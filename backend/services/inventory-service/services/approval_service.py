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

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

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


# ── Session 6: Dynamic position-based approval resolution ────────────────────


@dataclass
class ResolvedStep:
    """One step in the dynamically-resolved approval chain."""
    sequence:              int
    position_title:        str
    position_id:           Optional[str]
    node_id:               Optional[str]
    assigned_to_user_id:   Optional[str]
    assigned_to_name:      Optional[str]
    execution_mode:        str = "sequential"
    sla_hours:             Optional[int] = None
    is_vacant:             bool = False
    escalated:             bool = False
    status:                str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence":            self.sequence,
            "position_title":      self.position_title,
            "position_id":         self.position_id,
            "node_id":             self.node_id,
            "assigned_to_user_id": self.assigned_to_user_id,
            "assigned_to_name":    self.assigned_to_name,
            "execution_mode":      self.execution_mode,
            "sla_hours":           self.sla_hours,
            "is_vacant":           self.is_vacant,
            "escalated":           self.escalated,
            "status":              self.status,
        }


@dataclass
class ApprovalResolution:
    """Full resolution result — stored as JSON on the transfer order."""
    steps:        list[ResolvedStep]
    rule_id:      Optional[str] = None
    missing_rule: bool = False

    def steps_as_json(self) -> str:
        return json.dumps([s.to_dict() for s in self.steps])


# ── Helper: find matching transfer_approval_rules row ────────────────────────

async def _find_matching_rule(
    session:       AsyncSession,
    config_id:     str,
    src_level:     Optional[int],
    dst_level:     Optional[int],
    quantity:      Decimal,
    value:         Optional[Decimal],
) -> Optional[dict[str, Any]]:
    """Return the highest-priority rule that matches the transfer parameters.

    Specificity: rules with explicit source_level/dest_level take precedence
    over NULL (any-level) rules.  Within the same specificity, lower priority
    number wins.
    """
    result = await session.execute(
        text("""
            SELECT id, approval_steps, threshold_type,
                   quantity_min, quantity_max,
                   value_min, value_max,
                   source_level, destination_level,
                   priority
            FROM   transfer_approval_rules
            WHERE  transfer_type_config_id = :cid
            AND    is_active = true
            AND    (source_level IS NULL OR source_level = :sl)
            AND    (destination_level IS NULL OR destination_level = :dl)
            ORDER  BY
                -- more-specific rules first (non-NULL levels before NULL)
                (CASE WHEN source_level IS NOT NULL THEN 0 ELSE 1 END) +
                (CASE WHEN destination_level IS NOT NULL THEN 0 ELSE 1 END),
                priority ASC
        """),
        {"cid": config_id, "sl": src_level, "dl": dst_level},
    )
    rows = result.fetchall()
    for row in rows:
        # Threshold check
        tt = str(row.threshold_type)
        qty_ok = val_ok = True
        if tt in ("QUANTITY", "EITHER", "BOTH"):
            qty_min = Decimal(str(row.quantity_min)) if row.quantity_min is not None else Decimal("0")
            qty_max = Decimal(str(row.quantity_max)) if row.quantity_max is not None else None
            qty_ok = quantity >= qty_min and (qty_max is None or quantity <= qty_max)
        if tt in ("VALUE", "EITHER", "BOTH"):
            val_min = Decimal(str(row.value_min)) if row.value_min is not None else Decimal("0")
            val_max = Decimal(str(row.value_max)) if row.value_max is not None else None
            v = value or Decimal("0")
            val_ok = v >= val_min and (val_max is None or v <= val_max)
        if tt == "BOTH":
            if qty_ok and val_ok:
                return dict(id=str(row.id), approval_steps=row.approval_steps or [])
        elif tt in ("EITHER",):
            if qty_ok or val_ok:
                return dict(id=str(row.id), approval_steps=row.approval_steps or [])
        else:
            check = qty_ok if tt == "QUANTITY" else val_ok
            if check:
                return dict(id=str(row.id), approval_steps=row.approval_steps or [])
    return None


# ── Helper: get an org node ───────────────────────────────────────────────────

async def _get_node(
    session: AsyncSession, tenant_id: str, node_id: str,
) -> Optional[dict[str, Any]]:
    row = (await session.execute(
        text("SELECT id, name, hierarchy_level FROM organization_node WHERE id = :nid AND tenant_id = :tid"),
        {"nid": node_id, "tid": tenant_id},
    )).fetchone()
    return dict(id=str(row.id), name=row.name, level=row.hierarchy_level) if row else None


