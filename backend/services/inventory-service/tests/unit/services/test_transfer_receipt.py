"""Unit tests for receipt confirmation: InventoryService.receive_transfer() with
a receipt body, services/transfer_discrepancies.py, and the receive / PATCH
endpoints.

No real database: _World answers each statement by its SQL text and keeps the
stored allocations, the discrepancy rows and every ledger / outbox call in
memory (the same approach as test_transfer_lots.py).

The transfer under test has two lines:
  LINE_1  batch product, 100 sent, split LOT-A 60 / LOT-B 40 at approval
  LINE_2  non-batch product, 30 sent
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

TENANT_ID = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"  # source
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"  # destination
PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001"  # batch
PRODUCT_2 = "aaaaaaaa-0000-0000-0000-000000000002"  # non-batch
TRANSFER_ID = UUID("cccccccc-0000-0000-0000-000000000001")
LINE_1 = "11111111-0000-0000-0000-000000000001"
LINE_2 = "11111111-0000-0000-0000-000000000002"
LOT_A = "0000000a-0000-0000-0000-000000000000"
LOT_B = "0000000b-0000-0000-0000-000000000000"
LOT_OTHER = "0000000c-0000-0000-0000-000000000000"  # not on this transfer
USER_ID = "30000000-0000-0000-0000-000000000001"
LOT_NUMBERS = {LOT_A: "LOT-A", LOT_B: "LOT-B"}
IN_KEY = f"transfer:{TRANSFER_ID}:receive:in:line"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: Optional[str]
    region_id: Optional[str]
    role: str


DST_WM = _User(USER_ID, TENANT_ID, WAREHOUSE_B, None, "WM")


class _World:
    """In-memory stand-in for the tables a receipt touches."""

    def __init__(self, status: str = "IN_TRANSIT") -> None:
        self.transfer_row = SimpleNamespace(
            status=status,
            transfer_type="PULL",
            from_warehouse_id=WAREHOUSE_A,
            to_warehouse_id=WAREHOUSE_B,
            tenant_id=TENANT_ID,
            created_by="u-creator",
            is_self_approved=False,
            reference_number=None,
            from_warehouse_name=None,
            to_warehouse_name=None,
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            total_value=None,
            currency="ETB",
            transfer_type_config_id=None,
            current_approval_step=None,
            resolved_approval_steps=None,
        )
        self.lines = [
            SimpleNamespace(id=LINE_1, product_id=PRODUCT_ID, quantity=Decimal("100")),
            SimpleNamespace(id=LINE_2, product_id=PRODUCT_2, quantity=Decimal("30")),
        ]
        self.allocations = [(LINE_1, LOT_A, Decimal("60")), (LINE_1, LOT_B, Decimal("40"))]
        self.discrepancies: list[dict] = []  # INSERT INTO transfer_discrepancies params
        self.ledger: list[dict] = []  # record_transaction kwargs
        self.audit: list[dict] = []  # write_transfer_ledger_entry kwargs
        self.status_updates: list[str] = []
        self.audit_rows: list[dict] = []  # audit_log() kwargs (transfer-linked rows)
        self.audit_error: Optional[Exception] = None
        self.outbox = AsyncMock()

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> MagicMock:
        sql, params = str(stmt), params or {}
        result = MagicMock()
        if "INSERT INTO transfer_discrepancies" in sql:
            self.discrepancies.append(dict(params))
        elif "FROM transfer_discrepancies" in sql:
            result.fetchall.return_value = [
                SimpleNamespace(
                    id=uuid4(),
                    transfer_line_id=d["line_id"],
                    product_id=d["pid"],
                    lot_id=d["lot_id"],
                    lot_number=LOT_NUMBERS.get(d["lot_id"]),
                    sent_quantity=Decimal(d["sent"]),
                    received_quantity=Decimal(d["received"]),
                    missing_quantity=Decimal(d["missing"]),
                    reason=d["reason"],
                    note=d["note"],
                    status="OPEN",
                    created_at=datetime.now(timezone.utc),
                    resolution=None,
                    resolved_lot_id=None,
                    resolved_lot_number=None,
                    resolution_note=None,
                    resolved_by=None,
                    resolved_at=None,
                )
                for d in self.discrepancies
            ]
        elif "FROM transfer_line_allocations" in sql:
            result.fetchall.return_value = [
                SimpleNamespace(
                    transfer_line_id=line_id,
                    lot_id=lot_id,
                    lot_number=LOT_NUMBERS[lot_id],
                    expiry_date=None,
                    quantity=qty,
                    is_override=False,
                    product_id=PRODUCT_ID,
                )
                for line_id, lot_id, qty in self.allocations
            ]
        elif "FROM transfer_order_lines tol" in sql:
            # list / detail line items (joined to products)
            result.fetchall.return_value = [
                SimpleNamespace(
                    line_id=line.id,
                    product_id=line.product_id,
                    product_name=f"Product {line.product_id}",
                    sku=f"SKU-{line.product_id}",
                    quantity=line.quantity,
                    uom="bags",
                )
                for line in self.lines
            ]
        elif "FROM transfer_order_lines" in sql:
            result.fetchall.return_value = self.lines
        elif "UPDATE transfer_orders" in sql:
            self.status_updates.append(sql)
        elif "FROM transfer_orders" in sql:
            result.fetchone.return_value = self.transfer_row
        return result

    async def record_transaction(self, db: Any, **kw: Any) -> str:
        self.ledger.append(kw)
        return f"tx-{len(self.ledger)}"

    async def write_transfer_ledger_entry(self, **kw: Any) -> None:
        kw.pop("session", None)  # a different mock per run — not part of the entry
        self.audit.append(kw)

    async def audit_log(self, *args: Any, **kw: Any) -> None:
        if self.audit_error is not None:
            raise self.audit_error
        self.audit_rows.append(kw)

    def db(self) -> AsyncMock:
        session = AsyncMock()
        self.session = session
        session.execute = AsyncMock(side_effect=self.execute)
        return session

    # ── views the assertions read ──
    def transfer_in(self) -> list[tuple]:
        return [
            (c.get("lot_id"), c["quantity"], c["idempotency_key"])
            for c in self.ledger
            if c["transaction_type"] == "TRANSFER_IN"
        ]

    def transit_clear(self) -> list[tuple]:
        return [
            (c["warehouse_id"], c.get("lot_id"), c["quantity"], c["line_id"])
            for c in self.audit
            if c["transaction_type"] == "TRANSIT_CLEAR"
        ]

    def transferred(self) -> list[tuple]:
        """(product_id, quantity) of every StockTransferred outbox event."""
        return [
            (c.args[3].product_id, c.args[3].quantity)
            for c in self.outbox.await_args_list
            if c.args[2] == "StockTransferred"
        ]

    def nothing_written(self) -> bool:
        return (
            self.ledger == []
            and self.audit == []
            and self.discrepancies == []
            and self.status_updates == []
            and self.outbox.await_count == 0
            and self.audit_rows == []
        )


# TRANSIT_CLEAR always clears the FULL sent quantity at both ends.
FULL_TRANSIT_CLEAR = [
    (WAREHOUSE_A, LOT_A, Decimal("-60"), f"{LINE_1}:{LOT_A}"),
    (WAREHOUSE_A, LOT_B, Decimal("-40"), f"{LINE_1}:{LOT_B}"),
    (WAREHOUSE_B, LOT_A, Decimal("-60"), f"{LINE_1}:{LOT_A}:dest"),
    (WAREHOUSE_B, LOT_B, Decimal("-40"), f"{LINE_1}:{LOT_B}:dest"),
    (WAREHOUSE_A, None, Decimal("-30"), LINE_2),
    (WAREHOUSE_B, None, Decimal("-30"), f"{LINE_2}:dest"),
]
FULL_TRANSFER_IN = [
    (LOT_A, Decimal("60"), f"{IN_KEY}:{LINE_1}:lot:{LOT_A}"),
    (LOT_B, Decimal("40"), f"{IN_KEY}:{LINE_1}:lot:{LOT_B}"),
    (None, Decimal("30"), f"{IN_KEY}:{LINE_2}"),
]


def _entry(line_id: str, lot_id: Optional[str], qty: str, **kw: Any) -> dict:
    return {"line_id": line_id, "lot_id": lot_id, "received_quantity": qty, **kw}


def _body(
    a: str = "60", b: str = "40", line2: str = "30", extra: Optional[dict[str, dict]] = None
) -> list[dict]:
    """A complete receipt: LOT-A, LOT-B and the non-batch line. extra adds
    reason/note to an entry by name: {"a": {...}, "b": {...}, "line2": {...}}."""
    extra = extra or {}
    return [
        _entry(LINE_1, LOT_A, a, **extra.get("a", {})),
        _entry(LINE_1, LOT_B, b, **extra.get("b", {})),
        _entry(LINE_2, None, line2, **extra.get("line2", {})),
    ]


async def _receive(world: _World, lines: Optional[list[dict]] = None) -> Any:
    """receive_transfer() through InventoryService, every write routed to the world."""
    from schemas.inventory import ReceiveTransferRequest
    from services.inventory_service import InventoryService

    receipt = ReceiveTransferRequest(lines=lines) if lines is not None else None
    with (
        patch("services.transfer_lots.record_transaction", new=world.record_transaction),
        patch(
            "services.transfer_lots.write_transfer_ledger_entry",
            new=world.write_transfer_ledger_entry,
        ),
        patch("services.inventory_service.record_transaction", new=world.record_transaction),
        patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=world.write_transfer_ledger_entry,
        ),
        patch("services.inventory_service.write_to_outbox", new=world.outbox),
        patch("services.inventory_service.audit_log", new=world.audit_log),
    ):
        svc = InventoryService(world.db())
        if receipt is None:
            return await svc.receive_transfer(DST_WM, TRANSFER_ID)
        return await svc.receive_transfer(DST_WM, TRANSFER_ID, receipt)


# ── receive_transfer ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestReceiveAuditRow:
    """receive_transfer() writes one transfer-linked audit row (the middleware's
    transfer:receive row has NULL resource_type/resource_id)."""

    async def test_full_receipt_writes_row_with_zero_discrepancies(self) -> None:
        world = _World()
        await _receive(world)

        assert len(world.audit_rows) == 1
        row = world.audit_rows[0]
        assert row["action"] == "transfer:receive"
        assert row["decision"] == "GRANTED"
        assert row["db"] is world.session  # caller transaction, not a separate session
        res = row["resource"]
        assert res["resource_type"] == "transfer"
        assert res["resource_id"] == str(TRANSFER_ID)
        assert res["received_quantity_total"] == "130"
        assert res["short_quantity_total"] == "0"
        assert res["discrepancy_count"] == 0
        assert "acted_on_behalf_of" not in res

    async def test_explicit_full_body_also_counts_zero(self) -> None:
        world = _World()
        await _receive(world, _body())

        assert world.audit_rows[0]["resource"]["discrepancy_count"] == 0

    async def test_short_receipt_records_totals_and_discrepancy_count(self) -> None:
        world = _World()
        await _receive(
            world,
            _body(
                a="50",
                line2="25",
                extra={"a": {"reason": "SHORT"}, "line2": {"reason": "DAMAGED"}},
            ),
        )

        assert len(world.audit_rows) == 1
        res = world.audit_rows[0]["resource"]
        assert res["received_quantity_total"] == "115"  # 50 + 40 + 25
        assert res["short_quantity_total"] == "15"  # 10 + 5
        assert res["discrepancy_count"] == 2
        assert res["discrepancy_count"] == len(world.discrepancies)

    async def test_failed_validation_writes_no_audit_row(self) -> None:
        world = _World()
        with pytest.raises(HTTPException) as exc:
            await _receive(world, _body(a="61"))  # more than sent

        assert exc.value.status_code == 422
        assert world.audit_rows == []

    async def test_audit_failure_propagates_so_the_receipt_rolls_back(self) -> None:
        """Caller-transaction mode: an audit write error is not swallowed, so the
        request's transaction (ledger, discrepancies, status) is rolled back as a unit."""
        world = _World()
        world.audit_error = RuntimeError("audit insert failed")
        with pytest.raises(RuntimeError, match="audit insert failed"):
            await _receive(world)

        assert world.audit_rows == []

    async def test_no_extra_outbox_event_for_the_audit_row(self) -> None:
        world = _World()
        await _receive(world)

        assert all(c.args[2] == "StockTransferred" for c in world.outbox.await_args_list)


