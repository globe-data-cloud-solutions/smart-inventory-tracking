"""Unit tests for transfer discrepancy resolution (FEFO D2):
services/transfer_discrepancies.resolve_discrepancy / list_discrepancies and
the POST .../resolve and GET /discrepancies endpoints.

No real database: _World answers each statement by its SQL text and keeps the
discrepancy rows, lots, lot balances, ledger calls, UPDATEs and audit INSERTs
in memory (the same approach as test_transfer_receipt.py). The fake
record_transaction applies record_transaction's lot floor check, so an
insufficient source lot raises the same 422 INSUFFICIENT_LOT_STOCK.

Transfer T1 moves stock from WH_A (source) to WH_B (destination).
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

TENANT_ID = "10000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-0000-0000-0000-000000000001"
WH_A = "20000000-0000-0000-0000-00000000000a"  # source of T1
WH_B = "20000000-0000-0000-0000-00000000000b"  # destination of T1
WH_C = "20000000-0000-0000-0000-00000000000c"  # unrelated warehouse
REGION = "40000000-0000-0000-0000-000000000001"  # RM node over WH_A and WH_B
REGION_B = "40000000-0000-0000-0000-000000000002"  # RM node over WH_B only
REGION_C = "40000000-0000-0000-0000-000000000003"  # RM node over WH_C only
SITE = "50000000-0000-0000-0000-000000000001"  # facility node, WH_C is its child
PRODUCT = "aaaaaaaa-0000-0000-0000-000000000001"  # batch
PRODUCT_2 = "aaaaaaaa-0000-0000-0000-000000000002"  # non-batch
T1 = "cccccccc-0000-0000-0000-000000000001"
T2 = "cccccccc-0000-0000-0000-000000000002"  # WH_C -> WH_A
T3 = "cccccccc-0000-0000-0000-000000000003"  # WH_B -> WH_C
T_OTHER = "cccccccc-0000-0000-0000-0000000000ff"  # another tenant
LINE = "11111111-0000-0000-0000-000000000001"
USER_ID = "30000000-0000-0000-0000-000000000001"

# Lots are compared in lot_id order: LOT_0 < LOT_A < LOT_C < LOT_D.
LOT_0 = "00000001-0000-0000-0000-000000000000"  # product, sorts BEFORE the sent lot
LOT_A = "0000000a-0000-0000-0000-000000000000"  # product, the lot that was sent
LOT_C = "0000000c-0000-0000-0000-000000000000"  # product, expired, sorts AFTER LOT_A
LOT_D = "0000000d-0000-0000-0000-000000000000"  # product, only 1 at the source
LOT_Z = "0000000f-0000-0000-0000-000000000000"  # PRODUCT_2 — another product

D_SHORT = "dddddddd-0000-0000-0000-000000000001"  # SHORT, batch, 2 missing
D_SHORT_NB = "dddddddd-0000-0000-0000-000000000002"  # SHORT, non-batch, 5 missing
D_DAMAGED = "dddddddd-0000-0000-0000-000000000003"  # DAMAGED, batch, 4 missing
D_WRONG = "dddddddd-0000-0000-0000-000000000004"  # WRONG_LOT, batch, 3 missing
D_WRONG_NB = "dddddddd-0000-0000-0000-000000000005"  # WRONG_LOT, non-batch, 6 missing
D_RESOLVED = "dddddddd-0000-0000-0000-000000000006"  # already RESOLVED
D_T2 = "dddddddd-0000-0000-0000-000000000007"  # on T2 (WH_C -> WH_A)
D_T3 = "dddddddd-0000-0000-0000-000000000008"  # on T3 (WH_B -> WH_C)
D_OTHER = "dddddddd-0000-0000-0000-0000000000ff"  # another tenant's row

KEY = f"transfer:{T1}:discrepancy"


def _user(role: str, warehouse_id: Optional[str] = None, tenant_id: str = TENANT_ID) -> Any:
    return SimpleNamespace(
        user_id=USER_ID,
        tenant_id=tenant_id,
        role=role,
        warehouse_id=warehouse_id,
        region_id=None,
    )


TA = _user("TA")
NM = _user("NM")
RM = _user("RM", REGION)  # source and destination in scope
RM_DEST_ONLY = _user("RM", REGION_B)  # destination in scope, source outside
RM_OUT = _user("RM", REGION_C)  # neither end in scope
RM_NO_NODE = _user("RM", None)

# Subtrees as get_descendant_node_ids returns them. REGION's comes back in
# upper case to prove the scope comparison lowercases both sides.
SUBTREES: dict[str, set[str]] = {
    REGION: {REGION.upper(), WH_A.upper(), WH_B.upper()},
    REGION_B: {REGION_B, WH_B},
    REGION_C: {REGION_C, WH_C},
    SITE: {SITE, WH_C.upper()},
}


class _World:
    """In-memory stand-in for the tables a resolution touches."""

    def __init__(self) -> None:
        now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        self.transfers = {
            T1: dict(tenant_id=TENANT_ID, from_wh=WH_A, to_wh=WH_B, type="PULL"),
            T2: dict(tenant_id=TENANT_ID, from_wh=WH_C, to_wh=WH_A, type="PUSH"),
            T3: dict(tenant_id=TENANT_ID, from_wh=WH_B, to_wh=WH_C, type="SISTER"),
            T_OTHER: dict(tenant_id=OTHER_TENANT, from_wh=WH_A, to_wh=WH_B, type="PULL"),
        }
        self.lots = {
            LOT_0: dict(
                tenant_id=TENANT_ID, product_id=PRODUCT, lot_number="LOT-0", expiry_date=None
            ),
            LOT_A: dict(
                tenant_id=TENANT_ID,
                product_id=PRODUCT,
                lot_number="LOT-A",
                expiry_date=date(2027, 1, 31),
            ),
            LOT_C: dict(
                tenant_id=TENANT_ID,
                product_id=PRODUCT,
                lot_number="LOT-C",
                expiry_date=date.today() - timedelta(days=30),
            ),  # expired
            LOT_D: dict(
                tenant_id=TENANT_ID, product_id=PRODUCT, lot_number="LOT-D", expiry_date=None
            ),
            LOT_Z: dict(
                tenant_id=TENANT_ID, product_id=PRODUCT_2, lot_number="LOT-Z", expiry_date=None
            ),
        }
        self.lot_balances: dict[tuple[str, str], Decimal] = {
            (LOT_0, WH_A): Decimal("10"),
            (LOT_A, WH_A): Decimal("50"),
            (LOT_C, WH_A): Decimal("10"),
            (LOT_D, WH_A): Decimal("1"),
        }

        def row(
            did: str,
            xfer: str,
            product: str,
            lot: Optional[str],
            missing: str,
            reason: str,
            minutes: int,
            status: str = "OPEN",
            tenant: str = TENANT_ID,
        ) -> dict:
            return dict(
                id=did,
                tenant_id=tenant,
                transfer_order_id=xfer,
                transfer_line_id=LINE,
                product_id=product,
                lot_id=lot,
                sent_quantity=Decimal("10"),
                received_quantity=Decimal("10") - Decimal(missing),
                missing_quantity=Decimal(missing),
                reason=reason,
                note=None,
                status=status,
                created_at=now + timedelta(minutes=minutes),
                resolution="WRITTEN_OFF" if status == "RESOLVED" else None,
                resolved_lot_id=None,
                resolution_note="gone" if status == "RESOLVED" else None,
                resolved_by=USER_ID if status == "RESOLVED" else None,
                resolved_at=now if status == "RESOLVED" else None,
            )

        self.discrepancies = {
            D_SHORT: row(D_SHORT, T1, PRODUCT, LOT_A, "2", "SHORT", 1),
            D_SHORT_NB: row(D_SHORT_NB, T1, PRODUCT_2, None, "5", "SHORT", 2),
            D_DAMAGED: row(D_DAMAGED, T1, PRODUCT, LOT_A, "4", "DAMAGED", 3),
            D_WRONG: row(D_WRONG, T1, PRODUCT, LOT_A, "3", "WRONG_LOT", 4),
            D_WRONG_NB: row(D_WRONG_NB, T1, PRODUCT_2, None, "6", "WRONG_LOT", 5),
            D_RESOLVED: row(D_RESOLVED, T1, PRODUCT, LOT_A, "1", "SHORT", 6, status="RESOLVED"),
            D_T2: row(D_T2, T2, PRODUCT_2, None, "1", "SHORT", 7),
            D_T3: row(D_T3, T3, PRODUCT_2, None, "1", "DAMAGED", 8),
            D_OTHER: row(D_OTHER, T_OTHER, PRODUCT_2, None, "1", "SHORT", 9, tenant=OTHER_TENANT),
        }
        self.ledger: list[dict] = []  # record_transaction kwargs, in call order
        self.updates: list[dict] = []  # UPDATE transfer_discrepancies params
        self.audits: list[dict] = []  # INSERT INTO audit_logs params
        self.sql: list[tuple[str, dict]] = []
        self.update_rowcount: Optional[int] = None  # force a lost race

    # ── session ──
    def _out_row(self, d: dict) -> SimpleNamespace:
        t = self.transfers[d["transfer_order_id"]]
        lot = self.lots.get(d["lot_id"]) if d["lot_id"] else None
        rlot = self.lots.get(d["resolved_lot_id"]) if d["resolved_lot_id"] else None
        return SimpleNamespace(
            **{k: v for k, v in d.items() if k != "tenant_id"},
            lot_number=lot["lot_number"] if lot else None,
            resolved_lot_number=rlot["lot_number"] if rlot else None,
            transfer_type=t["type"],
            from_warehouse_id=t["from_wh"],
            to_warehouse_id=t["to_wh"],
        )

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> MagicMock:
        sql, params = str(stmt), dict(params or {})
        self.sql.append((sql, params))
        result = MagicMock()
        result.fetchone.return_value = None
        result.fetchall.return_value = []

        if "FOR UPDATE OF d" in sql:
            d = self.discrepancies.get(params["did"])
            if (
                d
                and d["tenant_id"] == params["tid"]
                and d["transfer_order_id"] == params["xfer_id"]
            ):
                t = self.transfers[d["transfer_order_id"]]
                result.fetchone.return_value = SimpleNamespace(
                    id=d["id"],
                    product_id=UUID(d["product_id"]),
                    lot_id=UUID(d["lot_id"]) if d["lot_id"] else None,
                    missing_quantity=d["missing_quantity"],
                    reason=d["reason"],
                    status=d["status"],
                    from_warehouse_id=UUID(t["from_wh"]),
                    to_warehouse_id=UUID(t["to_wh"]),
                )
        elif sql.startswith("SELECT id, product_id, lot_number, expiry_date FROM stock_lots"):
            lot = self.lots.get(params["lid"])
            if lot and lot["tenant_id"] == params["tid"]:
                result.fetchone.return_value = SimpleNamespace(
                    id=UUID(params["lid"]),
                    product_id=UUID(lot["product_id"]),
                    lot_number=lot["lot_number"],
                    expiry_date=lot["expiry_date"],
                )
        elif sql.startswith("UPDATE transfer_discrepancies"):
            self.updates.append(params)
            d = self.discrepancies.get(params["did"])
            hit = bool(d and d["tenant_id"] == params["tid"] and d["status"] == "OPEN")
            if hit and self.update_rowcount is None:
                d.update(
                    status="RESOLVED",
                    resolution=params["resolution"],
                    resolved_lot_id=params["resolved_lot_id"],
                    resolution_note=params["note"],
                    resolved_by=params["uid"],
                    resolved_at=datetime.now(timezone.utc),
                )
            result.rowcount = self.update_rowcount if self.update_rowcount is not None else int(hit)
        elif "INSERT INTO audit_logs" in sql:
            self.audits.append(params)
        elif "FROM transfer_discrepancies d" in sql and "LIMIT 200" in sql:
            rows = [d for d in self.discrepancies.values() if d["tenant_id"] == params["tid"]]
            if "status" in params:
                rows = [d for d in rows if d["status"] == params["status"]]

            def ends(d: dict) -> tuple[str, str]:
                t = self.transfers[d["transfer_order_id"]]
                return t["from_wh"], t["to_wh"]

            if "subtree" in params:  # uuid = ANY(:subtree)
                rows = [d for d in rows if any(e in params["subtree"] for e in ends(d))]
            if "wh" in params:
                rows = [d for d in rows if params["wh"] in ends(d)]
            rows.sort(key=lambda d: d["created_at"], reverse=True)
            result.fetchall.return_value = [self._out_row(d) for d in rows]
        elif "FROM transfer_discrepancies d" in sql and "WHERE d.id = :did" in sql:
            d = self.discrepancies.get(params["did"])
            if d and d["tenant_id"] == params["tid"]:
                result.fetchone.return_value = self._out_row(d)
        return result

    def db(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=self.execute)
        return session

    # ── ledger ──
    async def record_transaction(self, db: Any, **kw: Any) -> str:
        """Applies record_transaction's lot floor check (Step 3b), then records."""
        lot_id, wh, qty = kw.get("lot_id"), kw["warehouse_id"], kw["quantity"]
        if lot_id is not None:
            before = self.lot_balances.get((lot_id, wh), Decimal("0"))
            if before + qty < 0:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INSUFFICIENT_LOT_STOCK",
                        "lot_id": lot_id,
                        "warehouse_id": wh,
                        "available": float(before),
                        "requested": float(abs(qty)),
                    },
                )
            self.lot_balances[(lot_id, wh)] = before + qty
        self.ledger.append(kw)
        return f"tx-{len(self.ledger)}"

    def rows(self) -> list[tuple]:
        return [
            (
                c["transaction_type"],
                c["warehouse_id"],
                c["quantity"],
                c["lot_id"],
                c["idempotency_key"],
            )
            for c in self.ledger
        ]


