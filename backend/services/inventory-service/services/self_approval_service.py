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
