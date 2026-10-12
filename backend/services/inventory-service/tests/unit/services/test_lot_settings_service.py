"""Unit tests for services/lot_settings_service.update_lot_settings()."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


TENANT_ID     = "10000000-0000-0000-0000-000000000001"
PRODUCT_ID    = "aaaaaaaa-0000-0000-0000-000000000001"
USER_ID       = "u-ta-001"
WAREHOUSE_ID1 = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_ID2 = "20000000-0000-0000-0000-000000000002"


def _product_row(batch_tracking=False, expiry_tracking=False, dispatch_strategy=None):
    return MagicMock(
        batch_tracking=batch_tracking,
        expiry_tracking=expiry_tracking,
        dispatch_strategy=dispatch_strategy,
    )


def _result(fetchone=None, fetchall=None):
    r = MagicMock()
    r.fetchone.return_value = fetchone
    r.fetchall.return_value = fetchall or []
    return r


@pytest.mark.unit
class TestFeatureFlag:

    async def test_flag_off_raises_403_before_any_query(self) -> None:
        from services.lot_settings_service import update_lot_settings

        session = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await update_lot_settings(
                session,
                tenant_id=TENANT_ID,
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                role="TA",
                feature_enabled=False,
                batch_tracking=True,
                expiry_tracking=False,
                dispatch_strategy=None,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "FEATURE_NOT_ENABLED"
        session.execute.assert_not_awaited()


@pytest.mark.unit
class TestProductNotFound:

    async def test_missing_product_raises_404(self) -> None:
        from services.lot_settings_service import update_lot_settings

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(fetchone=None))

        with pytest.raises(HTTPException) as exc_info:
            await update_lot_settings(
                session,
                tenant_id=TENANT_ID,
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                role="TA",
                feature_enabled=True,
                batch_tracking=True,
                expiry_tracking=False,
                dispatch_strategy=None,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.unit
class TestStrategyValidation:

    async def _run(self, session_execute_side_effect, **kwargs):
        from services.lot_settings_service import update_lot_settings

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=session_execute_side_effect)

        defaults = dict(
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            user_id=USER_ID,
            role="TA",
            feature_enabled=True,
        )
        defaults.update(kwargs)
        return await update_lot_settings(session, **defaults)

    async def test_expiry_without_batch_raises_422(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await self._run(
                [_result(fetchone=_product_row())],
                batch_tracking=False,
                expiry_tracking=True,
                dispatch_strategy=None,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "EXPIRY_NEEDS_BATCH"

    async def test_batch_off_with_strategy_raises_422(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await self._run(
                [_result(fetchone=_product_row())],
                batch_tracking=False,
                expiry_tracking=False,
                dispatch_strategy="FIFO",
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_DISPATCH_STRATEGY"

    async def test_fefo_without_expiry_raises_422(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await self._run(
                [_result(fetchone=_product_row())],
                batch_tracking=True,
                expiry_tracking=False,
                dispatch_strategy="FEFO",
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_DISPATCH_STRATEGY"

    async def test_expiry_forces_fefo(self) -> None:
        execs = [
            _result(fetchone=_product_row()),  # SELECT product
            _result(),                          # UPDATE products
            _result(fetchall=[]),               # SELECT balances (no conversion needed, old=batch already? )
            _result(),                           # INSERT audit_logs
        ]
        # old batch_tracking False -> True triggers conversion query; stub empty balances
        result = await self._run(
            execs,
            batch_tracking=True,
            expiry_tracking=True,
            dispatch_strategy=None,
        )
        assert result.dispatch_strategy == "FEFO"
        assert result.expiry_tracking is True

    async def test_batch_without_expiry_defaults_to_fifo(self) -> None:
        execs = [
            _result(fetchone=_product_row()),
            _result(),
            _result(fetchall=[]),
            _result(),
        ]
        result = await self._run(
            execs,
            batch_tracking=True,
            expiry_tracking=False,
            dispatch_strategy=None,
        )
        assert result.dispatch_strategy == "FIFO"


@pytest.mark.unit
class TestBatchTrackingOff:

    async def test_blocked_while_lot_holds_stock(self) -> None:
        from services.lot_settings_service import update_lot_settings

        execs = [
            _result(fetchone=_product_row(batch_tracking=True, dispatch_strategy="FIFO")),
            _result(fetchone=MagicMock(qty=Decimal("5"))),  # SUM(lot_balances) > 0
        ]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=execs)

        with pytest.raises(HTTPException) as exc_info:
            await update_lot_settings(
                session,
                tenant_id=TENANT_ID,
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                role="TA",
                feature_enabled=True,
                batch_tracking=False,
                expiry_tracking=False,
                dispatch_strategy=None,
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "BATCH_TRACKING_IN_USE"

    async def test_allowed_when_lot_balances_zero(self) -> None:
        from services.lot_settings_service import update_lot_settings

        execs = [
            _result(fetchone=_product_row(batch_tracking=True, dispatch_strategy="FIFO")),
            _result(fetchone=MagicMock(qty=Decimal("0"))),  # SUM(lot_balances) == 0
            _result(),  # UPDATE products
            _result(),  # INSERT audit_logs
        ]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=execs)

        result = await update_lot_settings(
            session,
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            user_id=USER_ID,
            role="TA",
            feature_enabled=True,
            batch_tracking=False,
            expiry_tracking=False,
            dispatch_strategy=None,
        )

        assert result.batch_tracking is False
        assert result.dispatch_strategy is None
        assert result.opening_lots == []


@pytest.mark.unit
class TestConversion:

    async def test_two_warehouses_create_opening_lots(self) -> None:
        from services.lot_settings_service import update_lot_settings

        bal1 = MagicMock(warehouse_id=WAREHOUSE_ID1, warehouse_code="MWH", quantity=Decimal("10"))
        bal2 = MagicMock(warehouse_id=WAREHOUSE_ID2, warehouse_code="SUB1", quantity=Decimal("25"))

        execs = [
            _result(fetchone=_product_row(batch_tracking=False)),  # SELECT product
            _result(),                                              # UPDATE products
            _result(fetchall=[bal1, bal2]),                         # SELECT balances
            _result(),                                              # INSERT audit_logs
        ]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=execs)

        lot_uuid1 = "30000000-0000-0000-0000-000000000001"
        lot_uuid2 = "30000000-0000-0000-0000-000000000002"
        with patch(
            "services.lot_settings_service.create_opening_lot",
            new=AsyncMock(side_effect=[(lot_uuid1, "OPENING-MWH"), (lot_uuid2, "OPENING-SUB1")]),
        ) as mock_create_lot, patch(
            "services.lot_settings_service.record_transaction",
            new=AsyncMock(return_value="tx-id"),
        ) as mock_record_tx, patch(
            "services.lot_settings_service.lot_totals_mismatch",
            new=AsyncMock(return_value=None),
        ):
            result = await update_lot_settings(
                session,
                tenant_id=TENANT_ID,
                product_id=PRODUCT_ID,
                user_id=USER_ID,
                role="TA",
                feature_enabled=True,
                batch_tracking=True,
                expiry_tracking=False,
                dispatch_strategy=None,
            )

        assert mock_create_lot.await_count == 2
        assert mock_record_tx.await_count == 2
        for call in mock_record_tx.await_args_list:
            assert call.args[2] == "LOT_OPENING"
            assert call.kwargs["source"] == "OPENING_BALANCE"
            assert call.kwargs["lot_id"] is not None

        assert len(result.opening_lots) == 2
        quantities = {str(ol.warehouse_id): ol.quantity for ol in result.opening_lots}
        assert quantities[WAREHOUSE_ID1] == Decimal("10")
        assert quantities[WAREHOUSE_ID2] == Decimal("25")

    async def test_mismatch_after_conversion_raises_500(self) -> None:
        from services.lot_settings_service import update_lot_settings

        bal1 = MagicMock(warehouse_id=WAREHOUSE_ID1, warehouse_code="MWH", quantity=Decimal("10"))

        execs = [
            _result(fetchone=_product_row(batch_tracking=False)),
            _result(),
            _result(fetchall=[bal1]),
        ]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=execs)

        with patch(
            "services.lot_settings_service.create_opening_lot",
            new=AsyncMock(return_value=("30000000-0000-0000-0000-000000000001", "OPENING-MWH")),
        ), patch(
            "services.lot_settings_service.record_transaction",
            new=AsyncMock(return_value="tx-id"),
        ), patch(
            "services.lot_settings_service.lot_totals_mismatch",
            new=AsyncMock(return_value=Decimal("3")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_lot_settings(
                    session,
                    tenant_id=TENANT_ID,
                    product_id=PRODUCT_ID,
                    user_id=USER_ID,
                    role="TA",
                    feature_enabled=True,
                    batch_tracking=True,
                    expiry_tracking=False,
                    dispatch_strategy=None,
                )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail["code"] == "LOT_CONVERSION_MISMATCH"