async def _descendants(db: Any, tenant_id: str, node_id: str) -> set[str]:
    assert tenant_id == TENANT_ID
    return SUBTREES.get(node_id, {node_id})


async def _resolve(
    world: _World, user: Any, discrepancy_id: str, transfer_id: str = T1, **body: Any
) -> Any:
    from schemas.inventory import ResolveDiscrepancyRequest
    from services.transfer_discrepancies import resolve_discrepancy

    with (
        patch("services.transfer_discrepancies.record_transaction", new=world.record_transaction),
        patch("services.transfer_discrepancies.get_descendant_node_ids", new=_descendants),
    ):
        return await resolve_discrepancy(
            world.db(),
            user,
            UUID(transfer_id),
            UUID(discrepancy_id),
            ResolveDiscrepancyRequest(**body),
        )


async def _rejected(world: _World, user: Any, discrepancy_id: str, **body: Any) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        await _resolve(world, user, discrepancy_id, **body)
    return exc_info.value


def _nothing_written(world: _World, discrepancy_id: str) -> bool:
    return (
        world.ledger == []
        and world.updates == []
        and world.audits == []
        and world.discrepancies[discrepancy_id]["status"] == "OPEN"
    )


# ── outcomes by reason ───────────────────────────────────────────────────────

ALLOWED = [
    (D_SHORT, "WRITTEN_OFF"),
    (D_SHORT, "RETURNED"),
    (D_SHORT, "ARRIVED_LATE"),
    (D_SHORT_NB, "WRITTEN_OFF"),
    (D_SHORT_NB, "RETURNED"),
    (D_SHORT_NB, "ARRIVED_LATE"),
    (D_DAMAGED, "WRITTEN_OFF"),
    (D_WRONG, "WRITTEN_OFF"),
    (D_WRONG, "RETURNED"),
    (D_WRONG, "RECEIVED_AS_LOT"),
    (D_WRONG_NB, "WRITTEN_OFF"),
    (D_WRONG_NB, "RETURNED"),
]
NOT_ALLOWED = [
    (D_SHORT, "RECEIVED_AS_LOT", "SHORT", ["WRITTEN_OFF", "RETURNED", "ARRIVED_LATE"]),
    (D_SHORT_NB, "RECEIVED_AS_LOT", "SHORT", ["WRITTEN_OFF", "RETURNED", "ARRIVED_LATE"]),
    (D_DAMAGED, "RETURNED", "DAMAGED", ["WRITTEN_OFF"]),
    (D_DAMAGED, "ARRIVED_LATE", "DAMAGED", ["WRITTEN_OFF"]),
    (D_DAMAGED, "RECEIVED_AS_LOT", "DAMAGED", ["WRITTEN_OFF"]),
    (D_WRONG, "ARRIVED_LATE", "WRONG_LOT", ["WRITTEN_OFF", "RETURNED", "RECEIVED_AS_LOT"]),
    (D_WRONG_NB, "ARRIVED_LATE", "WRONG_LOT", ["WRITTEN_OFF", "RETURNED"]),
    # RECEIVED_AS_LOT needs a batch line
    (D_WRONG_NB, "RECEIVED_AS_LOT", "WRONG_LOT", ["WRITTEN_OFF", "RETURNED"]),
]


