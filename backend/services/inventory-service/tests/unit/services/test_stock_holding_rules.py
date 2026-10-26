"""Stock-holding, own-node and SISTER rules (Alex, 2026-10-26).

- Approval-only nodes (is_stock_holding = false) never hold stock: they cannot
  be the source or destination of a transfer, receive goods, or be adjusted.
- Stock at a node is at the disposal of that node's holder only: goods receipt
  and issue need the caller's own node (TA/SA excepted), 403 NOT_YOUR_NODE.
- SISTER is a lateral transfer between nodes at the same level that are not
  under each other (e.g. Factory A -> Factory B); different levels are refused.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

pytestmark = pytest.mark.unit

TENANT = "aaaaaaaa-0000-0000-0000-000000000001"
NODE_A = UUID("bbbbbbbb-0000-0000-0000-00000000000a")
NODE_B = UUID("bbbbbbbb-0000-0000-0000-00000000000b")
PRODUCT = UUID("cccccccc-0000-0000-0000-000000000001")


class _Reached(Exception):
    """Raised by the fake DB once the node checks have passed."""


def _user(role: str = "WM") -> SimpleNamespace:
    return SimpleNamespace(user_id="u-1", tenant_id=TENANT, role=role, warehouse_id=str(NODE_B))


def _node(*, active: bool = True, stock: bool = True, level: int = 1) -> SimpleNamespace:
    return SimpleNamespace(is_active=active, is_stock_holding=stock, hierarchy_level=level)


def _db(*rows: object) -> AsyncMock:
    """Answer the from/to node lookups, then stop the flow with _Reached."""
    queue = list(rows)

    async def _execute(stmt, params=None):
        if not queue:
            raise _Reached
        return MagicMock(fetchone=MagicMock(return_value=queue.pop(0)))

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _transfer(transfer_type: str):
    from schemas.inventory import TransferOrderRequest

    return TransferOrderRequest(
        transfer_type=transfer_type,
        from_warehouse_id=NODE_A,
        to_warehouse_id=NODE_B,
        lines=[{"product_id": PRODUCT, "quantity": 5}],
    )


async def _create_error(db: AsyncMock, transfer_type: str) -> HTTPException:
    from services.inventory_service import InventoryService

    with pytest.raises(HTTPException) as exc_info:
        await InventoryService(db).create_transfer(_user(), _transfer(transfer_type))
    return exc_info.value


@pytest.mark.parametrize(
    ("from_stock", "to_stock", "side"),
    [(False, True, "from"), (True, False, "to")],
)
async def test_transfer_with_an_approval_only_node_is_refused(
    from_stock: bool, to_stock: bool, side: str
) -> None:
    db = _db(_node(stock=from_stock), _node(stock=to_stock))
    err = await _create_error(db, "PUSH")
    assert err.status_code == 422
    assert err.detail["code"] == "NODE_NOT_STOCK_HOLDING"
    assert err.detail["side"] == side


async def test_sister_across_levels_is_refused() -> None:
    db = _db(_node(level=1), _node(level=2))
    err = await _create_error(db, "SISTER")
    assert err.status_code == 422
    assert err.detail["code"] == "SISTER_LEVEL_MISMATCH"
    assert (err.detail["from_level"], err.detail["to_level"]) == (1, 2)


async def test_sister_between_same_level_nodes_passes_the_node_checks() -> None:
    """Factory A -> Factory B, both level 1, in different branches."""
    from services.inventory_service import InventoryService

    db = _db(_node(level=1), _node(level=1))
    with pytest.raises(_Reached):
        await InventoryService(db).create_transfer(_user(), _transfer("SISTER"))


async def test_pull_across_levels_is_not_affected_by_the_sister_rule() -> None:
    from services.inventory_service import InventoryService

    db = _db(_node(level=1), _node(level=2))
    with pytest.raises(_Reached):
        await InventoryService(db).create_transfer(_user(), _transfer("PULL"))


async def test_goods_receipt_at_an_approval_only_node_is_refused() -> None:
    from schemas.inventory import ALLOWED_RECEIVE_SOURCES
    from services.inventory_service import InventoryService

    product = SimpleNamespace(batch_tracking=False, expiry_tracking=False, node_stock_holding=False)
    db = _db(product)
    body = SimpleNamespace(
        source=min(ALLOWED_RECEIVE_SOURCES),
        product_id=PRODUCT,
        warehouse_id=NODE_B,  # the caller's own node
    )
    with pytest.raises(HTTPException) as exc_info:
        await InventoryService(db).receive(_user(), body)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {"code": "NODE_NOT_STOCK_HOLDING", "side": "receive"}


async def test_adjustment_at_an_approval_only_node_is_refused() -> None:
    from services.inventory_service import InventoryService

    db = _db(SimpleNamespace(stock_holding=False))
    with pytest.raises(HTTPException) as exc_info:
        await InventoryService(db)._validate_adjustment_warehouse(
            _user(), SimpleNamespace(warehouse_id=NODE_A)
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {"code": "NODE_NOT_STOCK_HOLDING", "side": "adjustment"}


async def test_adjustment_at_a_stock_holding_node_passes() -> None:
    from services.inventory_service import InventoryService

    db = _db(SimpleNamespace(stock_holding=True))
    await InventoryService(db)._validate_adjustment_warehouse(
        _user(), SimpleNamespace(warehouse_id=NODE_A)
    )


@pytest.mark.parametrize("role", ["NM", "WM", "RM"])
async def test_goods_receipt_at_another_node_is_refused(role: str) -> None:
    """The node comes from the request body, so the permission layer cannot
    check it; the service does. An NM is no exception."""
    from services.inventory_service import InventoryService

    db = _db()
    body = SimpleNamespace(source="PURCHASE", product_id=PRODUCT, warehouse_id=NODE_A)
    with pytest.raises(HTTPException) as exc_info:
        await InventoryService(db).receive(_user(role), body)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "NOT_YOUR_NODE"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("role", ["NM", "WM"])
async def test_issue_at_another_node_is_refused(role: str) -> None:
    from services.inventory_service import InventoryService

    db = _db()
    body = SimpleNamespace(product_id=PRODUCT, warehouse_id=NODE_A, quantity=5)
    with pytest.raises(HTTPException) as exc_info:
        await InventoryService(db).issue_stock(_user(role), body)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "NOT_YOUR_NODE",
        "action": "issue",
        "message": "Stock can only be handled at your own location.",
    }
    db.execute.assert_not_awaited()


def test_own_node_check_ignores_uuid_case_and_lets_ta_through() -> None:
    from services.inventory_service import _require_own_node

    user = SimpleNamespace(role="WM", warehouse_id=str(NODE_A).upper())
    _require_own_node(user, NODE_A, "issue")  # same node, different case
    _require_own_node(SimpleNamespace(role="TA", warehouse_id=None), NODE_A, "issue")
    _require_own_node(SimpleNamespace(role="SA", warehouse_id=None), NODE_B, "receive")
