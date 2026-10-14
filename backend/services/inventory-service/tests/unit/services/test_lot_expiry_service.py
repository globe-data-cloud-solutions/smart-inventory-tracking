"""Unit tests for services/lot_expiry_service.set_lot_expiry().

session.execute is mocked and calls are classified by their SQL text, so the
tests can assert exactly which writes were (not) issued.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.lot_expiry_service import set_lot_expiry

TENANT_ID = "10000000-0000-0000-0000-000000000001"
LOT_ID = "30000000-0000-0000-0000-000000000001"
PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001"


def _lot(expiry_date=None, batch_tracking=True, expiry_tracking=True):
    return MagicMock(
        id=LOT_ID,
        lot_number="OPENING-MWH",
        product_id=PRODUCT_ID,
        expiry_date=expiry_date,
        batch_tracking=batch_tracking,
        expiry_tracking=expiry_tracking,
    )


def _result(row):
    r = MagicMock()
    r.fetchone.return_value = row
    return r


def _session(select_rows, update_row=None):
    """select_rows: successive results for the lot SELECTs; update_row: UPDATE result."""
    selects = iter(select_rows)

    async def _execute(stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().startswith("UPDATE"):
            return _result(update_row)
        if sql.lstrip().startswith("INSERT INTO audit_logs"):
            return _result(None)
        return _result(next(selects))

    s = MagicMock()
    s.execute = AsyncMock(side_effect=_execute)
    return s


def _sqls(session, prefix):
    return [c for c in session.execute.call_args_list if str(c.args[0]).lstrip().startswith(prefix)]


def _user():
    return MagicMock(user_id="u-ta", role="TA", tenant_id=TENANT_ID)


def _updated(exp):
    return MagicMock(id=LOT_ID, lot_number="OPENING-MWH", product_id=PRODUCT_ID, expiry_date=exp)


@pytest.mark.unit
class TestSetLotExpiry:

    async def test_success(self) -> None:
        exp = date.today() + timedelta(days=10)
        s = _session([_lot()], update_row=_updated(exp))
        out = await set_lot_expiry(s, TENANT_ID, LOT_ID, exp, _user())
        assert out == {
            "lot_id": LOT_ID, "lot_number": "OPENING-MWH",
            "product_id": PRODUCT_ID, "expiry_date": exp,
        }
        assert len(_sqls(s, "UPDATE")) == 1
        audits = _sqls(s, "INSERT INTO audit_logs")
        assert len(audits) == 1
        assert exp.isoformat() in audits[0].args[1]["ctx"]

    async def test_today_is_accepted(self) -> None:
        today = date.today()
        s = _session([_lot()], update_row=_updated(today))
        out = await set_lot_expiry(s, TENANT_ID, LOT_ID, today, _user())
        assert out["expiry_date"] == today

    async def test_lot_not_found(self) -> None:
        s = _session([None])
        with pytest.raises(HTTPException) as ei:
            await set_lot_expiry(s, TENANT_ID, LOT_ID, date.today(), _user())
        assert ei.value.status_code == 404
        assert ei.value.detail == {"code": "LOT_NOT_FOUND"}
        assert not _sqls(s, "UPDATE")

    async def test_expiry_tracking_off(self) -> None:
        s = _session([_lot(expiry_tracking=False)])
        with pytest.raises(HTTPException) as ei:
            await set_lot_expiry(s, TENANT_ID, LOT_ID, date.today(), _user())
        assert ei.value.status_code == 422
        assert ei.value.detail["code"] == "EXPIRY_TRACKING_OFF"
        assert ei.value.detail["lot_number"] == "OPENING-MWH"
        assert not _sqls(s, "UPDATE")

    async def test_already_set(self) -> None:
        existing = date.today() + timedelta(days=5)
        s = _session([_lot(expiry_date=existing)])
        with pytest.raises(HTTPException) as ei:
            await set_lot_expiry(s, TENANT_ID, LOT_ID, date.today(), _user())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "LOT_EXPIRY_ALREADY_SET"
        assert ei.value.detail["existing_expiry"] == existing.isoformat()
        assert not _sqls(s, "UPDATE")

    async def test_past_date(self) -> None:
        s = _session([_lot()])
        with pytest.raises(HTTPException) as ei:
            await set_lot_expiry(s, TENANT_ID, LOT_ID, date.today() - timedelta(days=1), _user())
        assert ei.value.status_code == 422
        assert ei.value.detail == {"code": "EXPIRY_IN_PAST"}
        assert not _sqls(s, "UPDATE")

    async def test_race_update_matches_zero_rows(self) -> None:
        winner = date.today() + timedelta(days=3)
        s = _session([_lot(), _lot(expiry_date=winner)], update_row=None)
        with pytest.raises(HTTPException) as ei:
            await set_lot_expiry(s, TENANT_ID, LOT_ID, date.today() + timedelta(days=9), _user())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "LOT_EXPIRY_ALREADY_SET"
        assert ei.value.detail["existing_expiry"] == winner.isoformat()
        assert len(_sqls(s, "UPDATE")) == 1
        assert not _sqls(s, "INSERT INTO audit_logs")