@pytest.mark.unit
class TestReceiptConfirmation:
    async def test_no_body_is_a_full_receipt_with_todays_entries_and_keys(self) -> None:
        """No body: the same TRANSIT_CLEAR / TRANSFER_IN entries and idempotency
        keys as before receipt confirmation, for a batch and a non-batch line."""
        world = _World()
        result = await _receive(world)

        assert result.status == "RECEIVED"
        assert world.transit_clear() == FULL_TRANSIT_CLEAR
        assert world.transfer_in() == FULL_TRANSFER_IN
        assert {c["status_transition"] for c in world.audit} == {"IN_TRANSIT_TO_RECEIVED"}
        for call in world.ledger:
            assert call["warehouse_id"] == WAREHOUSE_B
            assert call["reference_id"] == str(TRANSFER_ID)
        assert [c.get("lot_number") for c in world.ledger] == ["LOT-A", "LOT-B", None]
        # The non-batch TRANSFER_IN carries no lot arguments at all, as today.
        assert world.ledger[2] == {
            "tenant_id": TENANT_ID,
            "transaction_type": "TRANSFER_IN",
            "product_id": PRODUCT_2,
            "warehouse_id": WAREHOUSE_B,
            "quantity": Decimal("30"),
            "performed_by": USER_ID,
            "idempotency_key": f"transfer:{TRANSFER_ID}:receive:in:line:{LINE_2}",
            "reference_id": str(TRANSFER_ID),
        }
        assert world.transferred() == [(PRODUCT_ID, 100.0), (PRODUCT_2, 30.0)]
        assert world.discrepancies == [] and result.discrepancies == []
        assert len(world.status_updates) == 1

    async def test_full_body_writes_the_same_entries_as_no_body(self) -> None:
        """All received == sent: identical ledger entries, no discrepancy. A
        reason or note on a fully received entry is ignored."""
        no_body, full_body = _World(), _World()
        await _receive(no_body)
        result = await _receive(
            full_body, _body(extra={"b": {"reason": "DAMAGED", "note": "box was dented"}})
        )

        assert result.status == "RECEIVED"
        assert full_body.ledger == no_body.ledger
        assert full_body.audit == no_body.audit
        assert full_body.transferred() == no_body.transferred()
        assert full_body.discrepancies == [] and result.discrepancies == []

    async def test_batch_lot_short_credits_received_and_records_discrepancy(self) -> None:
        """LOT-B 38 of 40, SHORT: TRANSFER_IN 38 on LOT-B with today's key, one
        discrepancy (sent 40, received 38, missing 2), TRANSIT_CLEAR still 40."""
        world = _World()
        result = await _receive(
            world, _body(b="38", extra={"b": {"reason": "SHORT", "note": "two cartons missing"}})
        )

        assert result.status == "RECEIVED"
        assert world.transit_clear() == FULL_TRANSIT_CLEAR
        assert world.transfer_in() == [
            (LOT_A, Decimal("60"), f"{IN_KEY}:{LINE_1}:lot:{LOT_A}"),
            (LOT_B, Decimal("38"), f"{IN_KEY}:{LINE_1}:lot:{LOT_B}"),
            (None, Decimal("30"), f"{IN_KEY}:{LINE_2}"),
        ]
        assert world.discrepancies == [
            {
                "tid": TENANT_ID,
                "xfer_id": str(TRANSFER_ID),
                "line_id": LINE_1,
                "pid": PRODUCT_ID,
                "lot_id": LOT_B,
                "wid": WAREHOUSE_B,
                "sent": "40",
                "received": "38",
                "missing": "2",
                "reason": "SHORT",
                "note": "two cartons missing",
                "uid": USER_ID,
            }
        ]
        assert [
            (
                str(d.transfer_line_id),
                str(d.lot_id),
                d.lot_number,
                d.sent_quantity,
                d.received_quantity,
                d.missing_quantity,
                d.reason,
                d.note,
                d.status,
            )
            for d in result.discrepancies
        ] == [
            (
                LINE_1,
                LOT_B,
                "LOT-B",
                Decimal("40"),
                Decimal("38"),
                Decimal("2"),
                "SHORT",
                "two cartons missing",
                "OPEN",
            )
        ]

    async def test_batch_lot_received_zero_damaged_posts_no_transfer_in(self) -> None:
        """LOT-A 0 of 60, DAMAGED: no TRANSFER_IN for LOT-A at all (no zero
        entry), the discrepancy's missing quantity is the whole lot."""
        world = _World()
        await _receive(world, _body(a="0", extra={"a": {"reason": "DAMAGED"}}))

        assert world.transfer_in() == [
            (LOT_B, Decimal("40"), f"{IN_KEY}:{LINE_1}:lot:{LOT_B}"),
            (None, Decimal("30"), f"{IN_KEY}:{LINE_2}"),
        ]
        assert world.transit_clear() == FULL_TRANSIT_CLEAR
        assert [
            (
                d["line_id"],
                d["lot_id"],
                d["sent"],
                d["received"],
                d["missing"],
                d["reason"],
                d["note"],
            )
            for d in world.discrepancies
        ] == [(LINE_1, LOT_A, "60", "0", "60", "DAMAGED", None)]

    async def test_non_batch_line_short_damaged_has_null_lot_id(self) -> None:
        """Non-batch line 25 of 30, DAMAGED: TRANSFER_IN 25 with the line key,
        discrepancy with lot_id NULL. (WRONG_LOT is refused on a non-batch
        line — test_wrong_lot_on_non_batch_line_is_422_and_nothing_is_written.)"""
        world = _World()
        result = await _receive(world, _body(line2="25", extra={"line2": {"reason": "DAMAGED"}}))

        assert world.transfer_in()[2] == (None, Decimal("25"), f"{IN_KEY}:{LINE_2}")
        assert "lot_id" not in world.ledger[2]
        assert world.transit_clear() == FULL_TRANSIT_CLEAR
        assert [
            (
                d["line_id"],
                d["pid"],
                d["lot_id"],
                d["sent"],
                d["received"],
                d["missing"],
                d["reason"],
            )
            for d in world.discrepancies
        ] == [(LINE_2, PRODUCT_2, None, "30", "25", "5", "DAMAGED")]
        assert result.discrepancies[0].lot_id is None
        assert result.discrepancies[0].lot_number is None

    async def test_received_more_than_sent_is_422_and_nothing_is_written(self) -> None:
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _receive(world, _body(b="41"))

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "code": "RECEIPT_EXCEEDS_SENT",
            "line_id": LINE_1,
            "lot_id": LOT_B,
            "sent": 40.0,
            "received": 41.0,
        }
        assert world.nothing_written()

    @pytest.mark.parametrize(
        "case, lines",
        [
            ("missing entry", _body()[:2]),
            ("extra entry", _body() + [_entry(LINE_1, LOT_OTHER, "5")]),
            ("duplicate entry", _body() + [_entry(LINE_2, None, "30")]),
            (
                "unknown lot_id",
                [
                    _entry(LINE_1, LOT_A, "60"),
                    _entry(LINE_1, LOT_OTHER, "40"),
                    _entry(LINE_2, None, "30"),
                ],
            ),
            (
                "lot_id on a non-batch line",
                [
                    _entry(LINE_1, LOT_A, "60"),
                    _entry(LINE_1, LOT_B, "40"),
                    _entry(LINE_2, LOT_A, "30"),
                ],
            ),
            (
                "batch line without lot_id",
                [_entry(LINE_1, None, "100"), _entry(LINE_2, None, "30")],
            ),
        ],
    )
    async def test_lines_mismatch_is_422_and_nothing_is_written(
        self, case: str, lines: list[dict]
    ) -> None:
        """The body must list every (line, lot) on the transfer exactly once."""
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _receive(world, lines)

        assert exc_info.value.status_code == 422, case
        assert exc_info.value.detail == {
            "code": "RECEIPT_LINES_MISMATCH",
            "expected": [
                {"line_id": LINE_1, "lot_id": LOT_A},
                {"line_id": LINE_1, "lot_id": LOT_B},
                {"line_id": LINE_2, "lot_id": None},
            ],
        }, case
        assert world.nothing_written(), case

    async def test_shortfall_without_reason_is_422_and_nothing_is_written(self) -> None:
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _receive(world, _body(line2="29"))

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "code": "RECEIPT_REASON_REQUIRED",
            "line_id": LINE_2,
            "lot_id": None,
        }
        assert world.nothing_written()

    async def test_wrong_lot_on_non_batch_line_is_422_and_nothing_is_written(self) -> None:
        """WRONG_LOT needs a lot — on a non-batch entry (lot_id None) it is refused."""
        world = _World()
        with pytest.raises(HTTPException) as exc_info:
            await _receive(world, _body(line2="29", extra={"line2": {"reason": "WRONG_LOT"}}))

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "code": "WRONG_LOT_NOT_BATCH",
            "line_id": LINE_2,
            "lot_id": None,
        }
        assert world.nothing_written()

    async def test_non_batch_line_with_short_is_accepted(self) -> None:
        world = _World()
        await _receive(world, _body(line2="29", extra={"line2": {"reason": "SHORT"}}))

        assert [(d["line_id"], d["lot_id"], d["reason"]) for d in world.discrepancies] == [
            (LINE_2, None, "SHORT"),
        ]

    async def test_batch_line_with_wrong_lot_is_accepted(self) -> None:
        world = _World()
        await _receive(world, _body(b="38", extra={"b": {"reason": "WRONG_LOT"}}))

        assert [(d["line_id"], d["lot_id"], d["reason"]) for d in world.discrepancies] == [
            (LINE_1, LOT_B, "WRONG_LOT"),
        ]

    async def test_outbox_quantity_is_the_received_total_and_zero_fires_no_event(self) -> None:
        """StockTransferred carries the line's received total (60 + 38 = 98); a
        line that received nothing fires no event and posts no TRANSFER_IN."""
        world = _World()
        await _receive(
            world,
            _body(
                b="38",
                line2="0",
                extra={"b": {"reason": "SHORT"}, "line2": {"reason": "DAMAGED"}},
            ),
        )

        assert world.transferred() == [(PRODUCT_ID, 98.0)]
        assert [t[0] for t in world.transfer_in()] == [LOT_A, LOT_B]
        assert world.transit_clear() == FULL_TRANSIT_CLEAR
        assert [(d["line_id"], d["lot_id"], d["missing"]) for d in world.discrepancies] == [
            (LINE_1, LOT_B, "2"),
            (LINE_2, None, "30"),
        ]

    async def test_partially_received_transfer_can_still_be_received(self) -> None:
        """A transfer already sitting in PARTIALLY_RECEIVED still moves to RECEIVED."""
        world = _World(status="PARTIALLY_RECEIVED")
        result = await _receive(world, _body())

        assert result.status == "RECEIVED"
        assert world.transfer_in() == FULL_TRANSFER_IN

    async def test_get_transfer_returns_discrepancies(self) -> None:
        from services.inventory_service import InventoryService

        world = _World(status="RECEIVED")
        world.discrepancies.append(
            {
                "line_id": LINE_1,
                "pid": PRODUCT_ID,
                "lot_id": LOT_B,
                "sent": "40",
                "received": "38",
                "missing": "2",
                "reason": "SHORT",
                "note": None,
            }
        )
        result = await InventoryService(world.db()).get_transfer(DST_WM, TRANSFER_ID)

        assert [
            (
                str(d.transfer_line_id),
                str(d.product_id),
                str(d.lot_id),
                d.lot_number,
                d.sent_quantity,
                d.received_quantity,
                d.missing_quantity,
                d.reason,
                d.status,
            )
            for d in result.discrepancies
        ] == [
            (
                LINE_1,
                PRODUCT_ID,
                LOT_B,
                "LOT-B",
                Decimal("40"),
                Decimal("38"),
                Decimal("2"),
                "SHORT",
                "OPEN",
            )
        ]
        # An OPEN row carries no resolution yet (088 columns all NULL).
        assert [
            (
                d.resolution,
                d.resolved_lot_id,
                d.resolved_lot_number,
                d.resolution_note,
                d.resolved_by,
                d.resolved_at,
            )
            for d in result.discrepancies
        ] == [(None, None, None, None, None, None)]
        assert len(result.lot_allocations) == 2

    async def test_get_transfer_returns_lines_with_line_id(self) -> None:
        """GET /{id} lists every line with its line_id — batch and non-batch alike."""
        from services.inventory_service import InventoryService

        world = _World()
        result = await InventoryService(world.db()).get_transfer(DST_WM, TRANSFER_ID)

        assert [
            (str(line.line_id), str(line.product_id), line.quantity) for line in result.lines
        ] == [
            (LINE_1, PRODUCT_ID, Decimal("100")),
            (LINE_2, PRODUCT_2, Decimal("30")),
        ]
        # every allocation points at a returned line
        assert {str(a.line_id) for a in result.lot_allocations} <= {
            str(line.line_id) for line in result.lines
        }


