"""Self-approval policy checker for transfer submissions.

Called at DRAFT → PENDING_REVIEW (PULL) and DRAFT → PENDING_APPROVAL (PUSH).
Returns True when the submitter's self-approval policy permits skipping the
normal approval workflow and jumping directly to APPROVED.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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

    Looks up self_approval_policies for the submitter's (role_code, level_number).
    Returns False immediately if no policy exists or the transfer type / threshold
    conditions are not met.
    """
    if level_number is None:
        return False

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
        return False

    allowed_types = list(policy.transfer_types)
    if transfer_type not in allowed_types and "ALL" not in allowed_types:
        return False

    threshold_type: str = policy.threshold_type
    qty_limit: Optional[Decimal] = (
        Decimal(str(policy.qty_limit)) if policy.qty_limit is not None else None
    )
    value_limit: Optional[Decimal] = (
        Decimal(str(policy.value_limit)) if policy.value_limit is not None else None
    )

    if threshold_type == "QUANTITY":
        return qty_limit is None or quantity <= qty_limit

    if threshold_type == "VALUE":
        return value_limit is None or total_value <= value_limit

    if threshold_type == "EITHER":
        qty_ok = qty_limit is None or quantity <= qty_limit
        val_ok = value_limit is None or total_value <= value_limit
        return qty_ok or val_ok

    return False
