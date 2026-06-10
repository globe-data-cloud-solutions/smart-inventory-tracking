"""Self-approval policy checker for transfer submissions.

Called at DRAFT → PENDING_REVIEW (PULL) and DRAFT → PENDING_APPROVAL (PUSH).
Returns True when the submitter's self-approval policy permits skipping the
normal approval workflow and jumping directly to APPROVED.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_self_approval_decision(
    session: AsyncSession,
    tenant_id: str,
    user_role: str,
    level_number: Optional[int],
    transfer_type: str,
    quantity: Decimal,
    total_value: Decimal,
) -> Optional[Any]:
    """Return the matching policy row if this transfer can be self-approved, else None.

    Looks up self_approval_policies for the submitter's (role_code, level_number).
    Returns None immediately if no policy exists or the transfer type / threshold
    conditions are not met. Returning the policy row (rather than a bare bool) lets
    callers record which policy and threshold permitted the self-approval, e.g. for
    audit logging.
    """
    if level_number is None:
        return None

    result = await session.execute(
        text("""
            SELECT transfer_types, threshold_type, qty_limit, value_limit
            FROM   self_approval_policies
            WHERE  tenant_id   = :tid
              AND  role_code   = :role
              AND  level_number = :level
              AND  is_active   = TRUE
            LIMIT 1
        """),
        {"tid": tenant_id, "role": user_role, "level": level_number},
    )
    policy = result.fetchone()

    if not policy:
        return None

    allowed_types = list(policy.transfer_types)
    if transfer_type not in allowed_types and "ALL" not in allowed_types:
        return None

    threshold_type: str = policy.threshold_type
    qty_limit: Optional[Decimal] = (
        Decimal(str(policy.qty_limit)) if policy.qty_limit is not None else None
    )
    value_limit: Optional[Decimal] = (
        Decimal(str(policy.value_limit)) if policy.value_limit is not None else None
    )

    if threshold_type == "QUANTITY":
        permitted = qty_limit is None or quantity <= qty_limit
    elif threshold_type == "VALUE":
        permitted = value_limit is None or total_value <= value_limit
    elif threshold_type == "EITHER":
        qty_ok = qty_limit is None or quantity <= qty_limit
        val_ok = value_limit is None or total_value <= value_limit
        permitted = qty_ok or val_ok
    else:
        permitted = False

    return policy if permitted else None


def _check_threshold(
    threshold_type: str,
    qty_limit: Optional[Decimal],
    value_limit: Optional[Decimal],
    quantity: Decimal,
    total_value: Decimal,
) -> bool:
    """Return True when (quantity, total_value) fall within the rule's threshold."""
    if threshold_type == "QUANTITY":
        return qty_limit is None or quantity <= qty_limit
    elif threshold_type == "VALUE":
        return value_limit is None or total_value <= value_limit
    elif threshold_type == "EITHER":
        qty_ok = qty_limit is None or quantity <= qty_limit
        val_ok = value_limit is None or total_value <= value_limit
        return qty_ok or val_ok
    return False


async def check_adjustment_self_approval(
    session: AsyncSession,
    tenant_id: Any,
    user: Any,
    reason_code: str,
    quantity: Decimal,
    total_value: Decimal,
) -> tuple[bool, Optional[str], Optional[dict]]:
    """Resolve the adjustment self-approval/routing decision for a submission.

    Looks up adjustment_approval_rules for the submitter's (role_code, level_number),
    preferring a PER_CODE rule that matches reason_code over a GLOBAL (reason_code IS NULL)
    rule, then by ascending priority.

    Returns (can_self_approve, approver_role_code, approver_position):
      (True,  None, None)              → within limit, no matching approver override → self-approve
      (False, role_code, None)         → exceeds limit or rule names a specific role → route to role_code
      (False, "TA", info)              → rule names a position, holder vacant → escalate to TA
      (False, role_code, info)         → rule names a position with an active holder → route to that
                                          user (info has approver_user_id/approver_name/approver_position_title);
                                          role_code is the position's holder role for legacy display
      (False, None, None)              → no matching rule, or rule exceeded → default routing
    """
    level_number = getattr(user, "level_number", None)
    if level_number is None:
        return False, None, None

    result = await session.execute(
        text("""
            SELECT
                approver_role_code,
                approver_position_id,
                threshold_type,
                qty_limit,
                value_limit,
                mode
            FROM adjustment_approval_rules
            WHERE tenant_id = :tid
              AND role_code = :role
              AND level_number = :level
              AND is_active = TRUE
              AND (
                reason_code = :reason
                OR reason_code IS NULL
              )
            ORDER BY
                CASE WHEN reason_code = :reason THEN 0 ELSE 1 END,
                priority ASC
            LIMIT 1
        """),
        {
            "tid": str(tenant_id),
            "role": str(user.role),
            "level": level_number,
            "reason": reason_code,
        },
    )
    rule = result.fetchone()

    # No rule → default routing
    if not rule:
        return False, None, None

    qty_limit: Optional[Decimal] = (
        Decimal(str(rule.qty_limit)) if rule.qty_limit is not None else None
    )
    value_limit: Optional[Decimal] = (
        Decimal(str(rule.value_limit)) if rule.value_limit is not None else None
    )

    within_limit = _check_threshold(
        rule.threshold_type, qty_limit, value_limit, quantity, total_value
    )

    if not within_limit:
        # Exceeds limit → default routing
        return False, None, None

    if rule.approver_position_id is not None:
        # Route to the current PRIMARY holder of the named position.
        holder = (await session.execute(
            text("""
                SELECT u.id AS user_id, u.full_name AS user_name,
                       p.title AS position_title, p.role_code AS position_role_code
                FROM   personnel_positions pp
                JOIN   users u     ON u.id = pp.user_id
                JOIN   positions p ON p.id = pp.position_id
                WHERE  pp.position_id = :pid
                  AND  pp.is_active = TRUE
                  AND  pp.assignment_type = 'PRIMARY'
                  AND  (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
                LIMIT 1
            """),
            {"pid": str(rule.approver_position_id)},
        )).fetchone()

        if holder is None:
            # Vacant position — escalate to Tenant Admin
            return False, "TA", {
                "approver_position_id": str(rule.approver_position_id),
                "escalated_vacant_position": True,
            }

        return False, holder.position_role_code, {
            "approver_position_id": str(rule.approver_position_id),
            "approver_user_id": str(holder.user_id),
            "approver_name": holder.user_name,
            "approver_position_title": holder.position_title,
        }

    if rule.approver_role_code is None:
        # Self-approve
        return True, None, None
    else:
        # Route to specific role (legacy)
        return False, rule.approver_role_code, None


async def check_self_approval(
    session: AsyncSession,
    tenant_id: str,
    user_role: str,
    level_number: Optional[int],
    transfer_type: str,
    quantity: Decimal,
    total_value: Decimal,
) -> bool:
    """Return True if this transfer can be self-approved by the submitter.

    Thin wrapper around get_self_approval_decision() for callers that only need
    the yes/no answer.
    """
    policy = await get_self_approval_decision(
        session=session,
        tenant_id=tenant_id,
        user_role=user_role,
        level_number=level_number,
        transfer_type=transfer_type,
        quantity=quantity,
        total_value=total_value,
    )
    return policy is not None
