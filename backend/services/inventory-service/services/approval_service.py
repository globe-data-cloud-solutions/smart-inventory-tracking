"""Approval routing service (CLAUDE.md §15, §21, IMTS §6, PROMPT 2A).

Two interfaces:
  resolve_approval()   — module-level async function; 3-step resolution using the
                         new authority_level / auto_approve / notify_levels columns
                         added by migration 027.  Use this in all new code.
  ApprovalService      — legacy class kept for backward compatibility with existing
                         tests and callers that use route_approval() / get_required_approver().

Authority level scale (lower = higher authority):
  SA/TA/NM = 1,  RM = 2,  LM = 3,  WM = 4
  Stored in approval_rule.authority_level and product_approval_minimums.min_authority_level.

Old ROLE_LEVEL scale (SA=10 highest) is retained for backward compat with ApprovalService.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── Role scale constants ──────────────────────────────────────────────────────

# Old privilege scale: CLAUDE.md §13 role hierarchy (SA=10 highest)
# Used by ApprovalService.route_approval() for backward compatibility.
ROLE_LEVEL: dict[str, int] = {
    "SYS":   1,
    "AU":    2,
    "RT":    3,
    "SA_GT": 4,
    "WM":    6,
    "LM":    6,
    "RM":    7,
    "NM":    8,
    "TA":    9,
    "SA":   10,
}

# New authority tier (lower = higher authority).
# Matches authority_level column added by migration 027.
ROLE_AUTHORITY_LEVEL: dict[str, int] = {
    "SA":    1,
    "TA":    1,
    "NM":    1,
    "RM":    2,
    "LM":    3,
    "WM":    4,
    "SA_GT": 5,
    "RT":    5,
    "AU":    5,
    "SYS":   5,
}

_ROLE_DISPLAY: dict[int, str] = {
    1: "National Manager / Tenant Admin",
    2: "Regional Manager",
    3: "Logistics Manager",
    4: "Warehouse Manager",
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ThresholdRow:
    approver_role:   str
    authority_level: int
    auto_approve:    bool
    notify_levels:   list[int]


@dataclass
class ApprovalDecision:
    """Approval routing result.

    Backward-compat fields (used by legacy ApprovalService callers):
      required_role, is_auto_approved, next_status

    New fields added by PROMPT 2 (default to safe values if not set):
      required_authority_level, notify_levels, reason
    """
    required_role:            str
    is_auto_approved:         bool
    next_status:              str
    required_authority_level: int           = 4
    notify_levels:            list[int]     = field(default_factory=list)
    reason:                   str           = ""

    @property
    def is_auto_approve(self) -> bool:
        return self.is_auto_approved

    @property
    def required_role_display(self) -> str:
        return _ROLE_DISPLAY.get(self.required_authority_level, self.required_role)


# ── Org-type fallback bands ───────────────────────────────────────────────────
# Used when no approval_rule row exists for the tenant/type combination.
# Extended with RECEIVE/ISSUE from migration 027.

_ORG_TYPE_DEFAULTS: dict[str, list[tuple[Decimal, Optional[Decimal], str]]] = {
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
    "RECEIVE": [
        (Decimal("0"),    Decimal("199.9999"), "WM"),
        (Decimal("200"),  None,               "RM"),
    ],
    "ISSUE": [
        (Decimal("0"),    Decimal("199.9999"), "WM"),
        (Decimal("200"),  None,               "RM"),
    ],
}


def _get_default_threshold(transaction_type: str, quantity: Decimal) -> ThresholdRow:
    bands = _ORG_TYPE_DEFAULTS.get(transaction_type)
    if not bands:
        raise ValueError(f"No default approval rule for transaction_type={transaction_type!r}")
    for min_qty, max_qty, role in bands:
        if quantity >= min_qty and (max_qty is None or quantity <= max_qty):
            return ThresholdRow(
                approver_role=role,
                authority_level=ROLE_AUTHORITY_LEVEL.get(role, 4),
                auto_approve=False,
                notify_levels=[],
            )
    raise ValueError(f"No default band matched {transaction_type} qty={quantity}")


async def _query_threshold(
    session: AsyncSession,
    tenant_id: str,
    transaction_type: str,
    quantity: Decimal,
) -> ThresholdRow:
    """Query approval_rule for the matching quantity band (tenant-level rules only).

    Reads authority_level, auto_approve, and notify_levels added by migration 027.
    Falls back to _get_default_threshold() when no matching row exists.
    """
    result = await session.execute(
        text("""
            SELECT approver_role, authority_level, auto_approve, notify_levels
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
        {"tid": tenant_id, "tx_type": transaction_type, "qty": str(quantity)},
    )
    row = result.fetchone()
    if row:
        notify = list(row[3]) if row[3] else []
        return ThresholdRow(
            approver_role=str(row[0]),
            authority_level=int(row[1]),
            auto_approve=bool(row[2]),
            notify_levels=notify,
        )
    return _get_default_threshold(transaction_type, quantity)


