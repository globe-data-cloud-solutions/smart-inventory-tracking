"""Queries behind the three Reports endpoints (inventory-service, 2026-10-22).

All reads use the caller's read-replica session (never DATABASE_URL — see
CLAUDE.md §1 and docs/claude/business-rules.md Rule 17). Every query filters by
tenant_id explicitly, in addition to RLS, and by the caller's node scope
(resolve_node_scope: None = tenant-wide, a set = the caller's subtree).

Schema note: docs/claude/schema.md describes a `warehouse_stock` table with
on_hand/reserved columns; the live table (verified against
shared/db/models/inventory.py) is `inventory_balances`, which is lot-level
(product_id, warehouse_id, quantity, lot_number, expiry_date) with no
unit_cost column of its own — valuation here uses each product/warehouse's
most recent inventory_transactions.unit_cost as "last cost". This is a
pre-existing doc/code naming drift (see ClaudeE2EReviewBug.md), not something
fixed by this change.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.reports import DispatchRow, ExpiryAlertRow, MovementRow, ValuationRow


def _scope_clause(column: str, scope: Optional[set[str]]) -> tuple[str, dict]:
    """Build the SQL fragment + bind params for a resolved node scope.

    scope is None -> tenant-wide, no clause.
    scope is a (possibly empty) set -> restrict column to ANY(:scope_ids).
    An empty set still binds a valid (empty) array so the query runs and
    correctly returns zero rows, rather than being skipped.
    """
    if scope is None:
        return "", {}
    return f"AND {column} = ANY(CAST(:scope_ids AS uuid[]))", {"scope_ids": [str(s) for s in scope]}


async def get_inventory_valuation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scope: Optional[set[str]],
) -> list[ValuationRow]:
    clause, scope_params = _scope_clause("b.warehouse_id", scope)
    rows = (
        await db.execute(
            text(
                f"""
                WITH balances AS (
                    SELECT product_id, warehouse_id, SUM(quantity) AS on_hand
                    FROM inventory_balances
                    WHERE tenant_id = :tid AND quantity > 0
                    GROUP BY product_id, warehouse_id
                ),
                latest_cost AS (
                    SELECT DISTINCT ON (product_id, warehouse_id)
                        product_id, warehouse_id, unit_cost
                    FROM inventory_transactions
                    WHERE tenant_id = :tid AND unit_cost IS NOT NULL
                    ORDER BY product_id, warehouse_id, created_at DESC
                )
                SELECT b.product_id, p.sku, p.name, b.warehouse_id, wn.name AS warehouse_name, b.on_hand,
                       COALESCE(lc.unit_cost, 0) AS unit_cost,
                       b.on_hand * COALESCE(lc.unit_cost, 0) AS total_value
                FROM balances b
                JOIN products p ON p.id = b.product_id
                LEFT JOIN organization_node wn ON wn.id = b.warehouse_id
                LEFT JOIN latest_cost lc
                    ON lc.product_id = b.product_id AND lc.warehouse_id = b.warehouse_id
                WHERE 1=1 {clause}
                ORDER BY p.name, b.warehouse_id
                """
            ),
            {"tid": str(tenant_id), **scope_params},
        )
    ).fetchall()
    return [
        ValuationRow(
            product_id=r.product_id,
            sku=r.sku,
            name=r.name,
            warehouse_id=r.warehouse_id,
            warehouse_name=r.warehouse_name,
            on_hand=r.on_hand,
            unit_cost=r.unit_cost,
            total_value=r.total_value,
        )
        for r in rows
    ]


async def get_stock_movement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scope: Optional[set[str]],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 500,
) -> list[MovementRow]:
    clause, scope_params = _scope_clause("it.warehouse_id", scope)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT it.id AS transaction_id, it.transaction_date, it.type,
                       it.product_id, p.sku, p.name, it.warehouse_id,
                       wn.name AS warehouse_name, it.quantity, it.unit_cost, it.lot_number, it.created_at
                FROM inventory_transactions it
                JOIN products p ON p.id = it.product_id
                LEFT JOIN organization_node wn ON wn.id = it.warehouse_id
                WHERE it.tenant_id = :tid
                  AND it.transaction_date >= COALESCE(CAST(:date_from AS date), CURRENT_DATE - INTERVAL '30 days')
                  AND it.transaction_date <= COALESCE(CAST(:date_to AS date), CURRENT_DATE)
                  {clause}
                ORDER BY it.transaction_date DESC, it.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "tid": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
                **scope_params,
            },
        )
    ).fetchall()
    return [
        MovementRow(
            transaction_id=r.transaction_id,
            transaction_date=r.transaction_date,
            type=r.type,
            product_id=r.product_id,
            sku=r.sku,
            name=r.name,
            warehouse_id=r.warehouse_id,
            warehouse_name=r.warehouse_name,
            quantity=r.quantity,
            unit_cost=r.unit_cost,
            lot_number=r.lot_number,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def get_expiry_alerts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scope: Optional[set[str]],
    window_days: int = 30,
) -> list[ExpiryAlertRow]:
    clause, scope_params = _scope_clause("ib.warehouse_id", scope)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT ib.product_id, p.sku, p.name, ib.warehouse_id, wn.name AS warehouse_name, ib.lot_number,
                       ib.expiry_date, ib.quantity,
                       (ib.expiry_date - CURRENT_DATE) AS days_to_expiry
                FROM inventory_balances ib
                JOIN products p ON p.id = ib.product_id
                LEFT JOIN organization_node wn ON wn.id = ib.warehouse_id
                WHERE ib.tenant_id = :tid
                  AND ib.quantity > 0
                  AND ib.expiry_date IS NOT NULL
                  AND ib.expiry_date <= CURRENT_DATE + (CAST(:window_days AS integer) * INTERVAL '1 day')
                  {clause}
                ORDER BY ib.expiry_date ASC
                """
            ),
            {"tid": str(tenant_id), "window_days": window_days, **scope_params},
        )
    ).fetchall()
    return [
        ExpiryAlertRow(
            product_id=r.product_id,
            sku=r.sku,
            name=r.name,
            warehouse_id=r.warehouse_id,
            warehouse_name=r.warehouse_name,
            lot_number=r.lot_number,
            expiry_date=r.expiry_date,
            quantity=r.quantity,
            days_to_expiry=r.days_to_expiry,
        )
        for r in rows
    ]


