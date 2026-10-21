"""Unit tests for InventoryService.receive() — lot-aware receive logic.

Covers the branching added for batch/expiry-tracked products: non-batch
pass-through, lot input validation (LOT_NOT_TRACKED / LOT_NUMBER_REQUIRED /
LOT_INPUT_CONFLICT), expiry validation (EXPIRY_REQUIRED / EXPIRY_IN_PAST),
manual vs. auto lot resolution, and the source allow-list (INVALID_SOURCE).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from schemas.inventory import ReceiveStockRequest
from services.inventory_service import InventoryService


TENANT_ID = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"
PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TX_ID = "bbbbbbbb-0000-0000-0000-000000000001"
LOT_ID = "cccccccc-0000-0000-0000-000000000001"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str
    role: str


WM = _User("u-wm-001", TENANT_ID, WAREHOUSE_ID, "WM")


def _product_row(batch_tracking: bool, expiry_tracking: bool) -> MagicMock:
    return MagicMock(batch_tracking=batch_tracking, expiry_tracking=expiry_tracking)


def _db_with_product(row) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row)))
    return db


def _body(**kwargs) -> ReceiveStockRequest:
    defaults = dict(
        product_id=UUID(PRODUCT_ID),
        warehouse_id=UUID(WAREHOUSE_ID),
        quantity=Decimal("10"),
        idempotency_key="receive:test:001",
    )
    defaults.update(kwargs)
    return ReceiveStockRequest(**defaults)


@pytest.mark.unit
class TestReceiveNonBatch:
    async def test_plain_non_batch_receive(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=False, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body()

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.receive(WM, body)

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] is None
        assert kwargs["lot_number"] is None
        assert kwargs["source"] == "WEB"
        assert result.transaction_id == UUID(TX_ID)
        assert result.source == "WEB"

    async def test_non_batch_with_lot_number_raises_lot_not_tracked(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=False, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body(lot_number="LOT-A1")

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_NOT_TRACKED"

    async def test_non_batch_with_auto_lot_raises_lot_not_tracked(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=False, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body(auto_lot=True)

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_NOT_TRACKED"


@pytest.mark.unit
class TestReceiveBatchValidation:
    async def test_batch_with_no_lot_input_raises_lot_number_required(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=True, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body()

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_NUMBER_REQUIRED"

    async def test_lot_number_and_auto_lot_together_raises_lot_input_conflict(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=True, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body(lot_number="LOT-A1", auto_lot=True)

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LOT_INPUT_CONFLICT"

    async def test_expiry_tracking_with_no_expiry_raises_expiry_required(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=True, expiry_tracking=True))
        svc = InventoryService(db)
        body = _body(lot_number="LOT-A1")

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "EXPIRY_REQUIRED"

    async def test_past_expiry_raises_expiry_in_past(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=True, expiry_tracking=True))
        svc = InventoryService(db)
        body = _body(lot_number="LOT-A1", expiry_date=date.today() - timedelta(days=1))

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "EXPIRY_IN_PAST"


@pytest.mark.unit
class TestReceiveLotResolution:
    async def test_manual_lot_passes_lot_id_to_record_transaction(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=True, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body(lot_number="LOT-A1")

        with (
            patch(
                "services.inventory_service.get_or_create_lot",
                new_callable=AsyncMock,
                return_value=LOT_ID,
            ) as mock_get_or_create,
            patch(
                "services.inventory_service.record_transaction",
                new_callable=AsyncMock,
                return_value=TX_ID,
            ) as mock_record,
        ):
            result = await svc.receive(WM, body)

        mock_get_or_create.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["lot_id"] == LOT_ID
        assert kwargs["lot_number"] == "LOT-A1"
        assert result.lot_id == UUID(LOT_ID)

    async def test_auto_lot_returns_generated_lot_number(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=True, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body(auto_lot=True)

        generated_number = f"{date.today().strftime('%y%m%d')}-001"

        with (
            patch(
                "services.inventory_service.create_auto_lot",
                new_callable=AsyncMock,
                return_value=(LOT_ID, generated_number),
            ) as mock_auto,
            patch(
                "services.inventory_service.record_transaction",
                new_callable=AsyncMock,
                return_value=TX_ID,
            ),
        ):
            result = await svc.receive(WM, body)

        mock_auto.assert_awaited_once()
        assert result.lot_number == generated_number
        assert result.lot_id == UUID(LOT_ID)


@pytest.mark.unit
class TestReceiveSource:
    async def test_opening_balance_source_passed_through(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=False, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body(source="OPENING_BALANCE")

        with patch(
            "services.inventory_service.record_transaction",
            new_callable=AsyncMock,
            return_value=TX_ID,
        ) as mock_record:
            result = await svc.receive(WM, body)

        _, kwargs = mock_record.call_args
        assert kwargs["source"] == "OPENING_BALANCE"
        assert result.source == "OPENING_BALANCE"

    async def test_invalid_source_raises_422(self) -> None:
        db = _db_with_product(_product_row(batch_tracking=False, expiry_tracking=False))
        svc = InventoryService(db)
        body = _body()
        body.source = "ERP_IMPORT"  # bypass schema; service layer must still reject it

        with pytest.raises(HTTPException) as exc_info:
            await svc.receive(WM, body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_SOURCE"