async def _get_parent_node(
    session: AsyncSession, tenant_id: str, node_id: str,
) -> Optional[dict[str, Any]]:
    """Return the PRIMARY_REPORTS_TO parent of a node."""
    row = (await session.execute(
        text("""
            SELECT n.id, n.name, n.hierarchy_level
            FROM   org_node_hierarchy h
            JOIN   organization_node n ON n.id = h.to_node_id
            WHERE  h.from_node_id         = :nid
            AND    h.tenant_id            = :tid
            AND    h.relationship_type    = 'PRIMARY_REPORTS_TO'
            LIMIT 1
        """),
        {"nid": node_id, "tid": tenant_id},
    )).fetchone()
    return dict(id=str(row.id), name=row.name, level=row.hierarchy_level) if row else None


# ── Helper: resolve which node to search for a step's position ───────────────

async def _resolve_node_for_step(
    session:       AsyncSession,
    tenant_id:     str,
    resolution:    str,
    src_node_id:   str,
    dst_node_id:   str,
    position_title: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Map a step resolution string to a specific org node."""
    res = resolution.upper()
    if res == "SOURCE":
        return await _get_node(session, tenant_id, src_node_id)
    if res == "DESTINATION":
        return await _get_node(session, tenant_id, dst_node_id)
    if res == "SOURCE_PARENT_NODE":
        return await _get_parent_node(session, tenant_id, src_node_id)
    if res == "DESTINATION_PARENT_NODE":
        return await _get_parent_node(session, tenant_id, dst_node_id)
    if res == "NEAREST_ANCESTOR_WITH_POSITION":
        # Traverse up from source until we find a node that has the requested position
        cur = src_node_id
        for _ in range(10):
            row = (await session.execute(
                text("""
                    SELECT COUNT(*) FROM positions
                    WHERE node_id = :nid AND tenant_id = :tid
                    AND is_active = true
                    AND (:title IS NULL OR title = :title)
                """),
                {"nid": cur, "tid": tenant_id, "title": position_title},
            )).scalar()
            if row and int(row) > 0:
                return await _get_node(session, tenant_id, cur)
            parent = await _get_parent_node(session, tenant_id, cur)
            if not parent:
                break
            cur = parent["id"]
        return None
    # TENANT_WIDE — no specific node, caller handles
    return None


# ── Helper: find a position at a node and its current holder ─────────────────

async def _find_position_and_holder(
    session:        AsyncSession,
    tenant_id:      str,
    node_id:        Optional[str],
    position_title: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return (position_id, holder_user_id, holder_name, actual_node_id).

    For TENANT_WIDE (node_id=None), searches any active position with the title.
    """
    # Build SQL dynamically to avoid asyncpg type-inference issues with nullable params
    if node_id and position_title:
        sql = text("SELECT p.id AS pos_id, pp.user_id, u.full_name, p.node_id FROM positions p LEFT JOIN personnel_positions pp ON pp.position_id = p.id AND pp.is_active = true AND pp.assignment_type = 'PRIMARY' AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE) LEFT JOIN users u ON u.id = pp.user_id AND u.is_active = true WHERE p.node_id = :nid AND p.tenant_id = :tid AND p.is_active = true AND p.title = :title LIMIT 1")
        row = (await session.execute(sql, {"nid": node_id, "tid": tenant_id, "title": position_title})).fetchone()
    elif node_id:
        sql = text("SELECT p.id AS pos_id, pp.user_id, u.full_name, p.node_id FROM positions p LEFT JOIN personnel_positions pp ON pp.position_id = p.id AND pp.is_active = true AND pp.assignment_type = 'PRIMARY' AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE) LEFT JOIN users u ON u.id = pp.user_id AND u.is_active = true WHERE p.node_id = :nid AND p.tenant_id = :tid AND p.is_active = true LIMIT 1")
        row = (await session.execute(sql, {"nid": node_id, "tid": tenant_id})).fetchone()
    elif position_title:
        sql = text("SELECT p.id AS pos_id, pp.user_id, u.full_name, p.node_id FROM positions p LEFT JOIN personnel_positions pp ON pp.position_id = p.id AND pp.is_active = true AND pp.assignment_type = 'PRIMARY' AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE) LEFT JOIN users u ON u.id = pp.user_id AND u.is_active = true WHERE p.tenant_id = :tid AND p.is_active = true AND p.title = :title LIMIT 1")
        row = (await session.execute(sql, {"tid": tenant_id, "title": position_title})).fetchone()
    else:
        sql = text("SELECT p.id AS pos_id, pp.user_id, u.full_name, p.node_id FROM positions p LEFT JOIN personnel_positions pp ON pp.position_id = p.id AND pp.is_active = true AND pp.assignment_type = 'PRIMARY' AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE) LEFT JOIN users u ON u.id = pp.user_id AND u.is_active = true WHERE p.tenant_id = :tid AND p.is_active = true LIMIT 1")
        row = (await session.execute(sql, {"tid": tenant_id})).fetchone()

    if not row:
        return None, None, None, node_id
    return (
        str(row.pos_id),
        str(row.user_id) if row.user_id else None,
        str(row.full_name) if row.full_name else None,
        str(row.node_id),
    )


async def _escalate_vacant(
    session:      AsyncSession,
    tenant_id:    str,
    position_id:  str,
) -> tuple[Optional[str], Optional[str], bool]:
    """Traverse reports_to chain until we find a holder, or fall back to NM.

    Returns (user_id, name, escalated_flag).
    """
    cur_pos = position_id
    for _ in range(10):
        parent_row = (await session.execute(
            text("""
                SELECT p.id, pp.user_id, u.full_name
                FROM   positions p
                LEFT JOIN personnel_positions pp
                       ON pp.position_id = p.id AND pp.is_active = true
                       AND pp.assignment_type = 'PRIMARY'
                       AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
                LEFT JOIN users u ON u.id = pp.user_id AND u.is_active = true
                WHERE  p.id = (SELECT reports_to_position_id FROM positions WHERE id = :pid)
                AND    p.tenant_id = :tid
            """),
            {"pid": cur_pos, "tid": tenant_id},
        )).fetchone()
        if not parent_row:
            break
        if parent_row.user_id:
            return str(parent_row.user_id), str(parent_row.full_name), True
        cur_pos = str(parent_row.id)

    # Fall back to any NM-level position holder
    nm_row = (await session.execute(
        text("""
            SELECT pp.user_id, u.full_name
            FROM   positions p
            JOIN   personnel_positions pp
                   ON pp.position_id = p.id AND pp.is_active = true
                   AND pp.assignment_type = 'PRIMARY'
                   AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
            JOIN   users u ON u.id = pp.user_id AND u.is_active = true
            WHERE  p.tenant_id = :tid
            AND    p.role_code IN ('NM')
            LIMIT  1
        """),
        {"tid": tenant_id},
    )).fetchone()
    if nm_row:
        return str(nm_row.user_id), str(nm_row.full_name), True
    return None, None, True


# ── Main entry point: resolve_transfer_approvers ─────────────────────────────

async def resolve_transfer_approvers(
    session:              AsyncSession,
    tenant_id:            str,
    transfer_type_config_id: Optional[str],
    from_warehouse_id:    str,
    to_warehouse_id:      str,
    quantity:             Decimal,
    total_value:          Optional[Decimal],
    created_by:           Optional[str],
    src_level:            Optional[int] = None,
    dst_level:            Optional[int] = None,
) -> ApprovalResolution:
    """Dynamic approval routing using transfer_approval_rules + positions.

    ── Level-matching convention ──────────────────────────────────────────────
    transfer_approval_rules.source_level      = hierarchy level of from_warehouse_id
                                                (the stock PROVIDER / sender node).
    transfer_approval_rules.destination_level = hierarchy level of to_warehouse_id
                                                (the stock RECEIVER / requester node).

    For a PULL transfer (WM at L3 requests stock from NM at L1):
      from_warehouse_id → L1 (HQ National, stock source)  → source_level = 1
      to_warehouse_id   → L3 (Bole Warehouse, requester)  → destination_level = 3
      Rule: {source_level: 1, destination_level: 3}

    For a PUSH transfer (NM at L1 proactively sends stock to WM at L3):
      from_warehouse_id → L1 (initiator, sender)          → source_level = 1
      to_warehouse_id   → L3 (receiver)                   → destination_level = 3
      Rule: {source_level: 1, destination_level: 3}

    The rule levels always match the physical FROM/TO node levels, regardless
    of which role "initiated" the request.  This is consistent with how
    _find_matching_rule passes src_level/dst_level to the SQL query.
    ──────────────────────────────────────────────────────────────────────────

    Resolution order:
      1. Find matching transfer_approval_rule for config/level/qty/value
      2. For each step, resolve the target node (source/dest/parent/tenant-wide)
      3. Find the position by title at that node
      4. Find the current PRIMARY holder
      5. If vacant → escalate up reports_to chain
      6. If holder == creator → escalate up reports_to chain
      7. No rule → fall back to any NM-role position holder

    Stores the full resolution on the transfer order so approval-info
    queries don't re-run the logic on every call.
    """
    # Auto-detect node levels if not provided
    if src_level is None:
        src_row = (await session.execute(
            text("SELECT hierarchy_level FROM organization_node WHERE id = :nid AND tenant_id = :tid"),
            {"nid": from_warehouse_id, "tid": tenant_id},
        )).fetchone()
        src_level = int(src_row.hierarchy_level) if src_row else None

    if dst_level is None:
        dst_row = (await session.execute(
            text("SELECT hierarchy_level FROM organization_node WHERE id = :nid AND tenant_id = :tid"),
            {"nid": to_warehouse_id, "tid": tenant_id},
        )).fetchone()
        dst_level = int(dst_row.hierarchy_level) if dst_row else None

    # Find matching rule
    rule: Optional[dict[str, Any]] = None
    if transfer_type_config_id:
        rule = await _find_matching_rule(
            session, transfer_type_config_id,
            src_level, dst_level, quantity, total_value,
        )

    # No rule → NM fallback
    if not rule:
        nm_row = (await session.execute(
            text("""
                SELECT pp.user_id, u.full_name, p.id AS pos_id, p.title, p.node_id
                FROM   positions p
                JOIN   personnel_positions pp
                       ON pp.position_id = p.id AND pp.is_active = true
                       AND pp.assignment_type = 'PRIMARY'
                       AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
                JOIN   users u ON u.id = pp.user_id AND u.is_active = true
                WHERE  p.tenant_id = :tid
                AND    p.role_code IN ('NM')
                LIMIT  1
            """),
            {"tid": tenant_id},
        )).fetchone()

        uid = str(nm_row.user_id) if nm_row and nm_row.user_id else None
        name = str(nm_row.full_name) if nm_row and nm_row.full_name else None
        title = str(nm_row.title) if nm_row else "National Manager"
        # Self-approval escalation for the fallback step
        if uid and uid == created_by:
            uid, name, _ = await _escalate_vacant(
                session, tenant_id, str(nm_row.pos_id) if nm_row else "fallback"
            )

        return ApprovalResolution(
            missing_rule=True,
            steps=[ResolvedStep(
                sequence=1,
                position_title=title,
                position_id=str(nm_row.pos_id) if nm_row else None,
                node_id=str(nm_row.node_id) if nm_row else None,
                assigned_to_user_id=uid,
                assigned_to_name=name,
                is_vacant=nm_row is None,
                escalated=nm_row is None,
            )],
        )

    # Resolve each step in the rule
    resolved_steps: list[ResolvedStep] = []
    for step in rule["approval_steps"]:
        seq         = int(step.get("sequence", len(resolved_steps) + 1))
        title       = step.get("position_title")
        resolution  = step.get("resolution", "TENANT_WIDE")
        exec_mode   = step.get("execution_mode", "sequential")
        sla         = step.get("sla_hours")

        # Resolve target node
        node = await _resolve_node_for_step(
            session, tenant_id, resolution,
            from_warehouse_id, to_warehouse_id, title,
        )
        node_id = node["id"] if node else None

        # Find position and holder
        pos_id, holder_uid, holder_name, actual_node_id = await _find_position_and_holder(
            session, tenant_id, node_id, title,
        )

        is_vacant = pos_id is not None and holder_uid is None
        escalated = False

        if is_vacant and pos_id:
            holder_uid, holder_name, escalated = await _escalate_vacant(session, tenant_id, pos_id)

        # Self-approval prevention
        if holder_uid and holder_uid == created_by:
            if pos_id:
                holder_uid, holder_name, escalated = await _escalate_vacant(session, tenant_id, pos_id)
            else:
                holder_uid, holder_name = None, None

        resolved_steps.append(ResolvedStep(
            sequence=seq,
            position_title=title or "Approver",
            position_id=pos_id,
            node_id=actual_node_id or node_id,
            assigned_to_user_id=holder_uid,
            assigned_to_name=holder_name,
            execution_mode=exec_mode,
            sla_hours=int(sla) if sla is not None else None,
            is_vacant=is_vacant,
            escalated=escalated,
        ))

    return ApprovalResolution(
        steps=resolved_steps,
        rule_id=rule["id"],
        missing_rule=False,
    )