async def get_dispatch_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scope: Optional[set[str]],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    product_id: Optional[str] = None,
    transfer_order_id: Optional[str] = None,
    limit: int = 500,
) -> list[DispatchRow]:
    """Dispatches (TRANSIT_OUT transfer ledger rows) grouped to one row per product.

    A dispatch is in scope when its source or destination warehouse is in the
    caller's scope (None = tenant-wide, set() = nothing).
    """
    if scope is None:
        scope_clause, scope_params = "", {}
    else:
        scope_clause = (
            "AND (it.warehouse_id = ANY(CAST(:scope_ids AS uuid[])) "
            "OR tor.to_warehouse_id = ANY(CAST(:scope_ids AS uuid[])))"
        )
        scope_params = {"scope_ids": sorted(scope)}
    rows = (
        await db.execute(
            text(
                f"""
                SELECT it.reference_id AS transfer_order_id,
                       MAX(it.transaction_date) AS dispatched_on,
                       it.warehouse_id AS from_warehouse_id,
                       wf.name AS from_warehouse_name,
                       tor.to_warehouse_id,
                       wt.name AS to_warehouse_name,
                       it.product_id, p.sku, p.name,
                       SUM(it.quantity) AS quantity_dispatched,
                       COUNT(DISTINCT it.lot_number) AS lots_used,
                       (SELECT COUNT(*) FROM transfer_line_allocations a
                         WHERE a.tenant_id = it.tenant_id
                           AND a.transfer_order_id = it.reference_id
                           AND a.product_id = it.product_id
                           AND a.is_override) AS overrides
                FROM inventory_transactions it
                JOIN transfer_orders tor
                  ON tor.id = it.reference_id AND tor.tenant_id = it.tenant_id
                JOIN products p ON p.id = it.product_id
                LEFT JOIN organization_node wf ON wf.id = it.warehouse_id
                LEFT JOIN organization_node wt ON wt.id = tor.to_warehouse_id
                WHERE it.tenant_id = :tid
                  AND it.type = 'TRANSIT_OUT'
                  AND it.transaction_date >= COALESCE(CAST(:date_from AS date), CURRENT_DATE - INTERVAL '30 days')
                  AND it.transaction_date <= COALESCE(CAST(:date_to AS date), CURRENT_DATE)
                  AND (CAST(:product_id AS uuid) IS NULL OR it.product_id = CAST(:product_id AS uuid))
                  AND (CAST(:transfer_order_id AS uuid) IS NULL
                       OR it.reference_id = CAST(:transfer_order_id AS uuid))
                  {scope_clause}
                GROUP BY it.tenant_id, it.reference_id, it.warehouse_id, wf.name,
                         tor.to_warehouse_id, wt.name, it.product_id, p.sku, p.name
                ORDER BY dispatched_on DESC, p.sku
                LIMIT :limit
                """
            ),
            {
                "tid": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
                "product_id": product_id,
                "transfer_order_id": transfer_order_id,
                "limit": limit,
                **scope_params,
            },
        )
    ).fetchall()
    return [
        DispatchRow(
            transfer_order_id=r.transfer_order_id,
            dispatched_on=r.dispatched_on,
            from_warehouse_id=r.from_warehouse_id,
            from_warehouse_name=r.from_warehouse_name,
            to_warehouse_id=r.to_warehouse_id,
            to_warehouse_name=r.to_warehouse_name,
            product_id=r.product_id,
            sku=r.sku,
            name=r.name,
            quantity_dispatched=r.quantity_dispatched,
            lots_used=r.lots_used,
            overrides=r.overrides,
        )
        for r in rows
    ]
