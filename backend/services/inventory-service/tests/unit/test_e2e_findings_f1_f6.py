"""Regression tests for E2E walkthrough findings F1 and F6 (inventory service).

F1: an unhandled error returned the raw SQLAlchemy/SQL text to the API client.
    The client now gets a generic message; the detail goes to the server log only.
F6: POST /transfers/{id}/receive with `{}` returned 422 "lines required", although
    the router documents "no body = full receipt". An empty body is now a full receipt.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from schemas.inventory import ReceiveTransferRequest

TRANSFER = UUID("cccccccc-0000-0000-0000-000000000001")
TENANT = UUID("aaaaaaaa-0000-0000-0000-000000000001")

LEAKY_SQL = (
    "(sqlalchemy.dialects.postgresql.asyncpg.Error) no partition of relation "
    '"inventory_transactions" found [SQL: INSERT INTO inventory_transactions (id, ...)]'
)


@pytest.mark.unit
class TestF1GlobalHandlerHidesInternals:
    async def test_500_body_is_generic_and_carries_no_sql(self) -> None:
        from main import global_exception_handler

        request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/x/receive/"))
        response = await global_exception_handler(request, RuntimeError(LEAKY_SQL))

        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message"] == "An unexpected error occurred."
        text = response.body.decode()
        assert "INSERT" not in text
        assert "inventory_transactions" not in text
        assert "partition" not in text

    async def test_detail_is_logged_server_side(self) -> None:
        from main import global_exception_handler

        request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/x/receive/"))
        with patch("main.logger") as log:
            await global_exception_handler(request, RuntimeError(LEAKY_SQL))
        log.exception.assert_called_once()
        assert log.exception.call_args.kwargs["exc_info"].args[0] == LEAKY_SQL


@pytest.mark.unit
class TestF6EmptyReceiveBodyIsFullReceipt:
    def test_empty_object_parses_with_no_lines(self) -> None:
        assert ReceiveTransferRequest.model_validate({}).lines is None

    def test_explicit_empty_line_list_is_still_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReceiveTransferRequest.model_validate({"lines": []})

    async def test_router_turns_empty_body_into_full_receipt(self) -> None:
        from routers.transfer import receive_transfer
        from shared.permissions.middleware import PermissionResult

        user = SimpleNamespace(tenant_id=TENANT, user_id="u-wm", role="WM", role_code="WM")
        with (
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
            patch("routers.transfer.InventoryService") as svc_cls,
        ):
            svc = svc_cls.return_value
            svc.receive_transfer = AsyncMock(return_value=MagicMock())
            svc.read_transfer_after_write = AsyncMock(return_value=MagicMock(name="readback"))
            await receive_transfer(
                transfer_id=TRANSFER,
                body=ReceiveTransferRequest.model_validate({}),
                user=user,
                db=AsyncMock(),
            )

        svc.receive_transfer.assert_awaited_once_with(user, TRANSFER, None)
