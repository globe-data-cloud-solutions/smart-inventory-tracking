"""Approval routing service (CLAUDE.md §15, §21, IMTS §6).

Translates the approval_rule table into an approval decision for a given
transfer type, quantity, and initiator role.  This is the single entry point
for "who needs to approve this transaction?".

Decision logic:
  1. Query approval_rule for the row whose quantity band contains the request.
  2. Compare the required approver's role level to the initiator's level.
  3. If initiator level >= required level → AUTO_APPROVED (next_status='APPROVED').
  4. Otherwise → PENDING_APPROVAL (the required approver role is returned so
     the outbox notification worker knows who to alert).

Role level constants mirror CLAUDE.md §13 hierarchy:
  SA(10) > TA(9) > NM(8) > RM(7) > WM(6)=LM(6) > SA_GT(4) > RT(3) > AU(2) > SYS(1)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

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
        )
        # decision.required_role == "RM"
        # decision.is_auto_approved == False
        # decision.next_status == "PENDING_APPROVAL"
    """

    _ROLE_LEVEL: ClassVar[dict[str, int]] = ROLE_LEVEL

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_required_approver(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
    ) -> str:
        """Return the approver_role from the first matching approval_rule band.

        Raises ValueError when no matching rule exists (configuration error —
        the tenant has not been seeded with approval rules for this type/qty).
        """
        result = await self.db.execute(
            text("""
                SELECT approver_role
                FROM   approval_rule
                WHERE  tenant_id        = :tid
                  AND  transaction_type = :tx_type
                  AND  is_active        = true
                  AND  (min_quantity IS NULL OR :qty >= min_quantity)
                  AND  (max_quantity IS NULL OR :qty <= max_quantity)
                ORDER BY approval_order ASC
                LIMIT 1
            """),
            {"tid": tenant_id, "tx_type": transfer_type, "qty": str(quantity)},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(
                f"No approval rule found for transfer_type={transfer_type!r} "
                f"qty={quantity} in tenant {tenant_id}. "
                f"Run scripts/seed_approval_rules.py to populate default rules."
            )
        return str(row[0])

    async def route_approval(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
        initiator_role: str,
    ) -> ApprovalDecision:
        """Return the full approval decision for the given scenario.

        Auto-approved when the initiator's role level >= the required approver level.
        NEVER assume authority from role alone — always resolve via approval_rule table.
        """
        required_role    = await self.get_required_approver(tenant_id, transfer_type, quantity)
        initiator_level  = self._ROLE_LEVEL.get(initiator_role, 0)
        required_level   = self._ROLE_LEVEL.get(required_role, 0)
        is_auto_approved = initiator_level >= required_level
        return ApprovalDecision(
            required_role    = required_role,
            is_auto_approved = is_auto_approved,
            next_status      = "APPROVED" if is_auto_approved else "PENDING_APPROVAL",
        )
