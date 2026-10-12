"""Unit tests for repositories/lot_repo.py."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


TENANT_ID    = "10000000-0000-0000-0000-000000000001"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
USER_ID      = "u-wm-01"
LOT_ID       = "lot-id-001"
WAREHOUSE_ID = "wh-id-001"


def _make_session(existing_expiry) -> AsyncMock:
    """call 0 — INSERT ... ON CONFLICT DO NOTHING; call 1 — SELECT id, expiry_date."""
    insert_result = MagicMock()

    select_row = MagicMock()
    select_row.id = "lot-id-001"
    select_row.expiry_date = existing_expiry

    select_result = MagicMock()
    select_result.fetchone.return_value = select_row

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[insert_result, select_result])
    return session


@pytest.mark.unit
class TestGetOrCreateLot:

    async def test_new_lot_creates_and_returns_id(self) -> None:
        from repositories.lot_repo import get_or_create_lot

        session = _make_session(existing_expiry=date(2027, 1, 1))

        lot_id = await get_or_create_lot(
            session, TENANT_ID, PRODUCT_ID, "LOT-A1", date(2027, 1, 1), USER_ID
        )

        assert lot_id == "lot-id-001"
        assert session.execute.await_count == 2

    async def test_same_lot_same_expiry_returns_same_id(self) -> None:
        from repositories.lot_repo import get_or_create_lot

        session = _make_session(existing_expiry=date(2027, 1, 1))

        lot_id = await get_or_create_lot(
            session, TENANT_ID, PRODUCT_ID, "LOT-A1", date(2027, 1, 1), USER_ID
        )

        assert lot_id == "lot-id-001"

    async def test_same_lot_none_expiry_both_counts_as_same(self) -> None:
        from repositories.lot_repo import get_or_create_lot

        session = _make_session(existing_expiry=None)

        lot_id = await get_or_create_lot(
            session, TENANT_ID, PRODUCT_ID, "LOT-A1", None, USER_ID
        )

        assert lot_id == "lot-id-001"

    async def test_same_lot_different_expiry_raises_422(self) -> None:
        from repositories.lot_repo import get_or_create_lot

        session = _make_session(existing_expiry=date(2027, 1, 1))

        with pytest.raises(HTTPException) as exc_info:
            await get_or_create_lot(
                session, TENANT_ID, PRODUCT_ID, "LOT-A1", date(2027, 6, 1), USER_ID
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_EXPIRY_MISMATCH"
        assert exc_info.value.detail["lot_number"] == "LOT-A1"
        assert exc_info.value.detail["existing_expiry"] == "2027-01-01"
        assert exc_info.value.detail["given_expiry"] == "2027-06-01"

    async def test_blank_lot_number_raises_422(self) -> None:
        from repositories.lot_repo import get_or_create_lot

        session = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_or_create_lot(session, TENANT_ID, PRODUCT_ID, "   ", None, USER_ID)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_NUMBER_REQUIRED"
        session.execute.assert_not_awaited()

    async def test_lot_number_is_stripped(self) -> None:
        from repositories.lot_repo import get_or_create_lot

        session = _make_session(existing_expiry=None)

        await get_or_create_lot(session, TENANT_ID, PRODUCT_ID, "  LOT-A1  ", None, USER_ID)

        insert_call = session.execute.call_args_list[0]
        assert insert_call.args[1]["lot"] == "LOT-A1"


@pytest.mark.unit
class TestCreateAutoLot:

    async def test_format_is_yymmdd_seq(self) -> None:
        from repositories.lot_repo import create_auto_lot

        count_result = MagicMock()
        count_result.fetchone.return_value = MagicMock(cnt=0)

        insert_result = MagicMock()
        insert_result.fetchone.return_value = MagicMock(id="new-lot-id")

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[count_result, insert_result])

        lot_id, lot_number = await create_auto_lot(
            session, TENANT_ID, PRODUCT_ID, date(2027, 1, 1), USER_ID
        )

        today_prefix = date.today().strftime("%y%m%d")
        assert lot_id == "new-lot-id"
        assert lot_number == f"{today_prefix}-001"

    async def test_existing_lots_bump_the_sequence(self) -> None:
        from repositories.lot_repo import create_auto_lot

        count_result = MagicMock()
        count_result.fetchone.return_value = MagicMock(cnt=4)

        insert_result = MagicMock()
        insert_result.fetchone.return_value = MagicMock(id="new-lot-id")

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[count_result, insert_result])

        _, lot_number = await create_auto_lot(
            session, TENANT_ID, PRODUCT_ID, None, USER_ID
        )

        today_prefix = date.today().strftime("%y%m%d")
        assert lot_number == f"{today_prefix}-005"

    async def test_conflict_retries_with_next_number(self) -> None:
        from repositories.lot_repo import create_auto_lot

        count_result = MagicMock()
        count_result.fetchone.return_value = MagicMock(cnt=0)

        conflict_result = MagicMock()
        conflict_result.fetchone.return_value = None  # DO NOTHING — no row returned

        insert_result = MagicMock()
        insert_result.fetchone.return_value = MagicMock(id="new-lot-id")

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[count_result, conflict_result, insert_result]
        )

        _, lot_number = await create_auto_lot(
            session, TENANT_ID, PRODUCT_ID, None, USER_ID
        )

        today_prefix = date.today().strftime("%y%m%d")
        assert lot_number == f"{today_prefix}-002"
        assert session.execute.await_count == 3

    async def test_five_conflicts_raise_500(self) -> None:
        from repositories.lot_repo import create_auto_lot

        count_result = MagicMock()
        count_result.fetchone.return_value = MagicMock(cnt=0)

        conflict_result = MagicMock()
        conflict_result.fetchone.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[count_result] + [conflict_result] * 5
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_auto_lot(session, TENANT_ID, PRODUCT_ID, None, USER_ID)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail["code"] == "LOT_NUMBER_GENERATION_FAILED"
        assert session.execute.await_count == 6


@pytest.mark.unit
class TestUpdateLotBalance:

    async def test_positive_delta_upserts(self) -> None:
        from repositories.lot_repo import _update_lot_balance

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())

        await _update_lot_balance(
            session, TENANT_ID, LOT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal("10")
        )

        assert session.execute.await_count == 1
        sql = str(session.execute.call_args.args[0])
        assert "ON CONFLICT" in sql

    async def test_negative_delta_updates_only(self) -> None:
        from repositories.lot_repo import _update_lot_balance

        result = MagicMock()
        result.fetchone.return_value = MagicMock(quantity=Decimal("7"))
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)

        await _update_lot_balance(
            session, TENANT_ID, LOT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal("-3")
        )

        assert session.execute.await_count == 1
        sql = str(session.execute.call_args.args[0]).strip()
        assert sql.startswith("UPDATE")
        assert "INSERT" not in sql

    async def test_negative_delta_no_row_raises_422(self) -> None:
        from repositories.lot_repo import _update_lot_balance

        result = MagicMock()
        result.fetchone.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await _update_lot_balance(
                session, TENANT_ID, LOT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal("-20")
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INSUFFICIENT_LOT_STOCK"
        assert exc_info.value.detail["lot_id"] == LOT_ID
        assert exc_info.value.detail["warehouse_id"] == WAREHOUSE_ID
        assert exc_info.value.detail["available"] == "0"
        assert exc_info.value.detail["requested"] == "20"

    async def test_zero_delta_no_execute(self) -> None:
        from repositories.lot_repo import _update_lot_balance

        session = AsyncMock()

        await _update_lot_balance(
            session, TENANT_ID, LOT_ID, PRODUCT_ID, WAREHOUSE_ID, Decimal("0")
        )

        session.execute.assert_not_awaited()
