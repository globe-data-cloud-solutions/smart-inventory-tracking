"""Lot-allocation override log and FEFO compliance summary (read-only).

  list_overrides     the lot_allocation_overrides rows (083), newest first
  override_summary   how often the suggested lots were followed
  compliance_rate    the rate arithmetic, pure

Sources (all filtered by tenant_id):
  lot_allocation_overrides   one row per overridden decision (TRANSFER | ISSUE)
  transfer_line_allocations  one row per lot per transfer line; override_id is
                             set when that line's allocation was overridden
  inventory_transactions     ISSUE rows with a lot_id; reference_id is the
                             issue_ref the ISSUE override row carries

PERMISSIONS: not checked here; the routers require report:dispatch_summary.
Scope (CLAUDE.md §1, same rule as transfer_discrepancies.list_discrepancies):
  WM / LM / SA_GT / RT   their node subtree; no node -> empty result
  RM                     its node subtree; no node -> the whole tenant
  TA / NM / AU / SA      the whole tenant
The subtree is matched against the override's warehouse_id, the allocation's
from_warehouse_id and the ledger row's warehouse_id.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.inventory import (
    ComplianceCounts,
    OverrideLogItem,
    OverrideLogOut,
    OverrideLotOut,
    OverrideProductOut,
    OverrideSummaryOut,
    OverrideWarehouseOut,
)
from services.transfer_discrepancies import _FACILITY_SCOPED_ROLES, _inside, _subtree

DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 366
MOVEMENTS = ("TRANSFER", "ISSUE")

_PRODUCT_JOIN = "JOIN products p ON p.id = {a}.product_id AND p.tenant_id = {a}.tenant_id "


def compliance_rate(decisions: int, overridden: int) -> Optional[float]:
    """(decisions - overridden) / decisions to 4 places; None when no decisions."""
    if decisions <= 0:
        return None
    return round((decisions - overridden) / decisions, 4)


def resolve_period(
    date_from: Optional[date], date_to: Optional[date], today: Optional[date] = None
) -> tuple[date, date]:
    """Default: the 30 calendar days ending today. 422 on from > to or > 366 days."""
    end = date_to or today or datetime.now(timezone.utc).date()
    start = date_from or (end - timedelta(days=DEFAULT_PERIOD_DAYS - 1))
    if start > end:
        raise HTTPException(status_code=422, detail={"code": "INVALID_DATE_RANGE"})
    if (end - start).days > MAX_PERIOD_DAYS:
        raise HTTPException(status_code=422, detail={"code": "DATE_RANGE_TOO_LARGE"})
    return start, end


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """created_at window [start 00:00 UTC, end + 1 day 00:00 UTC)."""
    return (
        datetime.combine(start, time.min, tzinfo=timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
    )


def _require_tenant(tenant_id: Optional[UUID | str]) -> str:
    # SA with no ?tenant_id= resolves to None (effective_tenant_id); a log
    # across every tenant is not offered.
    if tenant_id is None:
        raise HTTPException(status_code=422, detail={"code": "TENANT_ID_REQUIRED"})
    return str(tenant_id)


async def _scope(
    db: AsyncSession, user: Any, tenant_id: str, warehouse_id: Optional[UUID | str]
) -> tuple[bool, Optional[list[str]]]:
    """(empty, subtree). subtree is None for a tenant-wide caller."""
    role = getattr(user, "role", None)
    node_id = getattr(user, "warehouse_id", None)
    if role in _FACILITY_SCOPED_ROLES and not node_id:
        return True, None
    if node_id and (role in _FACILITY_SCOPED_ROLES or role == "RM"):
        subtree = await _subtree(db, tenant_id, node_id)
        if warehouse_id is not None and not _inside(subtree, [warehouse_id]):
            raise HTTPException(status_code=403, detail={"code": "WAREHOUSE_OUT_OF_SCOPE"})
        return False, sorted(subtree)
    return False, None


def _wh_filter(
    column: str,
    subtree: Optional[list[str]],
    warehouse_id: Optional[UUID | str],
    params: dict[str, Any],
) -> str:
    sql = ""
    if subtree is not None:
        sql += f" AND {column} = ANY(CAST(:subtree AS uuid[]))"
        params["subtree"] = subtree
    if warehouse_id is not None:
        sql += f" AND {column} = CAST(:wh AS uuid)"
        params["wh"] = str(warehouse_id).lower()
    return sql


# ── list ─────────────────────────────────────────────────────────────────────


def _stored_lots(raw: Any) -> list[dict[str, Any]]:
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def _lots(raw: Any, lot_numbers: dict[str, str]) -> list[OverrideLotOut]:
    """Stored JSON [{lot_id, lot_number, quantity}] with lot_number from stock_lots."""
    return [
        OverrideLotOut(
            lot_id=i["lot_id"],
            lot_number=lot_numbers.get(str(i["lot_id"]).lower(), i.get("lot_number")),
            quantity=Decimal(str(i["quantity"])),
        )
        for i in _stored_lots(raw)
    ]


async def list_overrides(
    db: AsyncSession,
    user: Any,
    tenant_id: Optional[UUID | str],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    warehouse_id: Optional[UUID | str] = None,
    product_id: Optional[UUID | str] = None,
    strategy: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> OverrideLogOut:
    """Override rows in the period, newest first, with lot numbers and names."""
    tid = _require_tenant(tenant_id)
    start, end = resolve_period(date_from, date_to)
    empty, subtree = await _scope(db, user, tid, warehouse_id)
    if empty:
        return OverrideLogOut(total=0, rows=[])

    ts_from, ts_to = _bounds(start, end)
    params: dict[str, Any] = {"tid": tid, "ts_from": ts_from, "ts_to": ts_to}
    filters = " AND o.created_at >= :ts_from AND o.created_at < :ts_to"
    filters += _wh_filter("o.warehouse_id", subtree, warehouse_id, params)
    if product_id is not None:
        filters += " AND o.product_id = CAST(:pid AS uuid)"
        params["pid"] = str(product_id)
    if strategy is not None:
        filters += " AND o.strategy = CAST(:strategy AS dispatch_strategy)"
        params["strategy"] = strategy

    total = (
        (
            await db.execute(
                text(
                    "SELECT count(*) AS n FROM lot_allocation_overrides o "
                    f"WHERE o.tenant_id = :tid{filters}"
                ),
                params,
            )
        )
        .fetchone()
        .n
    )

    rows = (
        await db.execute(
            text(
                "SELECT o.id, o.created_at, u.full_name AS overridden_by_name, "
                "       o.product_id, p.name AS product_name, p.sku AS product_sku, "
                "       o.warehouse_id, COALESCE(n.name, w.name) AS warehouse_name, "
                "       o.strategy::text AS strategy, o.movement_type, o.reference_id, "
                "       o.requested_qty, o.suggested, o.chosen, o.reason "
                "FROM lot_allocation_overrides o "
                "JOIN products p ON p.id = o.product_id AND p.tenant_id = o.tenant_id "
                "LEFT JOIN users u ON u.id = o.overridden_by "
                "LEFT JOIN organization_node n ON n.id = o.warehouse_id AND n.tenant_id = o.tenant_id "
                "LEFT JOIN warehouses w ON w.id = o.warehouse_id AND w.tenant_id = o.tenant_id "
                f"WHERE o.tenant_id = :tid{filters} "
                "ORDER BY o.created_at DESC, o.id "
                "LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
    ).fetchall()

    lot_ids = sorted(
        {
            str(i["lot_id"]).lower()
            for r in rows
            for raw in (r.suggested, r.chosen)
            for i in _stored_lots(raw)
        }
    )
    lot_numbers: dict[str, str] = {}
    if lot_ids:
        found = (
            await db.execute(
                text(
                    "SELECT id, lot_number FROM stock_lots "
                    "WHERE tenant_id = :tid AND id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"tid": tid, "ids": lot_ids},
            )
        ).fetchall()
        lot_numbers = {str(r.id).lower(): r.lot_number for r in found}

    return OverrideLogOut(
        total=total,
        rows=[
            OverrideLogItem(
                id=r.id,
                created_at=r.created_at,
                overridden_by=r.overridden_by_name,
                product=OverrideProductOut(id=r.product_id, name=r.product_name, sku=r.product_sku),
                warehouse=OverrideWarehouseOut(id=r.warehouse_id, name=r.warehouse_name),
                strategy=r.strategy,
                movement_type=r.movement_type,
                reference_id=r.reference_id,
                requested_qty=r.requested_qty,
                suggested=_lots(r.suggested, lot_numbers),
                chosen=_lots(r.chosen, lot_numbers),
                reason=r.reason,
            )
            for r in rows
        ],
    )


# ── summary ──────────────────────────────────────────────────────────────────


async def _period_counts(
    db: AsyncSession,
    tid: str,
    start: date,
    end: date,
    subtree: Optional[list[str]],
    warehouse_id: Optional[UUID | str],
    fefo_only: bool,
) -> dict[str, tuple[int, int]]:
    """{movement: (decisions, overridden)} — distinct transfer lines / issue refs."""
    ts_from, ts_to = _bounds(start, end)
    fefo = " AND p.dispatch_strategy = 'FEFO'" if fefo_only else ""

    def join(alias: str) -> str:
        return _PRODUCT_JOIN.format(a=alias) if fefo_only else ""

    # TRANSFER: one row per lot per line; a line is overridden if any row has override_id.
    params: dict[str, Any] = {"tid": tid, "ts_from": ts_from, "ts_to": ts_to}
    t_filters = _wh_filter("a.from_warehouse_id", subtree, warehouse_id, params)
    t = (
        await db.execute(
            text(
                "SELECT count(DISTINCT a.transfer_line_id) AS decisions, "
                "       count(DISTINCT a.transfer_line_id) "
                "         FILTER (WHERE a.override_id IS NOT NULL) AS overridden "
                "FROM transfer_line_allocations a "
                f"{join('a')}"
                "WHERE a.tenant_id = :tid AND a.created_at >= :ts_from AND a.created_at < :ts_to"
                f"{t_filters}{fefo}"
            ),
            params,
        )
    ).fetchone()

    # ISSUE: lot-carrying ledger rows, one decision per issue_ref. The overridden
    # count comes from the SAME rows (those with a matching override row), so it
    # can never exceed decisions at a period edge.
    params = {"tid": tid, "df": start, "dt": end}
    i_filters = _wh_filter("t.warehouse_id", subtree, warehouse_id, params)
    issued = (
        await db.execute(
            text(
                "SELECT count(DISTINCT t.reference_id) AS decisions, "
                "       count(DISTINCT t.reference_id) FILTER (WHERE EXISTS ("
                "         SELECT 1 FROM lot_allocation_overrides o "
                "         WHERE o.tenant_id = t.tenant_id AND o.movement_type = 'ISSUE' "
                "           AND o.reference_id = t.reference_id)) AS overridden "
                "FROM inventory_transactions t "
                f"{join('t')}"
                "WHERE t.tenant_id = :tid AND t.type = 'ISSUE' AND t.lot_id IS NOT NULL "
                "  AND t.transaction_date >= :df AND t.transaction_date <= :dt"
                f"{i_filters}{fefo}"
            ),
            params,
        )
    ).fetchone()

    return {
        "TRANSFER": (int(t.decisions), int(t.overridden)),
        "ISSUE": (int(issued.decisions), int(issued.overridden)),
    }


def _counts(decisions: int, overridden: int) -> ComplianceCounts:
    return ComplianceCounts(
        decisions=decisions,
        overridden=overridden,
        compliance_rate=compliance_rate(decisions, overridden),
    )


def _total(by_movement: dict[str, tuple[int, int]]) -> ComplianceCounts:
    return _counts(
        sum(d for d, _ in by_movement.values()),
        sum(o for _, o in by_movement.values()),
    )


async def override_summary(
    db: AsyncSession,
    user: Any,
    tenant_id: Optional[UUID | str],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    warehouse_id: Optional[UUID | str] = None,
) -> OverrideSummaryOut:
    """How often the suggested lots were followed in the period.

    decisions   distinct transfer lines with allocations + distinct issue refs
                with lot-carrying ISSUE ledger rows
    overridden  distinct transfer lines with override_id set + distinct issue
                refs, among those same ledger rows, with an ISSUE override row

    `fefo` limits the same counts to products whose products.dispatch_strategy
    is 'FEFO' today. Non-overridden decisions do not store the strategy that
    was used, so the product's current strategy is the proxy.
    """
    tid = _require_tenant(tenant_id)
    start, end = resolve_period(date_from, date_to)
    empty, subtree = await _scope(db, user, tid, warehouse_id)

    if empty:
        overall_by = fefo_by = {m: (0, 0) for m in MOVEMENTS}
    else:
        overall_by = await _period_counts(db, tid, start, end, subtree, warehouse_id, False)
        fefo_by = await _period_counts(db, tid, start, end, subtree, warehouse_id, True)

    return OverrideSummaryOut(
        date_from=start,
        date_to=end,
        overall=_total(overall_by),
        fefo=_total(fefo_by),
        by_movement={m: _counts(*overall_by[m]) for m in MOVEMENTS},
    )
