"""Approval routing service (CLAUDE.md §15, §21, IMTS §6).

Single interface: resolve_approval() — module-level async function.

3-step resolution using authority_level / auto_approve / notify_levels columns:
  Step 1: product_approval_minimums authority floor (per-product override)
  Step 2: approval_rule quantity band (SISTER always queries PULL bands)
  Step 3: required_level = min(product_min, threshold_level); escalation if
          required_level >= requester_authority_level (requester cannot self-approve)

Authority level scale (lower = higher authority):
  SA/TA/NM = 1,  RM = 2,  LM = 3,  WM = 4
  Stored in approval_rule.authority_level and product_approval_minimums.min_authority_level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── Role scale constants ──────────────────────────────────────────────────────

# Authority tier (lower = higher authority).
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
) -> Optional[ThresholdRow]:
    """Query approval_rule for the matching quantity band (tenant-level rules only).

    Reads authority_level, auto_approve, and notify_levels added by migration 027.
    Returns None when no matching row exists (caller decides fallback strategy).
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
    return None


async def resolve_approval(
    session: AsyncSession,
    tenant_id: str,
    transaction_type: str,
    quantity: Decimal,
    product_id: Optional[str] = None,
    simple_mode: bool = True,
    requester_authority_level: Optional[int] = None,
) -> ApprovalDecision:
    """3-step approval resolution for a transfer or adjustment.

    Step 1: product_approval_minimums — per-product authority floor override.
    Step 2: approval_rule quantity band.  SISTER uses PULL bands (PRD-APPENDIX §B9).
            When simple_mode=False and no custom rule exists for the type, falls back
            to PULL rules before using hardcoded org-type defaults.
    Step 3: required_level = min(product_min, threshold_level) — lower = more restrictive.
    Step 4: escalation — if the required level >= requester_authority_level (same role or
            lower authority), bump up by one level so requesters cannot approve their own
            transfers.  auto_approve is suppressed when escalation fires.

    auto_approve is True only when:
      - the band is marked auto_approve=True AND
      - no product-level minimum override is in effect AND
      - the band's authority level is used unchanged AND
      - no escalation was applied.
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

    # Custom mode fallback: if no rule found for this type, try PULL before org defaults
    if threshold is None and not simple_mode and lookup_type != "PULL":
        threshold = await _query_threshold(session, tenant_id, "PULL", quantity)

    if threshold is None:
        threshold = _get_default_threshold(lookup_type, quantity)

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

    # Step 4: escalation — requester cannot approve their own transfer.
    # If the resolved level is the same or lower authority than the requester
    # (same number or larger number), bump up one level (smaller number = higher auth).
    escalated = False
    if requester_authority_level is not None and required_level >= requester_authority_level:
        required_level = max(1, requester_authority_level - 1)
        is_auto = False
        escalated = True

    if escalated:
        role_display = _ROLE_DISPLAY.get(required_level, threshold.approver_role)
        if required_level == requester_authority_level:
            # Ceiling: requester is already at the highest authority (level 1).
            # Escalation fired but the level could not increase further.
            # A DIFFERENT user at the same level must approve.
            reason = (
                f"Any {role_display} approval must come from a different user "
                f"— not the creator (highest operational authority, level {requester_authority_level})."
            )
        else:
            reason = (
                f"Escalated: requester authority (level {requester_authority_level}) cannot "
                f"self-approve. Now requires {role_display} (level {required_level})."
            )
    elif product_min is not None and product_min < threshold_level:
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

