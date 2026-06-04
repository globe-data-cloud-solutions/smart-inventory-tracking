"""Async port of reference inventory_service.py aggregation patterns.

Key translation decisions:
  - Sync db.query() → await session.execute(text(...))
  - event_dispatcher.emit() removed — side effects use the Outbox pattern
  - Stock balance read from inventory_balances (running total) not SUM of ledger
    (faster; consistent with how we maintain balances on RECEIVE/TRANSFER)
  - Forecast consumption computed from inventory_transactions WHERE quantity < 0
    (TRANSFER_OUT, ISSUE, ADJUSTMENT with negative value)
  - pending_out from transfer_orders WHERE status = PENDING_APPROVAL only.
    RESERVE is written when entering PENDING_APPROVAL for all transfer types.
    Pre-PENDING_APPROVAL statuses (DRAFT, PENDING_REVIEW, PENDING_SOURCE_CONFIRM,
    PENDING_DEST_CONFIRM) carry no reservation. APPROVED/ISSUED/IN_TRANSIT excluded
    (on_hand already deducted via TRANSFER_OUT — would double-count).
  - in_transit_in from transfer_orders WHERE status = IN_TRANSIT (destination side)
  - requested_qty from transfer_requests WHERE status = PENDING
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.analytics import (
    CrossWarehouseStockOut,
    ForecastOut,
    InventoryStockOut,
    ReorderAlertOut,
    TransferHistoryItem,
)


# ── Current stock ──────────────────────────────────────────────────────────────

async def get_stock(
    session: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    warehouse_id: Optional[uuid.UUID] = None,
) -> List[InventoryStockOut]:
    """Return current stock levels with pending quantities.

    current_stock   : from inventory_balances (maintained running total)
    pending_out_qty : transfer_orders APPROVED or IN_TRANSIT from this warehouse
    in_transit_in   : transfer_orders IN_TRANSIT destined for this warehouse
    requested_qty   : transfer_requests PENDING against this warehouse as source
    """
    tenant_clause   = "AND ib.tenant_id = :tid" if tenant_id else ""
    warehouse_clause = "AND ib.warehouse_id = :wid" if warehouse_id else ""

    balance_sql = text(f"""
        SELECT
            ib.product_id,
            ib.warehouse_id,
            p.name                                AS product_name,
            p.sku                                 AS product_sku,
            COALESCE(w.name, on_node.name)        AS warehouse_name,
            COALESCE(w.warehouse_type::text, 'WAREHOUSE') AS warehouse_type,
            SUM(ib.quantity)                      AS current_stock
        FROM inventory_balances ib
        JOIN products          p       ON p.id       = ib.product_id
        LEFT JOIN warehouses   w       ON w.id       = ib.warehouse_id
        LEFT JOIN organization_node on_node ON on_node.id = ib.warehouse_id
        WHERE ib.lot_number IS NULL   -- aggregate running balance only; lot rows excluded
          {tenant_clause}
          {warehouse_clause}
        GROUP BY ib.product_id, ib.warehouse_id,
                 p.name, p.sku, w.name, w.warehouse_type, on_node.name
        ORDER BY p.name, COALESCE(w.name, on_node.name)
    """)

    params: dict = {}
    if tenant_id:
        params["tid"] = str(tenant_id)
    if warehouse_id:
        params["wid"] = str(warehouse_id)

    rows = (await session.execute(balance_sql, params)).fetchall()
    if not rows:
        return []

    results = []
    for r in rows:
        pid = r.product_id
        wid = r.warehouse_id
        tid_param = {"tid": str(tenant_id)} if tenant_id else {}

        # Soft holds: the RESERVE ledger entry is written when a transfer enters
        # PENDING_APPROVAL — for ALL types (PULL, PUSH, SISTER).
        # Statuses before PENDING_APPROVAL carry no reservation:
        #   DRAFT                  — no commitment; can be discarded freely
        #   PENDING_REVIEW (PULL)  — WH submitted; source not yet committed
        #   PENDING_SOURCE_CONFIRM — SISTER source confirm; no reservation yet
        #   PENDING_DEST_CONFIRM   — SISTER dest confirm; no reservation yet
        # APPROVED/ISSUED/IN_TRANSIT are excluded: current_stock already reflects
        # the APPROVED deduction via TRANSFER_OUT; including them double-subtracts.
        # Correct set: PENDING_APPROVAL only.
        pending_out_sql = text("""
            SELECT COALESCE(SUM(tol.quantity), 0)
            FROM transfer_order_lines tol
            JOIN transfer_orders to_ ON to_.id = tol.transfer_order_id
            WHERE to_.from_warehouse_id = :wid
              AND tol.product_id = :pid
              AND to_.status IN (
                'PENDING_APPROVAL'
              )
        """ + (" AND to_.tenant_id = :tid" if tenant_id else ""))
        pending_out = (
            await session.execute(pending_out_sql, {"wid": str(wid), "pid": str(pid), **tid_param})
        ).scalar() or Decimal("0")

        # In transit out: stock already deducted from On Hand (at APPROVED) and
        # physically moving — informational only, does NOT affect net_available.
        in_transit_out_sql = text("""
            SELECT COALESCE(SUM(tol.quantity), 0)
            FROM transfer_order_lines tol
            JOIN transfer_orders to_ ON to_.id = tol.transfer_order_id
            WHERE to_.from_warehouse_id = :wid
              AND tol.product_id = :pid
              AND to_.status IN ('ISSUED','IN_TRANSIT')
        """ + (" AND to_.tenant_id = :tid" if tenant_id else ""))
        in_transit_out = (
            await session.execute(in_transit_out_sql, {"wid": str(wid), "pid": str(pid), **tid_param})
        ).scalar() or Decimal("0")

        # In-transit inbound: orders destined for this warehouse that have physically
        # left the source (ISSUED) or are in motion (IN_TRANSIT, PARTIALLY_RECEIVED).
        # PARTIALLY_RECEIVED is included because the remaining un-received quantity is
        # still in transit — omitting it caused the inbound counter to drop to zero mid-way
        # through a partial receipt, which confused operators tracking expected stock.
        in_transit_sql = text("""
            SELECT COALESCE(SUM(tol.quantity), 0)
            FROM transfer_order_lines tol
            JOIN transfer_orders to_ ON to_.id = tol.transfer_order_id
            WHERE to_.to_warehouse_id = :wid
              AND tol.product_id = :pid
              AND to_.status IN ('IN_TRANSIT', 'PARTIALLY_RECEIVED')
        """ + (" AND to_.tenant_id = :tid" if tenant_id else ""))
        in_transit_in = (
            await session.execute(in_transit_sql, {"wid": str(wid), "pid": str(pid), **tid_param})
        ).scalar() or Decimal("0")

        # Requested: pending transfer requests sourcing from this warehouse
        requested_sql = text("""
            SELECT COALESCE(SUM(tr.quantity), 0)
            FROM transfer_requests tr
            WHERE tr.source_warehouse_id = :wid
              AND tr.product_id = :pid
              AND tr.status = 'PENDING'
        """ + (" AND tr.tenant_id = :tid" if tenant_id else ""))
        requested = (
            await session.execute(requested_sql, {"wid": str(wid), "pid": str(pid), **tid_param})
        ).scalar() or Decimal("0")

        results.append(
            InventoryStockOut(
                product_id=pid,
                product_name=r.product_name,
                product_sku=r.product_sku,
                warehouse_id=wid,
                warehouse_name=r.warehouse_name,
                warehouse_type=r.warehouse_type,
                current_stock=Decimal(str(r.current_stock)),
                pending_out_qty=Decimal(str(pending_out)),
                in_transit_out_qty=Decimal(str(in_transit_out)),
                in_transit_in_qty=Decimal(str(in_transit_in)),
                requested_qty=Decimal(str(requested)),
            )
        )

    return results


# ── Reorder alerts ─────────────────────────────────────────────────────────────

async def get_alerts(
    session: AsyncSession,
    tenant_id: Optional[uuid.UUID],
) -> List[ReorderAlertOut]:
    """Return all product/warehouse pairs where current_stock <= reorder_point."""
    stock_items = await get_stock(session, tenant_id)
    if not stock_items:
        return []

    product_ids = list({str(s.product_id) for s in stock_items})
    product_sql = text("""
        SELECT id, reorder_point, reorder_quantity
        FROM products
        WHERE id = ANY(:ids)
    """)
    product_rows = (
        await session.execute(product_sql, {"ids": product_ids})
    ).fetchall()
    reorder_map = {
        row.id: (row.reorder_point, row.reorder_quantity) for row in product_rows
    }

    alerts = []
    for item in stock_items:
        rp, rq = reorder_map.get(item.product_id, (None, None))
        if rp and rp > 0 and item.current_stock <= Decimal(str(rp)):
            alerts.append(
                ReorderAlertOut(
                    product_id=item.product_id,
                    product_name=item.product_name,
                    product_sku=item.product_sku,
                    warehouse_id=item.warehouse_id,
                    warehouse_name=item.warehouse_name,
                    current_stock=item.current_stock,
                    reorder_point=Decimal(str(rp)),
                    reorder_quantity=Decimal(str(rq)) if rq else None,
                    shortfall=Decimal(str(rp)) - item.current_stock,
                )
            )

    return sorted(alerts, key=lambda a: a.shortfall, reverse=True)


# ── Demand forecast ────────────────────────────────────────────────────────────

async def get_forecast(
    session: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    product_id: Optional[uuid.UUID] = None,
    days: int = 30,
) -> List[ForecastOut]:
    """Compute average daily consumption and estimated days until stockout.

    Consumption is derived from negative inventory_transactions
    (TRANSFER_OUT, ISSUE, ADJUSTMENT with quantity < 0).
    """
    stock_items = await get_stock(session, tenant_id)
    if product_id:
        stock_items = [s for s in stock_items if s.product_id == product_id]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    tid_clause = "AND it.tenant_id = :tid" if tenant_id else ""
    params_base: dict = {"cutoff": cutoff, "days": days}
    if tenant_id:
        params_base["tid"] = str(tenant_id)

    results = []
    for item in stock_items:
        consumption_sql = text(f"""
            SELECT COALESCE(SUM(ABS(it.quantity)), 0)
            FROM inventory_transactions it
            WHERE it.product_id  = :pid
              AND it.warehouse_id = :wid
              AND it.quantity < 0
              AND it.created_at  >= :cutoff
              {tid_clause}
        """)
        total_consumed = (
            await session.execute(
                consumption_sql,
                {"pid": str(item.product_id), "wid": str(item.warehouse_id), **params_base},
            )
        ).scalar() or 0

        avg_daily = float(total_consumed) / days if days > 0 else 0
        days_until = (
            round(float(item.current_stock) / avg_daily, 1) if avg_daily > 0 else None
        )

        results.append(
            ForecastOut(
                product_id=item.product_id,
                product_name=item.product_name,
                product_sku=item.product_sku,
                warehouse_id=item.warehouse_id,
                warehouse_name=item.warehouse_name,
                current_stock=item.current_stock,
                avg_daily_consumption=round(avg_daily, 2),
                days_until_stockout=days_until,
            )
        )

    # Sort by most urgent (fewest days remaining) first
    return sorted(
        results,
        key=lambda f: (f.days_until_stockout is None, f.days_until_stockout or float("inf")),
    )


# ── Cross-warehouse stock ──────────────────────────────────────────────────────

async def get_cross_warehouse_stock(
    session: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    product_id: uuid.UUID,
) -> CrossWarehouseStockOut:
    """Return stock of one product across all warehouses for this tenant."""
    tid_clause = "AND tenant_id = :tid" if tenant_id else ""
    check_sql = text(f"SELECT id, name, sku FROM products WHERE id = :pid {tid_clause}")
    params: dict = {"pid": str(product_id)}
    if tenant_id:
        params["tid"] = str(tenant_id)

    product_row = (await session.execute(check_sql, params)).fetchone()
    if not product_row:
        raise HTTPException(status_code=404, detail="Product not found")

    all_stock = await get_stock(session, tenant_id)
    product_rows = [s for s in all_stock if s.product_id == product_id]
    total = sum(s.current_stock for s in product_rows)

    return CrossWarehouseStockOut(
        product_id=product_id,
        product_name=product_row.name,
        product_sku=product_row.sku,
        total_stock=total,
        warehouses=product_rows,
    )


# ── Transfer history ───────────────────────────────────────────────────────────

async def get_transfer_history(
    session: AsyncSession,
    tenant_id: Optional[uuid.UUID],
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
) -> List[TransferHistoryItem]:
    """Return outbound transfer order history for a product at a specific warehouse."""
    tid_clause = "AND to_.tenant_id = :tid" if tenant_id else ""
    params: dict = {"pid": str(product_id), "wid": str(warehouse_id)}
    if tenant_id:
        params["tid"] = str(tenant_id)

    sql = text(f"""
        SELECT
            to_.id               AS transfer_id,
            to_.reference_number,
            to_.to_warehouse_id                          AS destination_warehouse_id,
            COALESCE(dw.name, dw_node.name)              AS destination_warehouse_name,
            tol.quantity,
            to_.status,
            to_.created_at
        FROM transfer_orders to_
        JOIN transfer_order_lines tol ON tol.transfer_order_id = to_.id
        LEFT JOIN warehouses dw                  ON dw.id      = to_.to_warehouse_id
        LEFT JOIN organization_node dw_node      ON dw_node.id = to_.to_warehouse_id
        WHERE to_.from_warehouse_id = :wid
          AND tol.product_id        = :pid
          {tid_clause}
        ORDER BY to_.created_at DESC
        LIMIT 200
    """)

    rows = (await session.execute(sql, params)).fetchall()

    return [
        TransferHistoryItem(
            transfer_id=r.transfer_id,
            reference_number=r.reference_number,
            destination_warehouse_id=r.destination_warehouse_id,
            destination_warehouse_name=r.destination_warehouse_name,
            quantity=Decimal(str(r.quantity)),
            status=r.status,
            created_at=r.created_at,
        )
        for r in rows
    ]