async def resolve_approval(
    session: AsyncSession,
    tenant_id: str,
    transaction_type: str,
    quantity: Decimal,
    product_id: Optional[str] = None,
) -> ApprovalDecision:
    """3-step approval resolution for a transfer or adjustment.

    Step 1: product_approval_minimums — per-product authority floor override.
    Step 2: approval_rule quantity band.  SISTER uses PULL bands (PRD-APPENDIX §B9).
    Step 3: required_level = min(product_min, threshold_level) — lower = more restrictive.

    auto_approve is True only when:
      - the band is marked auto_approve=True AND
      - no product-level minimum override is in effect AND
      - the band's authority level is used unchanged.
    """
    # Step 1: per-product authority floor
    product_min: Optional[int] = None
    if product_id:
        result = await session.execute(
            text(
                "SELECT min_authority_level FROM product_approval_minimums "
                "WHERE product_id = :pid AND transaction_type = :type"
            ),
            {"pid": product_id, "type": transaction_type},
        )
        pam_row = result.fetchone()
        if pam_row:
            product_min = int(pam_row[0])

    # Step 2: quantity-band threshold (SISTER → PULL lookup)
    lookup_type = "PULL" if transaction_type == "SISTER" else transaction_type
    threshold = await _query_threshold(session, tenant_id, lookup_type, quantity)

    # Step 3: take more restrictive level (lower number = higher authority)
    threshold_level = threshold.authority_level
    required_level = (
        min(product_min, threshold_level) if product_min is not None else threshold_level
    )

    is_auto = (
        threshold.auto_approve
        and product_min is None
        and required_level == threshold_level
    )

    if product_min is not None and product_min < threshold_level:
        reason = (
            f"Product authority floor (level {product_min}) overrides "
            f"quantity band (level {threshold_level}) for qty={quantity}."
        )
    else:
        role_display = _ROLE_DISPLAY.get(required_level, threshold.approver_role)
        reason = (
            f"Qty {quantity} requires {role_display} approval (level {required_level})."
        )

    return ApprovalDecision(
        required_role=threshold.approver_role,
        is_auto_approved=is_auto,
        next_status="APPROVED" if is_auto else "PENDING_APPROVAL",
        required_authority_level=required_level,
        notify_levels=threshold.notify_levels or [],
        reason=reason,
    )


# ── ApprovalService — legacy class-based interface ────────────────────────────

class ApprovalService:
    """Legacy approval service.

    Uses the old ROLE_LEVEL (SA=10) scale for auto-approve decisions.
    New code should use the module-level resolve_approval() function instead.
    """

    _ROLE_LEVEL: ClassVar[dict[str, int]] = ROLE_LEVEL
    _ORG_TYPE_DEFAULTS: ClassVar[dict[str, list[tuple[Decimal, Optional[Decimal], str]]]] = (
        _ORG_TYPE_DEFAULTS
    )

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _query_rule(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
        product_id: Optional[str],
    ) -> Optional[str]:
        """Query approval_rule for approver_role only.

        product_id=None → tenant-level rules (product_id IS NULL).
        product_id=<uuid> → product-level rules for that product.
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
        if product_id:
            role = await self._query_rule(tenant_id, transfer_type, quantity, product_id)
            if role:
                return role
        role = await self._query_rule(tenant_id, transfer_type, quantity, None)
        if role:
            return role
        return self._get_org_type_default(transfer_type, quantity)

    async def route_approval(
        self,
        tenant_id: str,
        transfer_type: str,
        quantity: Decimal,
        initiator_role: str,
        product_id: Optional[str] = None,
    ) -> ApprovalDecision:
        required_role    = await self.get_required_approver(
            tenant_id, transfer_type, quantity, product_id
        )
        initiator_level  = self._ROLE_LEVEL.get(initiator_role, 0)
        required_level   = self._ROLE_LEVEL.get(required_role, 0)
        is_auto_approved = initiator_level >= required_level
        return ApprovalDecision(
            required_role=required_role,
            is_auto_approved=is_auto_approved,
            next_status="APPROVED" if is_auto_approved else "PENDING_APPROVAL",
        )
