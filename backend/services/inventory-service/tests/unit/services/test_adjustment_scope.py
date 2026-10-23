"""RB-2: adjustments follow the node scope used by transfers.

A reviewer acts on an adjustment only inside its node scope, or when it is the
named override approver. Scope comes from InventoryService._transfer_scope, so
the rule is the same one transfers already use.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.inventory_service import InventoryService

WH_IN = "aaaaaaaa-0000-0000-0000-000000000001"
WH_OUT = "bbbbbbbb-0000-0000-0000-000000000002"
ME = "cccccccc-0000-0000-0000-000000000003"
OTHER = "dddddddd-0000-0000-0000-000000000004"


def _svc(scope):
    svc = InventoryService.__new__(InventoryService)
    svc._transfer_scope = AsyncMock(return_value=scope)
    return svc


def _user(role="RM"):
    return SimpleNamespace(role=role, user_id=ME, tenant_id="t-1", warehouse_id=None)


def _row(warehouse_id, approver=None):
    return SimpleNamespace(warehouse_id=warehouse_id, required_approver_user_id=approver)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_warehouse_inside_region_is_in_scope():
    svc = _svc({WH_IN})
    assert await svc._adjustment_in_scope(_user(), _row(WH_IN.upper())) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_warehouse_outside_region_is_out_of_scope():
    svc = _svc({WH_IN})
    assert await svc._adjustment_in_scope(_user(), _row(WH_OUT)) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_scope_fails_closed():
    svc = _svc(set())
    assert await svc._adjustment_in_scope(_user(), _row(WH_IN)) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_wide_role_sees_every_warehouse():
    svc = _svc(None)
    assert await svc._adjustment_in_scope(_user("TA"), _row(WH_OUT)) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_named_override_approver_may_act_outside_region():
    svc = _svc({WH_IN})
    assert await svc._adjustment_in_scope(_user(), _row(WH_OUT, approver=ME)) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_other_named_approver_does_not_bypass_scope():
    svc = _svc({WH_IN})
    assert await svc._adjustment_in_scope(_user(), _row(WH_OUT, approver=OTHER)) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discrepancy_list_adds_named_approver_clause_for_facility_role():
    """RB-2: a facility-scoped reviewer's discrepancy query also matches transfers
    whose approval steps name them, not just transfers in the subtree."""
    from unittest.mock import MagicMock, patch

    from services import transfer_discrepancies as td

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
    user = SimpleNamespace(role="RM", user_id=ME, tenant_id="t-1", warehouse_id=WH_IN)

    with patch.object(td, "_subtree", AsyncMock(return_value={WH_IN.lower()})):
        await td.list_discrepancies(db, user)

    sql_arg, params = db.execute.call_args.args[0], db.execute.call_args.args[1]
    assert "resolved_approval_steps" in str(sql_arg)
    assert params["uid"] == ME.lower()
    assert params["step_nodes"] == [WH_IN.lower()]