def _body_for(resolution: str) -> dict:
    body: dict[str, Any] = {"resolution": resolution}
    if resolution == "WRITTEN_OFF":
        body["note"] = "lost in transit"
    if resolution == "RECEIVED_AS_LOT":
        body["lot_id"] = LOT_C
    return body


@pytest.mark.unit
class TestResolutionByReason:
    @pytest.mark.parametrize("discrepancy_id, resolution", ALLOWED)
    async def test_allowed_outcome_resolves(self, discrepancy_id: str, resolution: str) -> None:
        world = _World()
        out = await _resolve(world, TA, discrepancy_id, **_body_for(resolution))

        assert out.status == "RESOLVED"
        assert out.resolution == resolution
        assert str(out.resolved_by) == USER_ID
        assert out.resolved_at is not None
        assert len(world.updates) == 1 and len(world.audits) == 1

    @pytest.mark.parametrize("discrepancy_id, resolution, reason, allowed", NOT_ALLOWED)
    async def test_disallowed_outcome_is_422(
        self, discrepancy_id: str, resolution: str, reason: str, allowed: list[str]
    ) -> None:
        world = _World()
        exc = await _rejected(world, TA, discrepancy_id, **_body_for(resolution))

        assert exc.status_code == 422
        assert exc.detail == {
            "code": "RESOLUTION_NOT_ALLOWED",
            "reason": reason,
            "allowed": allowed,
        }
        assert _nothing_written(world, discrepancy_id)


