"""Unit tests for services/dispatch_service.py.

The pure layer (resolve_strategy / sort_lots / plan_allocation /
compare_selection) is tested directly. The DB layer is tested with a mocked
session — scripts/smoke_dispatch_engine.py proves the real SQL.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


TENANT_ID    = "10000000-0000-0000-0000-000000000001"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"
USER_ID      = "40000000-0000-0000-0000-000000000001"

TODAY = date(2026, 10, 13)
T0 = datetime(2026, 1, 1)

LOT_OPENING = "30000000-0000-0000-0000-000000000001"
LOT_1       = "30000000-0000-0000-0000-000000000002"
LOT_2       = "30000000-0000-0000-0000-000000000003"
LOT_3       = "30000000-0000-0000-0000-000000000004"


def _lot(lot_id, lot_number, quantity="10", expiry_date=None, received_day=0):
    from services.dispatch_service import CandidateLot

    return CandidateLot(
        lot_id=lot_id,
        lot_number=lot_number,
        expiry_date=expiry_date,
        first_received_at=T0 + timedelta(days=received_day),
        quantity=Decimal(quantity),
    )


def _standard_lots():
    """OPENING (no expiry, oldest), L1 (expires +90, day 1), L2 (expires +30, day 2)."""
    return [
        _lot(LOT_1, "L1", expiry_date=TODAY + timedelta(days=90), received_day=1),
        _lot(LOT_2, "L2", expiry_date=TODAY + timedelta(days=30), received_day=2),
        _lot(LOT_OPENING, "OPENING-MWH", received_day=0),
    ]


def _numbers(lots):
    return [lot.lot_number for lot in lots]


def _row(lot):
    return MagicMock(
        lot_id=lot.lot_id,
        lot_number=lot.lot_number,
        expiry_date=lot.expiry_date,
        first_received_at=lot.first_received_at,
        quantity=lot.quantity,
    )


def _result(fetchall=None, fetchone=None):
    r = MagicMock()
    r.fetchall.return_value = fetchall or []
    r.fetchone.return_value = fetchone
    return r


def _session(*results):
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(results))
    return session


def _sql(session, call_index):
    return str(session.execute.call_args_list[call_index].args[0])


@pytest.mark.unit
class TestResolveStrategy:

    def test_not_batch_returns_none_not_batch(self) -> None:
        from services.dispatch_service import resolve_strategy

        assert resolve_strategy(False, False, None) == (None, "NOT_BATCH")

    def test_not_batch_ignores_product_strategy(self) -> None:
        from services.dispatch_service import resolve_strategy

        assert resolve_strategy(False, False, "LIFO") == (None, "NOT_BATCH")

    def test_expiry_tracking_forces_fefo(self) -> None:
        from services.dispatch_service import resolve_strategy

        assert resolve_strategy(True, True, "LIFO") == ("FEFO", "FORCED")

    def test_product_strategy_used_when_set(self) -> None:
        from services.dispatch_service import resolve_strategy

        assert resolve_strategy(True, False, "LIFO") == ("LIFO", "PRODUCT")

    def test_default_is_fifo(self) -> None:
        from services.dispatch_service import resolve_strategy

        assert resolve_strategy(True, False, None) == ("FIFO", "DEFAULT")


@pytest.mark.unit
class TestSortLots:

    def test_fefo_no_expiry_first_then_earliest_expiry(self) -> None:
        from services.dispatch_service import sort_lots

        assert _numbers(sort_lots(_standard_lots(), "FEFO")) == ["OPENING-MWH", "L2", "L1"]

    def test_fefo_later_receipt_with_earlier_expiry_goes_first(self) -> None:
        from services.dispatch_service import sort_lots

        lots = [
            _lot(LOT_1, "EARLY-RECEIPT", expiry_date=TODAY + timedelta(days=90), received_day=1),
            _lot(LOT_2, "LATE-RECEIPT", expiry_date=TODAY + timedelta(days=30), received_day=50),
        ]
        assert _numbers(sort_lots(lots, "FEFO")) == ["LATE-RECEIPT", "EARLY-RECEIPT"]

    def test_fefo_same_expiry_ties_break_on_received_then_lot_number(self) -> None:
        from services.dispatch_service import sort_lots

        expiry = TODAY + timedelta(days=30)
        lots = [
            _lot(LOT_1, "B", expiry_date=expiry, received_day=5),
            _lot(LOT_2, "A", expiry_date=expiry, received_day=5),
            _lot(LOT_3, "Z", expiry_date=expiry, received_day=1),
        ]
        assert _numbers(sort_lots(lots, "FEFO")) == ["Z", "A", "B"]

    def test_fefo_multiple_no_expiry_lots_ordered_by_received(self) -> None:
        from services.dispatch_service import sort_lots

        lots = [
            _lot(LOT_1, "NOEXP-NEW", received_day=9),
            _lot(LOT_2, "DATED", expiry_date=TODAY + timedelta(days=1), received_day=0),
            _lot(LOT_3, "NOEXP-OLD", received_day=2),
        ]
        assert _numbers(sort_lots(lots, "FEFO")) == ["NOEXP-OLD", "NOEXP-NEW", "DATED"]

    def test_fifo_oldest_receipt_first(self) -> None:
        from services.dispatch_service import sort_lots

        assert _numbers(sort_lots(_standard_lots(), "FIFO")) == ["OPENING-MWH", "L1", "L2"]

    def test_fifo_tie_breaks_on_lot_number(self) -> None:
        from services.dispatch_service import sort_lots

        lots = [_lot(LOT_1, "B", received_day=3), _lot(LOT_2, "A", received_day=3)]
        assert _numbers(sort_lots(lots, "FIFO")) == ["A", "B"]

    def test_lifo_newest_receipt_first(self) -> None:
        from services.dispatch_service import sort_lots

        assert _numbers(sort_lots(_standard_lots(), "LIFO")) == ["L2", "L1", "OPENING-MWH"]

    def test_lifo_tie_breaks_on_lot_number_ascending(self) -> None:
        from services.dispatch_service import sort_lots

        lots = [
            _lot(LOT_1, "B", received_day=3),
            _lot(LOT_2, "A", received_day=3),
            _lot(LOT_3, "OLD", received_day=1),
        ]
        assert _numbers(sort_lots(lots, "LIFO")) == ["A", "B", "OLD"]

    def test_order_is_independent_of_input_order(self) -> None:
        from services.dispatch_service import sort_lots

        lots = _standard_lots()
        for strategy in ("FEFO", "FIFO", "LIFO"):
            assert sort_lots(lots, strategy) == sort_lots(list(reversed(lots)), strategy)

    def test_unknown_strategy_raises_value_error(self) -> None:
        from services.dispatch_service import sort_lots

        with pytest.raises(ValueError):
            sort_lots(_standard_lots(), "RANDOM")


@pytest.mark.unit
class TestPlanAllocation:

    def test_single_lot_covers_quantity(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation(_standard_lots(), Decimal("4"), "FEFO", TODAY)

        assert [(line.lot_number, line.quantity) for line in plan.lines] == [("OPENING-MWH", Decimal("4"))]
        assert plan.shortfall == Decimal("0")
        assert plan.expired_skipped == []

    def test_spills_across_lots_in_strategy_order(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation(_standard_lots(), Decimal("25"), "FEFO", TODAY)

        assert [(line.lot_number, line.quantity) for line in plan.lines] == [
            ("OPENING-MWH", Decimal("10")),
            ("L2", Decimal("10")),
            ("L1", Decimal("5")),
        ]
        assert plan.shortfall == Decimal("0")

    def test_line_carries_lot_id_and_expiry(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation(_standard_lots(), Decimal("15"), "FEFO", TODAY)

        assert plan.lines[1].lot_id == LOT_2
        assert plan.lines[1].expiry_date == TODAY + timedelta(days=30)
        assert plan.lines[0].expiry_date is None

    def test_expired_lot_never_allocated_and_reported(self) -> None:
        from services.dispatch_service import plan_allocation

        lots = _standard_lots() + [
            _lot(LOT_3, "L3", quantity="7", expiry_date=TODAY - timedelta(days=1), received_day=3)
        ]
        plan = plan_allocation(lots, Decimal("30"), "FEFO", TODAY)

        assert "L3" not in [line.lot_number for line in plan.lines]
        assert [(lot.lot_number, lot.quantity) for lot in plan.expired_skipped] == [("L3", Decimal("7"))]
        assert plan.shortfall == Decimal("0")

    def test_expired_lot_skipped_under_fifo_and_lifo_too(self) -> None:
        from services.dispatch_service import plan_allocation

        lots = [_lot(LOT_3, "L3", expiry_date=TODAY - timedelta(days=1))]
        for strategy in ("FIFO", "LIFO"):
            plan = plan_allocation(lots, Decimal("5"), strategy, TODAY)
            assert plan.lines == []
            assert plan.shortfall == Decimal("5")
            assert [lot.lot_number for lot in plan.expired_skipped] == ["L3"]

    def test_lot_expiring_today_is_still_allocatable(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation([_lot(LOT_1, "L1", expiry_date=TODAY)], Decimal("5"), "FEFO", TODAY)

        assert [line.lot_number for line in plan.lines] == ["L1"]
        assert plan.expired_skipped == []

    def test_expired_reported_even_when_quantity_already_covered(self) -> None:
        from services.dispatch_service import plan_allocation

        lots = [
            _lot(LOT_OPENING, "OPENING-MWH"),
            _lot(LOT_3, "L3", expiry_date=TODAY - timedelta(days=1)),
        ]
        plan = plan_allocation(lots, Decimal("1"), "FEFO", TODAY)

        assert [lot.lot_number for lot in plan.expired_skipped] == ["L3"]

    def test_shortfall_when_stock_does_not_cover(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation(_standard_lots(), Decimal("42.5"), "FIFO", TODAY)

        assert sum(line.quantity for line in plan.lines) == Decimal("30")
        assert plan.shortfall == Decimal("12.5")

    def test_no_lots_gives_full_shortfall_without_raising(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation([], Decimal("3"), "FIFO", TODAY)

        assert plan.lines == []
        assert plan.shortfall == Decimal("3")

    def test_zero_quantity_lots_ignored(self) -> None:
        from services.dispatch_service import plan_allocation

        lots = [
            _lot(LOT_OPENING, "OPENING-MWH", quantity="0"),
            _lot(LOT_3, "L3", quantity="0", expiry_date=TODAY - timedelta(days=1)),
            _lot(LOT_1, "L1", quantity="5", received_day=1),
        ]
        plan = plan_allocation(lots, Decimal("5"), "FIFO", TODAY)

        assert [line.lot_number for line in plan.lines] == ["L1"]
        assert plan.expired_skipped == []
        assert plan.shortfall == Decimal("0")

    def test_lifo_draws_from_newest_first(self) -> None:
        from services.dispatch_service import plan_allocation

        plan = plan_allocation(_standard_lots(), Decimal("12"), "LIFO", TODAY)

        assert [(line.lot_number, line.quantity) for line in plan.lines] == [
            ("L2", Decimal("10")),
            ("L1", Decimal("2")),
        ]


@pytest.mark.unit
class TestCompareSelection:

    def _plan(self):
        from services.dispatch_service import plan_allocation

        return plan_allocation(_standard_lots(), Decimal("15"), "FEFO", TODAY)

    def test_same_lots_and_quantities_is_not_override(self) -> None:
        from services.dispatch_service import compare_selection

        chosen = [
            {"lot_id": LOT_OPENING, "quantity": Decimal("10")},
            {"lot_id": LOT_2, "quantity": Decimal("5")},
        ]
        assert compare_selection(self._plan(), chosen) is False

    def test_same_set_in_different_order_is_not_override(self) -> None:
        from services.dispatch_service import compare_selection

        chosen = [
            {"lot_id": LOT_2, "quantity": "5.0000"},
            {"lot_id": LOT_OPENING, "quantity": "10"},
        ]
        assert compare_selection(self._plan(), chosen) is False

    def test_different_lot_is_override(self) -> None:
        from services.dispatch_service import compare_selection

        chosen = [
            {"lot_id": LOT_OPENING, "quantity": Decimal("10")},
            {"lot_id": LOT_1, "quantity": Decimal("5")},
        ]
        assert compare_selection(self._plan(), chosen) is True

    def test_same_lots_different_split_is_override(self) -> None:
        from services.dispatch_service import compare_selection

        chosen = [
            {"lot_id": LOT_OPENING, "quantity": Decimal("5")},
            {"lot_id": LOT_2, "quantity": Decimal("10")},
        ]
        assert compare_selection(self._plan(), chosen) is True

    def test_accepts_objects_as_well_as_dicts(self) -> None:
        import uuid

        from schemas.inventory import LotChoice
        from services.dispatch_service import compare_selection

        chosen = [
            LotChoice(lot_id=uuid.UUID(LOT_OPENING), quantity=Decimal("10")),
            LotChoice(lot_id=uuid.UUID(LOT_2), quantity=Decimal("5")),
        ]
        assert compare_selection(self._plan(), chosen) is False


@pytest.mark.unit
class TestLoadCandidateLots:

    async def test_preview_read_does_not_lock(self) -> None:
        from services.dispatch_service import load_candidate_lots

        session = _session(_result(fetchall=[_row(lot) for lot in _standard_lots()]))

        lots = await load_candidate_lots(session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID)

        assert session.execute.await_count == 1
        assert "FOR UPDATE" not in _sql(session, 0)
        assert "quantity > 0" in _sql(session, 0)
        assert sorted(_numbers(lots)) == ["L1", "L2", "OPENING-MWH"]
        assert all(isinstance(lot.quantity, Decimal) for lot in lots)

    async def test_lock_true_locks_in_lot_id_order_before_reading(self) -> None:
        from services.dispatch_service import load_candidate_lots

        session = _session(_result(), _result(fetchall=[]))

        await load_candidate_lots(session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID, lock=True)

        assert session.execute.await_count == 2
        assert "ORDER BY lb.lot_id FOR UPDATE" in _sql(session, 0)
        assert "FOR UPDATE" not in _sql(session, 1)

    async def test_query_is_scoped_to_tenant_product_warehouse(self) -> None:
        from services.dispatch_service import load_candidate_lots

        session = _session(_result(fetchall=[]))

        await load_candidate_lots(session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID)

        params = session.execute.call_args_list[0].args[1]
        assert params == {"tid": TENANT_ID, "pid": PRODUCT_ID, "wid": WAREHOUSE_ID}


@pytest.mark.unit
class TestLoadProduct:

    async def test_returns_tracking_flags_and_strategy(self) -> None:
        from services.dispatch_service import load_product

        row = MagicMock(batch_tracking=True, expiry_tracking=False, dispatch_strategy="LIFO")
        session = _session(_result(fetchone=row))

        product = await load_product(session, TENANT_ID, PRODUCT_ID)

        assert (product.batch_tracking, product.expiry_tracking, product.dispatch_strategy) == (
            True, False, "LIFO",
        )

    async def test_missing_product_raises_404_product_not_found(self) -> None:
        from services.dispatch_service import load_product

        session = _session(_result(fetchone=None))

        with pytest.raises(HTTPException) as exc_info:
            await load_product(session, TENANT_ID, PRODUCT_ID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.unit
class TestAllocate:

    async def test_locks_and_returns_plan(self) -> None:
        from services.dispatch_service import allocate

        session = _session(_result(), _result(fetchall=[_row(lot) for lot in _standard_lots()]))

        plan = await allocate(
            session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal("15"), "FEFO", today=TODAY
        )

        assert "FOR UPDATE" in _sql(session, 0)
        assert [line.lot_number for line in plan.lines] == ["OPENING-MWH", "L2"]

    async def test_shortfall_raises_insufficient_stock_error(self) -> None:
        from services.dispatch_service import InsufficientStockError, allocate

        session = _session(_result(), _result(fetchall=[_row(lot) for lot in _standard_lots()]))

        with pytest.raises(InsufficientStockError) as exc_info:
            await allocate(
                session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal("31"), "FIFO", today=TODAY
            )

        assert str(exc_info.value.product_id) == PRODUCT_ID
        assert exc_info.value.required == Decimal("31")
        assert exc_info.value.available == Decimal("30")


@pytest.mark.unit
class TestValidateManualSelection:

    async def _run(self, chosen, qty="15", lots=None, strategy="FEFO"):
        from services.dispatch_service import validate_manual_selection

        lots = _standard_lots() if lots is None else lots
        session = _session(_result(), _result(fetchall=[_row(lot) for lot in lots]))
        return await validate_manual_selection(
            session, TENANT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal(qty), chosen, strategy,
            today=TODAY,
        )

    async def _code(self, chosen, **kwargs):
        from services.dispatch_service import DispatchError

        with pytest.raises(DispatchError) as exc_info:
            await self._run(chosen, **kwargs)
        return exc_info.value.code

    async def test_selection_matching_plan_is_not_override(self) -> None:
        plan, is_override = await self._run([
            {"lot_id": LOT_OPENING, "quantity": Decimal("10")},
            {"lot_id": LOT_2, "quantity": Decimal("5")},
        ])
        assert is_override is False
        assert [line.lot_number for line in plan.lines] == ["OPENING-MWH", "L2"]

    async def test_valid_selection_differing_from_plan_is_override(self) -> None:
        plan, is_override = await self._run([
            {"lot_id": LOT_1, "quantity": Decimal("10")},
            {"lot_id": LOT_2, "quantity": Decimal("5")},
        ])
        assert is_override is True
        assert [line.lot_number for line in plan.lines] == ["OPENING-MWH", "L2"]

    async def test_lot_from_another_warehouse_or_product_rejected(self) -> None:
        code = await self._code([
            {"lot_id": "30000000-0000-0000-0000-0000000000ff", "quantity": Decimal("15")},
        ])
        assert code == "LOT_NOT_IN_WAREHOUSE"

    async def test_expired_lot_rejected(self) -> None:
        lots = _standard_lots() + [
            _lot(LOT_3, "L3", quantity="20", expiry_date=TODAY - timedelta(days=1))
        ]
        code = await self._code([{"lot_id": LOT_3, "quantity": Decimal("15")}], lots=lots)
        assert code == "LOT_EXPIRED"

    async def test_quantity_above_lot_balance_rejected(self) -> None:
        code = await self._code([{"lot_id": LOT_1, "quantity": Decimal("15")}])
        assert code == "INSUFFICIENT_LOT_STOCK"

    async def test_duplicate_lines_for_one_lot_are_summed_against_balance(self) -> None:
        code = await self._code([
            {"lot_id": LOT_1, "quantity": Decimal("8")},
            {"lot_id": LOT_1, "quantity": Decimal("7")},
        ])
        assert code == "INSUFFICIENT_LOT_STOCK"

    async def test_sum_not_equal_to_quantity_rejected(self) -> None:
        code = await self._code([
            {"lot_id": LOT_OPENING, "quantity": Decimal("10")},
            {"lot_id": LOT_2, "quantity": Decimal("4")},
        ])
        assert code == "SELECTION_QTY_MISMATCH"

    async def test_non_positive_line_rejected(self) -> None:
        code = await self._code([
            {"lot_id": LOT_OPENING, "quantity": Decimal("15")},
            {"lot_id": LOT_2, "quantity": Decimal("0")},
        ])
        assert code == "SELECTION_QTY_MISMATCH"

    async def test_raises_domain_error_not_http_exception(self) -> None:
        from services.dispatch_service import DispatchError

        with pytest.raises(DispatchError) as exc_info:
            await self._run([{"lot_id": LOT_1, "quantity": Decimal("15")}])
        assert not isinstance(exc_info.value, HTTPException)
        assert exc_info.value.detail["available"] == "10"


@pytest.mark.unit
class TestRecordOverride:

    def _plan(self):
        from services.dispatch_service import plan_allocation

        return plan_allocation(_standard_lots(), Decimal("15"), "FEFO", TODAY)

    _CHOSEN = [
        {"lot_id": LOT_1, "quantity": Decimal("10")},
        {"lot_id": LOT_2, "quantity": Decimal("5")},
    ]

    async def _run(self, strategy, reason):
        from services.dispatch_service import record_override

        lot_rows = [MagicMock(id=lot.lot_id, lot_number=lot.lot_number) for lot in _standard_lots()]
        session = _session(
            _result(fetchall=lot_rows),
            _result(fetchone=MagicMock(id="override-id-001")),
        )
        override_id = await record_override(
            session, TENANT_ID, USER_ID, PRODUCT_ID, WAREHOUSE_ID, strategy, "ISSUE", None,
            Decimal("15"), self._plan(), self._CHOSEN, reason,
        )
        return session, override_id

    @pytest.mark.parametrize("reason", [None, "", "   "])
    async def test_fefo_without_reason_raises_before_any_query(self, reason) -> None:
        from services.dispatch_service import DispatchError, record_override

        session = AsyncMock()
        with pytest.raises(DispatchError) as exc_info:
            await record_override(
                session, TENANT_ID, USER_ID, PRODUCT_ID, WAREHOUSE_ID, "FEFO", "ISSUE", None,
                Decimal("15"), self._plan(), self._CHOSEN, reason,
            )

        assert exc_info.value.code == "OVERRIDE_REASON_REQUIRED"
        session.execute.assert_not_awaited()

    async def test_fefo_with_reason_inserts_one_row(self) -> None:
        import json

        session, override_id = await self._run("FEFO", "  customer asked for the long-dated lot ")

        assert override_id == "override-id-001"
        assert session.execute.await_count == 2
        assert "INSERT INTO lot_allocation_overrides" in _sql(session, 1)
        params = session.execute.call_args_list[1].args[1]
        assert params["reason"] == "customer asked for the long-dated lot"
        assert params["strategy"] == "FEFO"
        assert params["uid"] == USER_ID
        assert json.loads(params["suggested"]) == [
            {"lot_id": LOT_OPENING, "lot_number": "OPENING-MWH", "quantity": "10"},
            {"lot_id": LOT_2, "lot_number": "L2", "quantity": "5"},
        ]
        assert json.loads(params["chosen"]) == [
            {"lot_id": LOT_1, "lot_number": "L1", "quantity": "10"},
            {"lot_id": LOT_2, "lot_number": "L2", "quantity": "5"},
        ]

    @pytest.mark.parametrize("strategy", ["FIFO", "LIFO"])
    async def test_fifo_lifo_reason_is_optional(self, strategy) -> None:
        session, override_id = await self._run(strategy, None)

        assert override_id == "override-id-001"
        assert session.execute.call_args_list[1].args[1]["reason"] is None

    def test_module_exposes_no_update_or_delete_path(self) -> None:
        import inspect

        from services import dispatch_service

        source = inspect.getsource(dispatch_service)
        assert "UPDATE lot_allocation_overrides" not in source
        assert "DELETE FROM lot_allocation_overrides" not in source