# ── endpoints ────────────────────────────────────────────────────────────────


def _allow_all():
    """Permission granted, tenant ACTIVE — the handlers run for real."""
    from shared.permissions.middleware import PermissionResult

    return (
        patch(
            "shared.permissions.middleware.check_permission",
            AsyncMock(return_value=PermissionResult(allowed=True)),
        ),
        patch(
            "shared.billing.contract_stage.get_tenant_contract_stage",
            AsyncMock(
                return_value={"stage": "ACTIVE", "contract_end": None, "read_only_since": None}
            ),
        ),
    )


@pytest.mark.unit
class TestReceiptEndpoints:
    async def test_patch_partially_received_is_422_before_any_service_call(self, wm_user) -> None:
        from routers.transfer import transition_transfer
        from schemas.inventory import TransferTransitionRequest

        allow, active = _allow_all()
        with allow, active, patch("routers.transfer.InventoryService") as svc_cls:
            with pytest.raises(HTTPException) as exc_info:
                await transition_transfer(
                    transfer_id=TRANSFER_ID,
                    body=TransferTransitionRequest(next_status="PARTIALLY_RECEIVED"),
                    user=wm_user,
                    db=AsyncMock(),
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "code": "PARTIAL_RECEIPT_NOT_SUPPORTED",
            "detail": "Use POST /transfers/{id}/receive with the received quantities.",
        }
        svc_cls.assert_not_called()

    async def test_patch_received_stays_a_full_receipt(self, wm_user) -> None:
        """PATCH next_status=RECEIVED calls receive_transfer() with no receipt."""
        from routers.transfer import transition_transfer
        from schemas.inventory import TransferTransitionRequest

        allow, active = _allow_all()
        with allow, active, patch("routers.transfer.InventoryService") as svc_cls:
            svc_cls.return_value.receive_transfer = AsyncMock(return_value=MagicMock())
            await transition_transfer(
                transfer_id=TRANSFER_ID,
                body=TransferTransitionRequest(next_status="RECEIVED"),
                user=wm_user,
                db=AsyncMock(),
            )

        svc_cls.return_value.receive_transfer.assert_awaited_once_with(wm_user, TRANSFER_ID)

    async def test_receive_endpoint_passes_the_body_through(self, wm_user) -> None:
        """POST /receive needs transfer:receive and hands the parsed body to the
        service; with no body the service gets None (a full receipt)."""
        from routers.transfer import receive_transfer
        from schemas.inventory import ReceiveTransferRequest
        from shared.permissions.middleware import PermissionResult

        check = AsyncMock(return_value=PermissionResult(allowed=True))
        body = ReceiveTransferRequest(lines=_body(b="38", extra={"b": {"reason": "SHORT"}}))
        _, active = _allow_all()
        with (
            patch("shared.permissions.middleware.check_permission", check),
            active,
            patch("routers.transfer.InventoryService") as svc_cls,
        ):
            svc_cls.return_value.receive_transfer = AsyncMock(return_value=MagicMock())
            await receive_transfer(transfer_id=TRANSFER_ID, body=body, user=wm_user, db=AsyncMock())
            await receive_transfer(transfer_id=TRANSFER_ID, body=None, user=wm_user, db=AsyncMock())

        assert [c.args for c in svc_cls.return_value.receive_transfer.await_args_list] == [
            (wm_user, TRANSFER_ID, body),
            (wm_user, TRANSFER_ID, None),
        ]
        assert {c.args[1].id for c in check.await_args_list} == {"transfer:receive"}

    def test_receive_request_schema_limits(self) -> None:
        from pydantic import ValidationError
        from schemas.inventory import ReceiveTransferRequest

        ok = ReceiveTransferRequest(
            lines=[_entry(LINE_2, None, "0", reason="DAMAGED", note="x" * 500)]
        )
        assert ok.lines[0].received_quantity == Decimal("0")
        for bad in (
            {"lines": []},
            {"lines": [_entry(LINE_2, None, "-1")]},
            {"lines": [_entry(LINE_2, None, "1.00001")]},
            {"lines": [_entry(LINE_2, None, "1", reason="LOST")]},
            {"lines": [_entry(LINE_2, None, "1", note="x" * 501)]},
            {"lines": [_entry(LINE_2, None, "1", note="bad\x00note")]},
        ):
            with pytest.raises(ValidationError):
                ReceiveTransferRequest(**bad)