# ── ledger rows ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestResolutionLedger:
    async def test_written_off_posts_no_ledger_rows(self) -> None:
        world = _World()
        out = await _resolve(world, TA, D_SHORT, resolution="WRITTEN_OFF", note="  fell off truck ")

        assert world.ledger == []
        assert out.resolution_note == "fell off truck"
        assert out.resolved_lot_id is None

    async def test_returned_batch_reverses_at_source_on_the_sent_lot(self) -> None:
        world = _World()
        await _resolve(world, TA, D_SHORT, resolution="RETURNED")

        assert world.rows() == [
            ("TRANSFER_REVERSAL", WH_A, Decimal("2"), LOT_A, f"{KEY}:{D_SHORT}:return"),
        ]
        call = world.ledger[0]
        assert call["product_id"] == PRODUCT
        assert call["reference_type"] == "TRANSFER" and call["reference_id"] == T1
        assert call["lot_number"] == "LOT-A" and call["expiry_date"] == date(2027, 1, 31)
        assert call["performed_by"] == USER_ID and call["tenant_id"] == TENANT_ID

    async def test_arrived_late_batch_credits_destination_on_the_sent_lot(self) -> None:
        world = _World()
        await _resolve(world, TA, D_SHORT, resolution="ARRIVED_LATE")

        assert world.rows() == [
            ("TRANSFER_IN", WH_B, Decimal("2"), LOT_A, f"{KEY}:{D_SHORT}:late"),
        ]
        assert world.ledger[0]["lot_number"] == "LOT-A"

    async def test_returned_non_batch_has_no_lot(self) -> None:
        world = _World()
        await _resolve(world, TA, D_SHORT_NB, resolution="RETURNED")

        assert world.rows() == [
            ("TRANSFER_REVERSAL", WH_A, Decimal("5"), None, f"{KEY}:{D_SHORT_NB}:return"),
        ]
        assert world.ledger[0]["product_id"] == PRODUCT_2
        assert world.ledger[0]["lot_number"] is None and world.ledger[0]["expiry_date"] is None

    async def test_arrived_late_non_batch_has_no_lot(self) -> None:
        world = _World()
        await _resolve(world, TA, D_SHORT_NB, resolution="ARRIVED_LATE")

        assert world.rows() == [
            ("TRANSFER_IN", WH_B, Decimal("5"), None, f"{KEY}:{D_SHORT_NB}:late"),
        ]

    async def test_received_as_lot_swaps_lots_reversal_first_when_sent_lot_sorts_first(
        self,
    ) -> None:
        """Arrived LOT_C (> LOT_A): reversal on LOT_A, out on LOT_C, in on LOT_C.
        LOT_C is expired — accepted, this records what happened."""
        world = _World()
        out = await _resolve(world, TA, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_C)

        assert world.rows() == [
            ("TRANSFER_REVERSAL", WH_A, Decimal("3"), LOT_A, f"{KEY}:{D_WRONG}:swap:return"),
            ("TRANSFER_OUT", WH_A, Decimal("-3"), LOT_C, f"{KEY}:{D_WRONG}:swap:out"),
            ("TRANSFER_IN", WH_B, Decimal("3"), LOT_C, f"{KEY}:{D_WRONG}:swap:in"),
        ]
        assert [c["lot_number"] for c in world.ledger] == ["LOT-A", "LOT-C", "LOT-C"]
        assert world.lot_balances[(LOT_A, WH_A)] == Decimal("53")
        assert world.lot_balances[(LOT_C, WH_A)] == Decimal("7")
        assert world.lot_balances[(LOT_C, WH_B)] == Decimal("3")
        assert str(out.resolved_lot_id) == LOT_C
        assert out.resolved_lot_number == "LOT-C"

    async def test_received_as_lot_source_rows_follow_lot_id_order(self) -> None:
        """Arrived LOT_0 (< LOT_A): the source rows are posted in lot_id order,
        the engine's lock order — TRANSFER_OUT on LOT_0 before the reversal."""
        world = _World()
        await _resolve(world, TA, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_0)

        assert world.rows() == [
            ("TRANSFER_OUT", WH_A, Decimal("-3"), LOT_0, f"{KEY}:{D_WRONG}:swap:out"),
            ("TRANSFER_REVERSAL", WH_A, Decimal("3"), LOT_A, f"{KEY}:{D_WRONG}:swap:return"),
            ("TRANSFER_IN", WH_B, Decimal("3"), LOT_0, f"{KEY}:{D_WRONG}:swap:in"),
        ]

    async def test_no_new_transaction_types(self) -> None:
        world = _World()
        await _resolve(world, TA, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_C)
        await _resolve(world, TA, D_SHORT, resolution="RETURNED")
        await _resolve(world, TA, D_SHORT_NB, resolution="ARRIVED_LATE")

        assert {c["transaction_type"] for c in world.ledger} == {
            "TRANSFER_REVERSAL",
            "TRANSFER_OUT",
            "TRANSFER_IN",
        }


# ── RECEIVED_AS_LOT lot checks ───────────────────────────────────────────────


@pytest.mark.unit
class TestReceivedAsLot:
    @pytest.mark.parametrize(
        "case, lot_id",
        [
            ("missing lot_id", None),
            ("same lot as sent", LOT_A),
            ("another product's lot", LOT_Z),
            ("unknown lot", "0000000e-0000-0000-0000-000000000000"),
        ],
    )
    async def test_bad_lot_is_422(self, case: str, lot_id: Optional[str]) -> None:
        world = _World()
        body: dict[str, Any] = {"resolution": "RECEIVED_AS_LOT"}
        if lot_id is not None:
            body["lot_id"] = lot_id
        exc = await _rejected(world, TA, D_WRONG, **body)

        assert exc.status_code == 422, case
        assert exc.detail == {"code": "RESOLUTION_LOT_INVALID", "lot_id": lot_id}, case
        assert _nothing_written(world, D_WRONG), case

    async def test_another_tenants_lot_is_422(self) -> None:
        world = _World()
        world.lots[LOT_C]["tenant_id"] = OTHER_TENANT
        exc = await _rejected(world, TA, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_C)

        assert exc.detail["code"] == "RESOLUTION_LOT_INVALID"
        assert _nothing_written(world, D_WRONG)

    async def test_non_batch_row_is_not_allowed(self) -> None:
        world = _World()
        exc = await _rejected(world, TA, D_WRONG_NB, resolution="RECEIVED_AS_LOT", lot_id=LOT_C)

        assert exc.status_code == 422
        assert exc.detail["code"] == "RESOLUTION_NOT_ALLOWED"
        assert _nothing_written(world, D_WRONG_NB)

    @pytest.mark.parametrize("resolution", ["WRITTEN_OFF", "RETURNED"])
    async def test_lot_id_on_another_outcome_is_422(self, resolution: str) -> None:
        world = _World()
        exc = await _rejected(world, TA, D_WRONG, **{**_body_for(resolution), "lot_id": LOT_C})

        assert exc.status_code == 422
        assert exc.detail == {"code": "RESOLUTION_LOT_INVALID", "lot_id": LOT_C}
        assert _nothing_written(world, D_WRONG)

    async def test_insufficient_source_lot_is_422_and_resolution_is_not_recorded(self) -> None:
        """LOT_D has 1 at the source, 3 are needed: record_transaction's floor
        check raises 422 before the UPDATE / audit; the router's session rolls
        back the reversal posted before it."""
        world = _World()
        exc = await _rejected(world, TA, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_D)

        assert exc.status_code == 422
        assert exc.detail["code"] == "INSUFFICIENT_LOT_STOCK"
        assert exc.detail["lot_id"] == LOT_D
        assert world.updates == [] and world.audits == []
        assert world.discrepancies[D_WRONG]["status"] == "OPEN"
        assert "TRANSFER_IN" not in {c["transaction_type"] for c in world.ledger}


