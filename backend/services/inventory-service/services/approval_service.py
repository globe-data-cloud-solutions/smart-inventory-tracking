"""Approval routing service (CLAUDE.md §15, §21, IMTS §6, PROMPT C).

Translates the approval_rule table into an approval decision for a given
transfer type, quantity, initiator role, and (optionally) product.

Decision logic:
  1. Query approval_rule for the row whose quantity band contains the request.
  2. Compare the required approver's role level to the initiator's level.
  3. If initiator level >= required level → AUTO_APPROVED (next_status='APPROVED').
  4. Otherwise → PENDING_APPROVAL (the required approver role is returned so
     the outbox notification worker knows who to alert).

3-level fallback (PROMPT C):
  Level 1: Product-level rule  (approval_rule.product_id = product_id)
  Level 2: Tenant-level rule   (approval_rule.product_id IS NULL)
  Level 3: Org-type default    (_ORG_TYPE_DEFAULTS constant — never fails)

Role level constants mirror CLAUDE.md §13 hierarchy:
  SA(10) > TA(9) > NM(8) > RM(7) > WM(6)=LM(6) > SA_GT(4) > RT(3) > AU(2) > SYS(1)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Role privilege levels — canonical codes per CLAUDE.md §13 / §24 role mapping table
ROLE_LEVEL: dict[str, int] = {
    "SYS":   1,
    "AU":    2,
    "RT":    3,
    "SA_GT": 4,
    "WM":    6,
    "LM":    6,   # Logistics Manager — same level as WM per CLAUDE.md §13
    "RM":    7,
    "NM":    8,
    "TA":    9,
    "SA":   10,
}


@dataclass
class ApprovalDecision:
    """Result of routing an approval request through the approval_rule table.

    required_role    — minimum role code that must approve this transaction.
    is_auto_approved — True when the initiator's level >= required level.
    next_status      — transfer status to set: 'APPROVED' (auto) or
                       'PENDING_APPROVAL' (manual sign-off required).
    """
    required_role:    str
    is_auto_approved: bool
    next_status:      str


class ApprovalService:
    """Resolves approval routing decisions from the approval_rule table.

    Usage:
        svc = ApprovalService(db)
        decision = await svc.route_approval(
            tenant_id="...",
            transfer_type="PULL",
            quantity=Decimal("2000"),
            initiator_role="WM",
            product_id="<uuid>",   # optional — triggers product-level lookup first
        )
        # decision.required_role == "RM"
        # decision.is_auto_approved == False
        # decision.next_status == "PENDING_APPROVAL"
    """

    _ROLE_LEVEL: ClassVar[dict[str, int]] = ROLE_LEVEL

    # Fallback rules when neither product-level nor tenant-level rules exist.
    # Mirrors APPROVAL_DEFAULTS in wizard_service.py (PRODUCER org type).
    # These are the same bands seeded by scripts/seed_approval_rules.py.
    _ORG_TYPE_DEFAULTS: ClassVar[dict[str, list[tuple[Decimal, Optional[Decimal], str]]]] = {
        "PULL": [
            (Decimal("0"),    Decimal("999.9999"),  "WM"),
            (Decimal("1000"), Decimal("4999.9999"), "RM"),
            (Decimal("5000"), None,                 "NM"),
        ],
        "PUSH": [
            (Decimal("0"),    Decimal("4999.9999"), "NM"),
            (Decimal("5000"), None,                 "TA"),
        ],
        "ADJUSTMENT": [
            (Decimal("0"),    Decimal("99.9999"),  "WM"),
            (Decimal("100"),  Decimal("999.9999"), "RM"),
            (Decimal("1000"), None,               "TA"),
        ],
        "SISTER": [
            (Decimal("0"),    Decimal("999.9999"), "WM"),
            (Decimal("1000"), None,               "RM"),
        ],
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _query_rule(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
        product_id: Optional[str],
    ) -> Optional[str]:
        """Query approval_rule for a single matching band.

        product_id=None → tenant-level rules (product_id IS NULL).
        product_id=<uuid> → product-level rules for that specific product.
        Returns approver_role string or None when no matching row exists.
        """
        if product_id is not None:
            result = await self.db.execute(
                text("""
                    SELECT approver_role
                    FROM   approval_rule
                    WHERE  tenant_id        = :tid
                      AND  transaction_type = :tx_type
                      AND  product_id       = :pid
                      AND  is_active        = true
                      AND  (min_quantity IS NULL OR :qty >= min_quantity)
                      AND  (max_quantity IS NULL OR :qty <= max_quantity)
                    ORDER BY approval_order ASC
                    LIMIT 1
                """),
                {"tid": tenant_id, "tx_type": transfer_type,
                 "qty": str(quantity), "pid": product_id},
            )
        else:
            result = await self.db.execute(
                text("""
                    SELECT approver_role
                    FROM   approval_rule
                    WHERE  tenant_id        = :tid
                      AND  transaction_type = :tx_type
                      AND  product_id IS NULL
                      AND  is_active        = true
                      AND  (min_quantity IS NULL OR :qty >= min_quantity)
                      AND  (max_quantity IS NULL OR :qty <= max_quantity)
                    ORDER BY approval_order ASC
                    LIMIT 1
                """),
                {"tid": tenant_id, "tx_type": transfer_type, "qty": str(quantity)},
            )
        row = result.fetchone()
        return str(row[0]) if row else None

    @classmethod
    def _get_org_type_default(cls, transfer_type: str, quantity: Decimal) -> str:
        """Return the hardcoded org-type default approver for the given band.

        Used as the final fallback when neither product-level nor tenant-level
        rules exist.  Raises ValueError only for unknown transaction types —
        a qty for a known type always matches because the last band is open-ended.
        """
        bands = cls._ORG_TYPE_DEFAULTS.get(transfer_type)
        if not bands:
            raise ValueError(f"No default approval rule for transfer_type={transfer_type!r}")
        for min_qty, max_qty, role in bands:
            if quantity >= min_qty and (max_qty is None or quantity <= max_qty):
                return role
        raise ValueError(f"No default band matched {transfer_type} qty={quantity}")

    async def get_required_approver(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
        product_id: Optional[str] = None,
    ) -> str:
        """Return the approver_role using the 3-level fallback chain.

        1. Product-level rule  (if product_id provided and a matching row exists)
        2. Tenant-level rule   (product_id IS NULL in approval_rule)
        3. Org-type default    (_ORG_TYPE_DEFAULTS — never raises for valid types)
        """
        # Level 1: product-level override
        if product_id:
            role = await self._query_rule(tenant_id, transfer_type, quantity, product_id)
            if role:
                return role

        # Level 2: tenant-level rule
        role = await self._query_rule(tenant_id, transfer_type, quantity, None)
        if role:
            return role

        # Level 3: hardcoded org-type default
        return self._get_org_type_default(transfer_type, quantity)

    async def route_approval(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
        initiator_role: str,
        product_id: Optional[str] = None,
    ) -> ApprovalDecision:
        """Return the full approval decision for the given scenario.

        Auto-approved when the initiator's role level >= the required approver level.
        NEVER assume authority from role alone — always resolve via approval_rule table.
        Product-level rules take priority over tenant-level rules (PROMPT C §fallback).
        """
        required_role    = await self.get_required_approver(
            tenant_id, transfer_type, quantity, product_id
        )
        initiator_level  = self._ROLE_LEVEL.get(initiator_role, 0)
        required_level   = self._ROLE_LEVEL.get(required_role, 0)
        is_auto_approved = initiator_level >= required_level
        return ApprovalDecision(
            required_role    = required_role,
            is_auto_approved = is_auto_approved,
            next_status      = "APPROVED" if is_auto_approved else "PENDING_APPROVAL",
        )
