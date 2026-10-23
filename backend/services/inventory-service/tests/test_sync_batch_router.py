"""Router tests for POST /api/v1/inventory/sync/batch (RB-10).

Each item must reach the SAME service method the online screens use, and each
outcome must map to the right status: SYNCED, CONFLICT or ERROR. A duplicate
(already posted) is SYNCED, never CONFLICT, so a lost response cannot make the
device show a movement as failed when the stock already moved.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from dependencies import get_current_user, get_db_session

URL = "/api/v1/inventory/sync/batch"
PRODUCT_ID = str(uuid.uuid4())
WAREHOUSE_ID = str(uuid.uuid4())


class _Savepoint:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _grant() -> MagicMock:
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _receive_item(key: str = "receive:k1") -> dict:
    return {
        "idempotency_key": key,
        "action": "inventory:receive",
        "payload": {
            "product_id": PRODUCT_ID,
            "warehouse_id": WAREHOUSE_ID,
            "reference_type": "PURCHASE_ORDER",
            "quantity": "5.0000",
        },
    }


def _issue_item(key: str = "issue:k1") -> dict:
    return {
        "idempotency_key": key,
        "action": "inventory:issue",
        "payload": {
            "product_id": PRODUCT_ID,
            "warehouse_id": WAREHOUSE_ID,
            "quantity": "2.0000",
            "reason_code": "SALE",
        },
    }


@pytest.fixture
def svc():
    """Patched InventoryService whose methods succeed unless a test overrides them."""
    service = MagicMock()
    service.receive = AsyncMock(return_value=SimpleNamespace())
    service.issue_stock = AsyncMock(return_value=SimpleNamespace())
    return service


@pytest.fixture
async def client(inv_app, wm_user, svc):
    db = MagicMock()
    db.begin_nested = MagicMock(return_value=_Savepoint())

    async def _db_gen():
        yield db

    inv_app.dependency_overrides[get_current_user] = lambda: wm_user
    inv_app.dependency_overrides[get_db_session] = _db_gen
    try:
        with (
            patch(
                "shared.permissions.middleware.get_role_permission",
                new=AsyncMock(return_value=_grant()),
            ),
            patch("shared.permissions.middleware.audit_log", new=AsyncMock()),
            patch("routers.sync.InventoryService", return_value=svc),
            patch(
                "routers.sync.check_permission",
                new=AsyncMock(return_value=SimpleNamespace(allowed=True)),
            ) as perm,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=inv_app), base_url="http://test"
            ) as ac:
                ac.perm_mock = perm  # type: ignore[attr-defined]
                yield ac
    finally:
        inv_app.dependency_overrides.clear()


def _results(resp) -> dict[str, dict]:
    assert resp.status_code == 200, resp.text
    return {r["idempotency_key"]: r for r in resp.json()["data"]}


@pytest.mark.unit
class TestSyncBatchPosting:
    async def test_receive_posts_through_service_with_queue_key(self, client, svc) -> None:
        resp = await client.post(URL, json={"items": [_receive_item("receive:k1")]})
        res = _results(resp)
        assert res["receive:k1"]["status"] == "SYNCED"
        svc.receive.assert_awaited_once()
        sent = svc.receive.await_args.args[1]
        assert str(sent.idempotency_key) == "receive:k1"
        assert str(sent.product_id) == PRODUCT_ID

    async def test_issue_posts_through_issue_stock(self, client, svc) -> None:
        resp = await client.post(URL, json={"items": [_issue_item("issue:k1")]})
        assert _results(resp)["issue:k1"]["status"] == "SYNCED"
        svc.issue_stock.assert_awaited_once()
        assert svc.issue_stock.await_args.args[1].reason_code == "SALE"

    async def test_queue_key_overrides_payload_key(self, client, svc) -> None:
        item = _receive_item("receive:queue-key")
        item["payload"]["idempotency_key"] = "some-other-key"
        await client.post(URL, json={"items": [item]})
        assert str(svc.receive.await_args.args[1].idempotency_key) == "receive:queue-key"

    async def test_mixed_batch_returns_one_result_per_item(self, client, svc) -> None:
        resp = await client.post(URL, json={"items": [_receive_item("a"), _issue_item("b")]})
        res = _results(resp)
        assert set(res) == {"a", "b"}
        assert res["a"]["status"] == res["b"]["status"] == "SYNCED"


@pytest.mark.unit
class TestSyncBatchOutcomes:
    async def test_duplicate_receive_is_synced_not_conflict(self, client, svc) -> None:
        svc.receive.side_effect = HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_TRANSACTION", "idempotency_key": "receive:k1"},
        )
        res = _results(await client.post(URL, json={"items": [_receive_item("receive:k1")]}))
        assert res["receive:k1"]["status"] == "SYNCED"

    async def test_business_rule_rejection_is_conflict_with_code(self, client, svc) -> None:
        svc.issue_stock.side_effect = HTTPException(
            status_code=422, detail={"code": "INSUFFICIENT_STOCK"}
        )
        res = _results(await client.post(URL, json={"items": [_issue_item("issue:k1")]}))
        assert res["issue:k1"] == {
            "idempotency_key": "issue:k1",
            "status": "CONFLICT",
            "code": "INSUFFICIENT_STOCK",
            "detail": "",
        }

    async def test_server_error_is_error_and_batch_continues(self, client, svc) -> None:
        svc.receive.side_effect = RuntimeError("db down")
        resp = await client.post(URL, json={"items": [_receive_item("a"), _issue_item("b")]})
        res = _results(resp)
        assert res["a"]["status"] == "ERROR"
        assert res["a"]["code"] == "SERVER_ERROR"
        assert res["b"]["status"] == "SYNCED"

    async def test_unknown_action_is_error_and_never_posts(self, client, svc) -> None:
        item = {"idempotency_key": "x", "action": "inventory:transfer", "payload": {}}
        res = _results(await client.post(URL, json={"items": [item]}))
        assert res["x"]["status"] == "ERROR"
        assert res["x"]["code"] == "UNKNOWN_ACTION"
        svc.receive.assert_not_awaited()
        svc.issue_stock.assert_not_awaited()

    async def test_invalid_payload_is_error_and_never_posts(self, client, svc) -> None:
        item = _receive_item("bad")
        del item["payload"]["product_id"]
        res = _results(await client.post(URL, json={"items": [item]}))
        assert res["bad"]["status"] == "ERROR"
        assert res["bad"]["code"] == "INVALID_PAYLOAD"
        svc.receive.assert_not_awaited()

    async def test_no_permission_is_conflict_and_never_posts(self, client, svc) -> None:
        client.perm_mock.return_value = SimpleNamespace(allowed=False)
        res = _results(await client.post(URL, json={"items": [_issue_item("issue:k1")]}))
        assert res["issue:k1"]["status"] == "CONFLICT"
        assert res["issue:k1"]["code"] == "FORBIDDEN"
        svc.issue_stock.assert_not_awaited()


@pytest.mark.unit
class TestSyncBatchLimits:
    async def test_batch_over_200_items_is_rejected(self, client, svc) -> None:
        items = [_receive_item(f"k{i}") for i in range(201)]
        resp = await client.post(URL, json={"items": items})
        assert resp.status_code == 422
        svc.receive.assert_not_awaited()