# ── validation, idempotence ──────────────────────────────────────────────────


@pytest.mark.unit
class TestResolutionRules:
    @pytest.mark.parametrize("note", [None, "", "   "])
    async def test_written_off_without_note_is_422(self, note: Optional[str]) -> None:
        world = _World()
        exc = await _rejected(world, TA, D_SHORT, resolution="WRITTEN_OFF", note=note)

        assert exc.status_code == 422
        assert exc.detail == {"code": "RESOLUTION_NOTE_REQUIRED"}
        assert _nothing_written(world, D_SHORT)

    async def test_second_resolve_is_409(self) -> None:
        world = _World()
        await _resolve(world, TA, D_SHORT, resolution="RETURNED")
        exc = await _rejected(world, TA, D_SHORT, resolution="RETURNED")

        assert exc.status_code == 409
        assert exc.detail == {"code": "DISCREPANCY_ALREADY_RESOLVED"}
        assert len(world.ledger) == 1 and len(world.updates) == 1 and len(world.audits) == 1

    async def test_already_resolved_row_is_409(self) -> None:
        world = _World()
        exc = await _rejected(world, TA, D_RESOLVED, resolution="WRITTEN_OFF", note="x")

        assert exc.status_code == 409
        assert world.ledger == [] and world.updates == []

    async def test_update_matching_no_row_is_409_and_not_audited(self) -> None:
        """A concurrent resolve won between the SELECT and the UPDATE."""
        world = _World()
        world.update_rowcount = 0
        exc = await _rejected(world, TA, D_SHORT, resolution="WRITTEN_OFF", note="x")

        assert exc.status_code == 409
        assert exc.detail == {"code": "DISCREPANCY_ALREADY_RESOLVED"}
        assert world.audits == []

    @pytest.mark.parametrize(
        "discrepancy_id, transfer_id",
        [
            ("dddddddd-0000-0000-0000-0000000000ee", T1),  # no such row
            (D_SHORT, T2),  # row of another transfer
            (D_OTHER, T_OTHER),  # another tenant's row
        ],
    )
    async def test_not_found_is_404(self, discrepancy_id: str, transfer_id: str) -> None:
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _resolve(
                world,
                TA,
                discrepancy_id,
                transfer_id=transfer_id,
                resolution="WRITTEN_OFF",
                note="x",
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {"code": "DISCREPANCY_NOT_FOUND"}
        assert world.updates == [] and world.ledger == []

    async def test_row_is_locked_for_update_with_tenant_and_transfer(self) -> None:
        world = _World()
        await _resolve(world, TA, D_SHORT, resolution="RETURNED")

        sql, params = world.sql[0]
        assert "FOR UPDATE OF d" in sql
        assert params == {"did": D_SHORT, "tid": TENANT_ID, "xfer_id": T1}

    async def test_update_is_conditional_on_open(self) -> None:
        world = _World()
        await _resolve(world, TA, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_C)

        update_sql = next(s for s, _ in world.sql if s.startswith("UPDATE transfer_discrepancies"))
        assert "status = 'OPEN'" in update_sql.split("WHERE")[1]
        assert world.updates == [
            {
                "resolution": "RECEIVED_AS_LOT",
                "resolved_lot_id": LOT_C,
                "note": None,
                "uid": USER_ID,
                "did": D_WRONG,
                "tid": TENANT_ID,
            }
        ]

    async def test_audit_row_written_after_the_update_in_the_same_session(self) -> None:
        world = _World()
        await _resolve(world, RM, D_WRONG, resolution="RECEIVED_AS_LOT", lot_id=LOT_C)

        kinds = [
            "update"
            if s.startswith("UPDATE transfer_discrepancies")
            else "audit"
            if "INSERT INTO audit_logs" in s
            else None
            for s, _ in world.sql
        ]
        assert kinds.index("update") < kinds.index("audit")
        audit = world.audits[0]
        assert audit["tid"] == TENANT_ID and audit["uid"] == USER_ID and audit["role"] == "RM"
        assert audit["rid"] == D_WRONG
        audit_sql = next(s for s, _ in world.sql if "INSERT INTO audit_logs" in s)
        assert "'transfer:resolve_discrepancy'" in audit_sql and "'GRANTED'" in audit_sql
        assert json.loads(audit["ctx"]) == {
            "discrepancy_id": D_WRONG,
            "transfer_id": T1,
            "reason": "WRONG_LOT",
            "resolution": "RECEIVED_AS_LOT",
            "quantity": "3",
            "product_id": PRODUCT,
            "lot_id": LOT_A,
            "resolved_lot_id": LOT_C,
            "from_warehouse_id": WH_A,
            "to_warehouse_id": WH_B,
            "note": None,
        }


# ── scope ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestResolutionScope:
    @pytest.mark.parametrize("user", [TA, NM, _user("SA")], ids=["TA", "NM", "SA"])
    async def test_tenant_wide_roles_resolve_without_a_node(self, user: Any) -> None:
        world = _World()
        out = await _resolve(world, user, D_SHORT, resolution="RETURNED")
        assert out.status == "RESOLVED"

    @pytest.mark.parametrize(
        "resolution, discrepancy_id",
        [
            ("WRITTEN_OFF", D_SHORT),
            ("RETURNED", D_SHORT),
            ("ARRIVED_LATE", D_SHORT),
            ("RECEIVED_AS_LOT", D_WRONG),
        ],
    )
    async def test_rm_with_both_ends_in_subtree_resolves(
        self, resolution: str, discrepancy_id: str
    ) -> None:
        world = _World()
        out = await _resolve(world, RM, discrepancy_id, **_body_for(resolution))
        assert out.status == "RESOLVED"

    @pytest.mark.parametrize("resolution", ["WRITTEN_OFF", "ARRIVED_LATE"])
    async def test_rm_needs_only_the_destination_for_destination_outcomes(
        self, resolution: str
    ) -> None:
        world = _World()
        out = await _resolve(world, RM_DEST_ONLY, D_SHORT, **_body_for(resolution))
        assert out.status == "RESOLVED"

    @pytest.mark.parametrize(
        "user, resolution, discrepancy_id",
        [
            (RM_OUT, "WRITTEN_OFF", D_SHORT),  # destination outside
            (RM_OUT, "ARRIVED_LATE", D_SHORT),  # destination outside
            (RM_DEST_ONLY, "RETURNED", D_SHORT),  # source outside
            (RM_DEST_ONLY, "RECEIVED_AS_LOT", D_WRONG),  # source outside
            (RM_NO_NODE, "WRITTEN_OFF", D_SHORT),  # no node at all
        ],
    )
    async def test_rm_out_of_scope_is_403(
        self, user: Any, resolution: str, discrepancy_id: str
    ) -> None:
        world = _World()
        exc = await _rejected(world, user, discrepancy_id, **_body_for(resolution))

        assert exc.status_code == 403
        assert exc.detail == {"code": "DISCREPANCY_OUT_OF_SCOPE"}
        assert _nothing_written(world, discrepancy_id)

    @pytest.mark.parametrize(
        "discrepancy_id, body",
        [
            (D_SHORT, {"resolution": "WRITTEN_OFF"}),  # NOTE_REQUIRED
            (D_DAMAGED, {"resolution": "ARRIVED_LATE"}),  # NOT_ALLOWED
            (D_SHORT, {"resolution": "ARRIVED_LATE", "lot_id": LOT_C}),  # LOT_INVALID
        ],
        ids=["no-note", "not-allowed", "bad-lot"],
    )
    async def test_scope_is_checked_before_the_body(self, discrepancy_id: str, body: dict) -> None:
        """An out-of-scope RM gets 403, never the 422 an invalid body would earn."""
        world = _World()
        exc = await _rejected(world, RM_OUT, discrepancy_id, **body)

        assert exc.status_code == 403
        assert exc.detail == {"code": "DISCREPANCY_OUT_OF_SCOPE"}
        assert _nothing_written(world, discrepancy_id)

    @pytest.mark.parametrize("role", ["WM", "LM", "AU"])
    async def test_other_roles_are_refused_by_the_service_too(self, role: str) -> None:
        """Defence in depth behind the permission check."""
        world = _World()
        exc = await _rejected(world, _user(role, WH_B), D_SHORT, resolution="WRITTEN_OFF", note="x")

        assert exc.status_code == 403
        assert exc.detail == {"code": "DISCREPANCY_OUT_OF_SCOPE"}
        assert _nothing_written(world, D_SHORT)


# ── list ─────────────────────────────────────────────────────────────────────


async def _list(world: _World, user: Any, **kw: Any) -> list:
    from services.transfer_discrepancies import list_discrepancies

    with patch("services.transfer_discrepancies.get_descendant_node_ids", new=_descendants):
        return await list_discrepancies(world.db(), user, **kw)


ALL_ROWS = [D_T3, D_T2, D_RESOLVED, D_WRONG_NB, D_WRONG, D_DAMAGED, D_SHORT_NB, D_SHORT]
T1_ROWS = [D_RESOLVED, D_WRONG_NB, D_WRONG, D_DAMAGED, D_SHORT_NB, D_SHORT]


@pytest.mark.unit
class TestListDiscrepancies:
    async def test_tenant_rows_newest_first_with_transfer_fields(self) -> None:
        world = _World()
        rows = await _list(world, TA)

        assert [str(r.id) for r in rows] == [
            D_T3,
            D_T2,
            D_RESOLVED,
            D_WRONG_NB,
            D_WRONG,
            D_DAMAGED,
            D_SHORT_NB,
            D_SHORT,
        ]  # D_OTHER (another tenant) is not there
        first = rows[-1]
        assert (
            str(first.transfer_order_id),
            first.transfer_type,
            str(first.from_warehouse_id),
            str(first.to_warehouse_id),
        ) == (T1, "PULL", WH_A, WH_B)
        assert first.lot_number == "LOT-A"
        sql, params = world.sql[0]
        assert "ORDER BY d.created_at DESC" in sql and "LIMIT 200" in sql
        assert params == {"tid": TENANT_ID}

    async def test_status_filter(self) -> None:
        world = _World()
        resolved = await _list(world, TA, status="RESOLVED")
        open_rows = await _list(world, TA, status="OPEN")

        assert [str(r.id) for r in resolved] == [D_RESOLVED]
        assert resolved[0].resolution == "WRITTEN_OFF" and resolved[0].resolution_note == "gone"
        assert D_RESOLVED not in {str(r.id) for r in open_rows}
        assert len(open_rows) == 7

    async def test_warehouse_filter_matches_either_end(self) -> None:
        world = _World()
        rows = await _list(world, TA, warehouse_id=UUID(WH_C))

        # T2 has WH_C as its source, T3 as its destination
        assert [str(r.id) for r in rows] == [D_T3, D_T2]
        assert "(t.from_warehouse_id = :wh OR t.to_warehouse_id = :wh)" in world.sql[0][0]

    @pytest.mark.parametrize("role", ["WM", "LM", "SA_GT", "RT"])
    async def test_facility_role_sees_rows_with_either_end_in_its_subtree(self, role: str) -> None:
        """SITE's subtree is {SITE, WH_C}: T2 (WH_C ->) and T3 (-> WH_C) reach
        it through the child node; the T1 rows (WH_A -> WH_B) do not."""
        world = _World()
        rows = await _list(world, _user(role, SITE))

        assert [str(r.id) for r in rows] == [D_T3, D_T2]
        sql, params = world.sql[0]
        assert "t.from_warehouse_id = ANY(:subtree) OR t.to_warehouse_id = ANY(:subtree)" in sql
        assert params["subtree"] == sorted([SITE, WH_C])  # lowercased

    async def test_wm_on_a_leaf_sees_transfers_touching_it(self) -> None:
        world = _World()
        rows = await _list(world, _user("WM", WH_A))
        assert [str(r.id) for r in rows] == [D_T2, *T1_ROWS]

    @pytest.mark.parametrize("role", ["WM", "SA_GT", "RT"])
    async def test_facility_role_without_a_node_sees_nothing(self, role: str) -> None:
        world = _World()
        assert await _list(world, _user(role, None)) == []
        assert world.sql == []

    async def test_lm_without_a_node_is_tenant_wide(self) -> None:
        """LM Track B (business rule 25): no node means no subtree filter."""
        world = _World()
        rows = await _list(world, _user("LM", None))
        assert len(rows) > 0
        assert "subtree" not in world.sql[0][1]

    async def test_rm_with_a_node_sees_its_subtree(self) -> None:
        """REGION_B's subtree is {REGION_B, WH_B}: T1 and T3 touch WH_B, T2 does not."""
        world = _World()
        rows = await _list(world, RM_DEST_ONLY)

        assert [str(r.id) for r in rows] == [D_T3, *T1_ROWS]
        assert world.sql[0][1]["subtree"] == sorted([REGION_B, WH_B])

    async def test_subtree_is_lowercased(self) -> None:
        """REGION's subtree comes back upper case."""
        world = _World()
        rows = await _list(world, RM)

        assert [str(r.id) for r in rows] == ALL_ROWS
        assert world.sql[0][1]["subtree"] == sorted([REGION, WH_A, WH_B])

    @pytest.mark.parametrize(
        "user",
        [
            TA,
            NM,
            _user("SA"),
            _user("AU", WH_C),
        ],
        ids=["TA", "NM", "SA", "AU"],
    )
    async def test_tenant_wide_callers(self, user: Any) -> None:
        world = _World()
        rows = await _list(world, user)

        assert [str(r.id) for r in rows] == ALL_ROWS
        assert "subtree" not in world.sql[0][1]

    async def test_scope_and_warehouse_filter_combine(self) -> None:
        world = _World()
        rows = await _list(world, RM, warehouse_id=UUID(WH_A.upper()))

        assert [str(r.id) for r in rows] == [D_T2, *T1_ROWS]
        assert world.sql[0][1]["wh"] == WH_A

    @pytest.mark.parametrize(
        "user, warehouse_id",
        [
            (_user("WM", SITE), WH_B),
            (_user("LM", WH_A), WH_C),
            (RM_DEST_ONLY, WH_A),
        ],
        ids=["WM", "LM", "RM"],
    )
    async def test_warehouse_outside_the_subtree_is_403(self, user: Any, warehouse_id: str) -> None:
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _list(world, user, warehouse_id=UUID(warehouse_id))

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == {"code": "WAREHOUSE_OUT_OF_SCOPE"}
        assert world.sql == []

    async def test_tenant_wide_caller_may_name_any_warehouse(self) -> None:
        world = _World()
        rows = await _list(world, TA, warehouse_id=UUID(WH_C))
        assert [str(r.id) for r in rows] == [D_T3, D_T2]

    async def test_rm_without_node_sees_no_rows(self) -> None:
        # RB-2 G3: an RM is limited to its region; with no node there is no region.
        world = _World()
        assert await _list(world, RM_NO_NODE) == []

    async def test_another_tenant_sees_only_its_rows(self) -> None:
        world = _World()
        rows = await _list(world, _user("TA", tenant_id=OTHER_TENANT))
        assert [str(r.id) for r in rows] == [D_OTHER]


# ── permission + endpoints ───────────────────────────────────────────────────

RESOLVE_URL = f"/api/v1/inventory/transfers/{T1}/discrepancies/{D_SHORT}/resolve"
LIST_URL = "/api/v1/inventory/transfers/discrepancies"

# role_permissions rows for transfer:resolve_discrepancy after 088 (+ SA via seed).
_RESOLVE_GRANTS = {"TA", "NM", "RM", "SA"}


def _seed_matrix() -> dict[str, dict[str, str]]:
    path = Path(__file__).resolve().parents[6] / "scripts" / "seed_permissions.py"
    spec = importlib.util.spec_from_file_location("_seed_permissions_d2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.ROLE_PERMISSION_MATRIX


async def _grant(role: str, action_id: str) -> Any:
    """role_permissions lookup: the 088 grants for resolve, transfer:list as seeded."""
    from shared.permissions.store import RolePermissionGrant

    if action_id == "transfer:resolve_discrepancy" and role in _RESOLVE_GRANTS:
        return RolePermissionGrant(role=role, action_id=action_id, grant_type="FULL")
    if action_id == "transfer:list" and role in {"TA", "NM", "RM", "WM", "LM", "AU", "SA"}:
        return RolePermissionGrant(role=role, action_id=action_id, grant_type="FULL")
    return None


@pytest.fixture
def api(inv_app, inv_get_current_user):
    """Client factory: (user, stage) -> (client, audit_log mock, service mocks)."""
    from dependencies import get_db_session

    db = AsyncMock()

    async def _db_gen():
        yield db

    def make(user: Any, stage: str = "ACTIVE"):
        inv_app.dependency_overrides[inv_get_current_user] = lambda: user
        inv_app.dependency_overrides[get_db_session] = _db_gen
        audit = AsyncMock()
        resolve = AsyncMock(return_value=SimpleNamespace())
        listing = AsyncMock(return_value=[])
        patches = [
            patch("shared.permissions.middleware.get_role_permission", new=_grant),
            patch("shared.permissions.middleware.audit_log", new=audit),
            patch(
                "shared.billing.contract_stage.get_tenant_contract_stage",
                AsyncMock(
                    return_value={"stage": stage, "contract_end": None, "read_only_since": None}
                ),
            ),
            patch("services.transfer_discrepancies.resolve_discrepancy", new=resolve),
            patch("services.transfer_discrepancies.list_discrepancies", new=listing),
        ]
        return patches, audit, resolve, listing, db

    yield make
    inv_app.dependency_overrides.clear()


async def _call(inv_app, patches, method: str, url: str, **kw: Any):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        async with AsyncClient(transport=ASGITransport(app=inv_app), base_url="http://test") as ac:
            return await ac.request(method, url, **kw)


def _out(**kw: Any) -> Any:
    from schemas.inventory import TransferDiscrepancyOut

    return TransferDiscrepancyOut(
        id=UUID(D_SHORT),
        transfer_line_id=UUID(LINE),
        product_id=UUID(PRODUCT),
        lot_id=UUID(LOT_A),
        lot_number="LOT-A",
        sent_quantity=Decimal("10"),
        received_quantity=Decimal("8"),
        missing_quantity=Decimal("2"),
        reason="SHORT",
        status="RESOLVED",
        created_at=datetime.now(timezone.utc),
        resolution="RETURNED",
        resolved_by=UUID(USER_ID),
        resolved_at=datetime.now(timezone.utc),
        **kw,
    )


@pytest.mark.unit
class TestResolvePermission:
    """docs/claude/testing.md cases that apply to transfer:resolve_discrepancy."""

    @pytest.mark.parametrize("role", ["TA", "NM", "RM", "SA"])
    async def test_01_granted_roles_reach_the_service(self, api, inv_app, role: str) -> None:
        user = _user(role, REGION if role == "RM" else None)
        patches, audit, resolve, _, db = api(user)
        resolve.return_value = _out()
        resp = await _call(inv_app, patches, "POST", RESOLVE_URL, json={"resolution": "RETURNED"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["resolution"] == "RETURNED"
        args = resolve.await_args.args
        assert args[0] is db and args[1] is user
        assert (args[2], args[3]) == (UUID(T1), UUID(D_SHORT))
        assert args[4].resolution == "RETURNED"
        # case 11: the GRANTED decision is audited
        assert audit.await_args.args[1] == "transfer:resolve_discrepancy"
        assert audit.await_args.args[3] == "GRANTED"

    @pytest.mark.parametrize("role", ["WM", "LM", "AU"])
    async def test_02_09_12_other_roles_denied_and_audited(self, api, inv_app, role: str) -> None:
        patches, audit, resolve, _, _ = api(_user(role, WH_B))
        resp = await _call(
            inv_app, patches, "POST", RESOLVE_URL, json={"resolution": "WRITTEN_OFF", "note": "x"}
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == {
            "code": "RBAC_DENIED",
            "action": "transfer:resolve_discrepancy",
        }
        resolve.assert_not_awaited()
        assert audit.await_args.args[3:] == ("DENIED", "RBAC_DENIED")

    async def test_03_rm_of_another_tenant_cannot_see_the_row(self) -> None:
        """Every query is tenant-filtered: another tenant's RM gets 404."""
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _resolve(
                world, _user("RM", REGION, tenant_id=OTHER_TENANT), D_SHORT, resolution="RETURNED"
            )
        assert exc_info.value.status_code == 404
        assert world.updates == [] and world.ledger == []

    async def test_10_read_only_tenant_cannot_resolve(self, api, inv_app) -> None:
        """A genuine write: blocked while the tenant contract is READ_ONLY."""
        patches, _, resolve, _, _ = api(TA, stage="READ_ONLY")
        resp = await _call(inv_app, patches, "POST", RESOLVE_URL, json={"resolution": "RETURNED"})

        assert resp.status_code == 402
        assert resp.json()["detail"]["code"] == "CONTRACT_EXPIRED_READ_ONLY"
        resolve.assert_not_awaited()

    def test_10_action_is_classified_as_a_write(self) -> None:
        from shared.permissions.read_only import is_blocked_in_read_only

        assert is_blocked_in_read_only("transfer:resolve_discrepancy") is True

    async def test_14_unauthenticated_is_401(self, api, inv_app) -> None:
        patches, _, resolve, _, _ = api(None)
        resp = await _call(inv_app, patches, "POST", RESOLVE_URL, json={"resolution": "RETURNED"})

        assert resp.status_code == 401
        resolve.assert_not_awaited()

    def test_grants_match_the_seed_matrix(self) -> None:
        from shared.permissions.registry import PERMISSIONS

        assert PERMISSIONS.TRANSFER_RESOLVE_DISCREPANCY.id == "transfer:resolve_discrepancy"
        assert PERMISSIONS.TRANSFER_RESOLVE_DISCREPANCY.abac == ["tenant_id"]
        matrix = _seed_matrix()
        granted = {
            role for role, grants in matrix.items() if "transfer:resolve_discrepancy" in grants
        }
        assert granted == {"SA", "TA", "NM", "RM"}
        assert {matrix[r]["transfer:resolve_discrepancy"] for r in granted} == {"FULL"}

    def test_route_is_registered_with_the_permission(self, inv_app) -> None:
        route = next(
            r
            for r in inv_app.routes
            if getattr(r, "path", "").endswith(
                "/{transfer_id}/discrepancies/{discrepancy_id}/resolve"
            )
        )
        assert route.methods == {"POST"}
        assert route.endpoint.__permission__.id == "transfer:resolve_discrepancy"

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"resolution": "LOST"},
            {"resolution": "RETURNED", "note": "x" * 501},
            {"resolution": "RETURNED", "note": "bad\x00note"},
            {"resolution": "RETURNED", "lot_id": "not-a-uuid"},
            {"resolution": "RETURNED", "quantity": 5},
        ],
    )
    async def test_bad_body_is_422(self, api, inv_app, body: dict) -> None:
        patches, _, resolve, _, _ = api(TA)
        resp = await _call(inv_app, patches, "POST", RESOLVE_URL, json=body)

        assert resp.status_code == 422
        resolve.assert_not_awaited()


@pytest.mark.unit
class TestListEndpoint:
    async def test_fixed_path_is_not_taken_for_a_transfer_id(self, api, inv_app) -> None:
        """GET /discrepancies reaches the list, not GET /{transfer_id}."""
        patches, _, _, listing, db = api(_user("WM", WH_B))
        resp = await _call(
            inv_app, patches, "GET", LIST_URL, params={"status": "OPEN", "warehouse_id": WH_C}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == []
        assert listing.await_args.args[0] is db
        assert listing.await_args.kwargs == {"status": "OPEN", "warehouse_id": UUID(WH_C)}

    def test_declared_before_the_parameterised_get(self, inv_app) -> None:
        paths = [
            r.path
            for r in inv_app.routes
            if getattr(r, "path", "").startswith("/api/v1/inventory/transfers/")
            and "GET" in getattr(r, "methods", set())
        ]
        assert paths.index("/api/v1/inventory/transfers/discrepancies") < paths.index(
            "/api/v1/inventory/transfers/{transfer_id}"
        )

    async def test_bad_status_is_422(self, api, inv_app) -> None:
        patches, _, _, listing, _ = api(TA)
        resp = await _call(inv_app, patches, "GET", LIST_URL, params={"status": "CLOSED"})

        assert resp.status_code == 422
        listing.assert_not_awaited()

    async def test_needs_transfer_list(self, api, inv_app) -> None:
        patches, _, _, listing, _ = api(_user("RT", WH_B))
        resp = await _call(inv_app, patches, "GET", LIST_URL)

        assert resp.status_code == 403
        assert resp.json()["detail"]["action"] == "transfer:list"
        listing.assert_not_awaited()

    async def test_list_stays_available_in_read_only(self, api, inv_app) -> None:
        patches, _, _, listing, _ = api(TA, stage="READ_ONLY")
        resp = await _call(inv_app, patches, "GET", LIST_URL)

        assert resp.status_code == 200
        listing.assert_awaited_once()
