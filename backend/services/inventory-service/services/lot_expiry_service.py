"""Set an expiry once on a lot that has none (PATCH /inventory/lots/{id}/expiry).

Metadata-only: no ledger row, no inventory_transactions, no lot_balances change.
The write is race-safe — the UPDATE only matches while expiry_date IS NULL.
Audit follows lot_settings_service: an INSERT into audit_logs in the same
transaction as the change.

Also the tenant near-expiry window (tenants.near_expiry_days, migration 089):
get_near_expiry_days() is read by the lot list and expiry-alert routes when no
window is passed; set_near_expiry_days() is the TA write path, audited the
same way.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


DEFAULT_NEAR_EXPIRY_DAYS = 30


async def get_near_expiry_days(session: AsyncSession, tenant_id: Any) -> int:
    """The tenant's near-expiry window; 30 for SA across tenants or no row."""
    if tenant_id is None:
        return DEFAULT_NEAR_EXPIRY_DAYS
    row = (
        await session.execute(
            text("SELECT near_expiry_days FROM tenants WHERE id = :tid"),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    if row is None or row.near_expiry_days is None:
        return DEFAULT_NEAR_EXPIRY_DAYS
    return int(row.near_expiry_days)


async def set_near_expiry_days(
    session: AsyncSession,
    tenant_id: str,
    near_expiry_days: int,
    user: Any,
) -> int:
    old = (
        await session.execute(
            text("SELECT near_expiry_days FROM tenants WHERE id = :tid FOR UPDATE"),
            {"tid": tenant_id},
        )
    ).fetchone()
    if old is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})

    await session.execute(
        text("UPDATE tenants SET near_expiry_days = :d, updated_at = now() WHERE id = :tid"),
        {"d": near_expiry_days, "tid": tenant_id},
    )

    await session.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'tenant:near_expiry_days_update', 'tenant', "
            "   :rid, 'GRANTED', CAST(:ctx AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": str(user.user_id),
            "role": getattr(user, "role", None),
            "rid": tenant_id,
            "ctx": json.dumps(
                {
                    "old_near_expiry_days": old.near_expiry_days,
                    "new_near_expiry_days": near_expiry_days,
                }
            ),
        },
    )
    return near_expiry_days


def _already_set(lot_number: str, existing: date) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "LOT_EXPIRY_ALREADY_SET",
            "lot_number": lot_number,
            "existing_expiry": existing.isoformat(),
        },
    )


async def _load_lot(session: AsyncSession, tenant_id: str, lot_id: str):
    return (
        await session.execute(
            text(
                "SELECT l.id, l.lot_number, l.product_id, l.expiry_date, "
                "       p.batch_tracking, p.expiry_tracking "
                "FROM stock_lots l "
                "JOIN products p ON p.id = l.product_id AND p.tenant_id = l.tenant_id "
                "WHERE l.id = :lid AND l.tenant_id = :tid"
            ),
            {"lid": lot_id, "tid": tenant_id},
        )
    ).fetchone()


async def set_lot_expiry(
    session: AsyncSession,
    tenant_id: str,
    lot_id: str,
    expiry_date: date,
    user: Any,
) -> dict:
    lot = await _load_lot(session, tenant_id, lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail={"code": "LOT_NOT_FOUND"})

    if not (lot.batch_tracking and lot.expiry_tracking):
        raise HTTPException(
            status_code=422,
            detail={"code": "EXPIRY_TRACKING_OFF", "lot_number": lot.lot_number},
        )

    if lot.expiry_date is not None:
        raise _already_set(lot.lot_number, lot.expiry_date)

    if expiry_date < date.today():
        raise HTTPException(status_code=422, detail={"code": "EXPIRY_IN_PAST"})

    row = (
        await session.execute(
            text(
                "UPDATE stock_lots SET expiry_date = :exp "
                "WHERE id = :lid AND tenant_id = :tid AND expiry_date IS NULL "
                "RETURNING id, lot_number, product_id, expiry_date"
            ),
            {"exp": expiry_date, "lid": lot_id, "tid": tenant_id},
        )
    ).fetchone()
    if row is None:
        # Another request set the expiry between our read and the UPDATE.
        current = await _load_lot(session, tenant_id, lot_id)
        if current is None:
            raise HTTPException(status_code=404, detail={"code": "LOT_NOT_FOUND"})
        raise _already_set(current.lot_number, current.expiry_date)

    await session.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'lot:set_expiry', 'stock_lot', "
            "   :rid, 'GRANTED', CAST(:ctx AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": str(user.user_id),
            "role": getattr(user, "role", None),
            "rid": str(row.id),
            "ctx": json.dumps(
                {
                    "lot_id": str(row.id),
                    "lot_number": row.lot_number,
                    "product_id": str(row.product_id),
                    "expiry_date": row.expiry_date.isoformat(),
                    "reason": "expiry set once (was empty)",
                }
            ),
        },
    )

    return {
        "lot_id": row.id,
        "lot_number": row.lot_number,
        "product_id": row.product_id,
        "expiry_date": row.expiry_date,
    }
