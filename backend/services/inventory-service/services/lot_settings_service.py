from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.ledger_repo import record_transaction
from repositories.lot_repo import create_opening_lot, lot_totals_mismatch
from schemas.inventory import ALLOWED_DISPATCH_STRATEGIES, LotSettingsResponse, OpeningLotItem


async def update_lot_settings(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_id: str,
    user_id: str,
    role: Optional[str],
    feature_enabled: bool,
    batch_tracking: bool,
    expiry_tracking: bool,
    dispatch_strategy: Optional[str],
) -> LotSettingsResponse:
    if not feature_enabled:
        raise HTTPException(status_code=403, detail={"code": "FEATURE_NOT_ENABLED"})

    row = (await session.execute(
        text(
            "SELECT batch_tracking, expiry_tracking, dispatch_strategy FROM products "
            "WHERE id = :pid AND tenant_id = :tid FOR UPDATE"
        ),
        {"pid": product_id, "tid": tenant_id},
    )).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "PRODUCT_NOT_FOUND"})

    old_batch_tracking = bool(row.batch_tracking)
    old_expiry_tracking = bool(row.expiry_tracking)
    old_dispatch_strategy = row.dispatch_strategy

    # Validate and normalise.
    if dispatch_strategy is not None and dispatch_strategy not in ALLOWED_DISPATCH_STRATEGIES:
        raise HTTPException(status_code=422, detail={"code": "INVALID_DISPATCH_STRATEGY"})

    if expiry_tracking and not batch_tracking:
        raise HTTPException(status_code=422, detail={"code": "EXPIRY_NEEDS_BATCH"})

    if not batch_tracking:
        if dispatch_strategy is not None:
            raise HTTPException(status_code=422, detail={"code": "INVALID_DISPATCH_STRATEGY"})
        expiry_tracking = False
        dispatch_strategy = None
    elif expiry_tracking:
        if dispatch_strategy is not None and dispatch_strategy != "FEFO":
            raise HTTPException(status_code=422, detail={"code": "INVALID_DISPATCH_STRATEGY"})
        dispatch_strategy = "FEFO"
    else:
        if dispatch_strategy == "FEFO":
            raise HTTPException(status_code=422, detail={"code": "INVALID_DISPATCH_STRATEGY"})
        dispatch_strategy = dispatch_strategy or "FIFO"

    # batch true -> false: block if any lot still holds stock.
    if old_batch_tracking and not batch_tracking:
        lot_sum = (await session.execute(
            text(
                "SELECT COALESCE(SUM(quantity), 0) AS qty FROM lot_balances "
                "WHERE tenant_id = :tid AND product_id = :pid"
            ),
            {"tid": tenant_id, "pid": product_id},
        )).fetchone()
        if Decimal(str(lot_sum.qty)) > 0:
            raise HTTPException(status_code=409, detail={"code": "BATCH_TRACKING_IN_USE"})

    # batch false -> true: block while a transfer of this product is past approval.
    # Transfers still waiting for approval are fine — their lots are picked at approval.
    if not old_batch_tracking and batch_tracking:
        open_row = (await session.execute(
            text(
                "SELECT count(*) AS open_count FROM transfer_order_lines l "
                "JOIN transfer_orders o ON o.id = l.transfer_order_id "
                "WHERE l.tenant_id = :tid AND l.product_id = :pid "
                "AND o.status IN ('APPROVED','ADVISED','ISSUED','IN_TRANSIT','PARTIALLY_RECEIVED')"
            ),
            {"tid": tenant_id, "pid": product_id},
        )).fetchone()
        open_transfers = int(open_row.open_count)
        if open_transfers > 0:
            raise HTTPException(
                status_code=409,
                detail={"code": "BATCH_TRACKING_TRANSFERS_OPEN", "open_transfers": open_transfers},
            )

    await session.execute(
        text(
            "UPDATE products SET batch_tracking = :bt, expiry_tracking = :et, "
            "dispatch_strategy = :ds WHERE id = :pid AND tenant_id = :tid"
        ),
        {
            "bt": batch_tracking,
            "et": expiry_tracking,
            "ds": dispatch_strategy,
            "pid": product_id,
            "tid": tenant_id,
        },
    )

    opening_lots: list[OpeningLotItem] = []

    # batch false -> true (conversion): seed an opening lot per warehouse with on-hand stock.
    if not old_batch_tracking and batch_tracking:
        balances = (await session.execute(
            text(
                "SELECT ib.warehouse_id, COALESCE(n.code, w.code) AS warehouse_code, ib.quantity "
                "FROM inventory_balances ib "
                "LEFT JOIN organization_node n ON n.id = ib.warehouse_id AND n.tenant_id = ib.tenant_id "
                "LEFT JOIN warehouses        w ON w.id = ib.warehouse_id AND w.tenant_id = ib.tenant_id "
                "WHERE ib.tenant_id = :tid AND ib.product_id = :pid "
                "AND ib.lot_number IS NULL AND ib.quantity > 0"
            ),
            {"tid": tenant_id, "pid": product_id},
        )).fetchall()

        for b in balances:
            warehouse_code = b.warehouse_code or str(b.warehouse_id)[:8]
            lot_id, lot_number = await create_opening_lot(
                session, tenant_id, product_id, f"OPENING-{warehouse_code}", user_id
            )
            await record_transaction(
                session,
                tenant_id,
                "LOT_OPENING",
                product_id,
                str(b.warehouse_id),
                Decimal(str(b.quantity)),
                user_id,
                f"lot-opening:{product_id}:{b.warehouse_id}:{uuid.uuid4()}",
                lot_id=lot_id,
                lot_number=lot_number,
                source="OPENING_BALANCE",
            )
            opening_lots.append(
                OpeningLotItem(
                    warehouse_id=b.warehouse_id,
                    lot_id=uuid.UUID(lot_id),
                    lot_number=lot_number,
                    quantity=Decimal(str(b.quantity)),
                )
            )

            mismatch = await lot_totals_mismatch(session, tenant_id, product_id, str(b.warehouse_id))
            if mismatch is not None:
                raise HTTPException(status_code=500, detail={"code": "LOT_CONVERSION_MISMATCH"})

    await session.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'product:lot_settings_update', 'product', "
            "   :rid, 'GRANTED', CAST(:ctx AS jsonb))"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "uid": user_id,
            "role": role,
            "rid": product_id,
            "ctx": json.dumps({
                "old": {
                    "batch_tracking": old_batch_tracking,
                    "expiry_tracking": old_expiry_tracking,
                    "dispatch_strategy": old_dispatch_strategy,
                },
                "new": {
                    "batch_tracking": batch_tracking,
                    "expiry_tracking": expiry_tracking,
                    "dispatch_strategy": dispatch_strategy,
                },
                "opening_lots": [
                    {
                        "warehouse_id": str(ol.warehouse_id),
                        "lot_id": str(ol.lot_id),
                        "lot_number": ol.lot_number,
                        "quantity": str(ol.quantity),
                    }
                    for ol in opening_lots
                ],
            }),
        },
    )

    return LotSettingsResponse(
        batch_tracking=batch_tracking,
        expiry_tracking=expiry_tracking,
        dispatch_strategy=dispatch_strategy,
        opening_lots=opening_lots,
    )
