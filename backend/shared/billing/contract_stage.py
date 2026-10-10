"""Contract stage — derives a tenant's billing/access stage from
tenants.contract_end.

Stages: ACTIVE -> EXPIRING (<=14 days left) -> GRACE (<=14 days past end)
-> READ_ONLY (beyond grace). A missing contract_end means no contract date
was ever set and the tenant is never restricted.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CONTRACT_GRACE_DAYS = 14
EXPIRING_WARN_DAYS = 14


def compute_contract_stage(
    contract_end: Optional[Union[date, datetime]],
    today: date,
) -> str:
    """Pure function: contract_end + today -> stage string.

    No contract date set -> always ACTIVE (never restricted).
    """
    if contract_end is None:
        return "ACTIVE"

    if isinstance(contract_end, datetime):
        contract_end = contract_end.date()
    elif not isinstance(contract_end, date):
        logger.warning(
            "compute_contract_stage: unexpected contract_end type %r (%r) — "
            "treating as ACTIVE",
            type(contract_end), contract_end,
        )
        return "ACTIVE"

    if today <= contract_end:
        days_left = (contract_end - today).days
        return "EXPIRING" if days_left <= EXPIRING_WARN_DAYS else "ACTIVE"

    days_past = (today - contract_end).days
    return "GRACE" if days_past <= CONTRACT_GRACE_DAYS else "READ_ONLY"


async def get_tenant_contract_stage(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """Load contract_end for tenant_id and compute its current stage."""
    row = (await db.execute(
        text("SELECT contract_end FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )).fetchone()

    contract_end = row.contract_end if row else None
    today = datetime.utcnow().date()
    stage = compute_contract_stage(contract_end, today)

    grace_ends: Optional[date] = None
    read_only_since: Optional[date] = None
    if contract_end is not None:
        end_date = contract_end.date() if isinstance(contract_end, datetime) else contract_end
        grace_ends = end_date + timedelta(days=CONTRACT_GRACE_DAYS)
        read_only_since = grace_ends + timedelta(days=1)

    return {
        "stage": stage,
        "contract_end": contract_end,
        "grace_ends": grace_ends,
        "read_only_since": read_only_since,
    }
