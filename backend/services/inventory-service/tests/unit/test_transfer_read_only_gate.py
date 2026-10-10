"""READ_ONLY gate on PATCH /transfers/{transfer_id} (transition_transfer).

This route is decorated with read_only_force_write=True — dispatch/receive
transitions write the ledger even though the action id is transfer:view (a
nominally read permission) — so it must be blocked in READ_ONLY regardless
of the action id's own classification.
"""
from __future__ import annotations
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from routers.transfer import transition_transfer
from schemas.inventory import TransferTransitionRequest
from shared.permissions.middleware import PermissionResult


def _user(tenant_id: str = "tenant-1") -> MagicMock:
    u = MagicMock()
    u.role, u.tenant_id = "WM", tenant_id
    u.warehouse_id, u.region_id = None, None
    return u


def _stage(stage: str) -> dict:
    return {"stage": stage, "contract_end": None, "read_only_since": None}


async def test_read_only_blocks_transition_and_service_not_called() -> None:
    db = AsyncMock()
    body = TransferTransitionRequest(next_status="ISSUED")

    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ), patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        AsyncMock(return_value=_stage("READ_ONLY")),
    ), patch("routers.transfer.InventoryService") as mock_svc_cls:
        with pytest.raises(HTTPException) as exc_info:
            await transition_transfer(transfer_id=uuid4(), body=body, user=_user(), db=db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "CONTRACT_EXPIRED_READ_ONLY"
    mock_svc_cls.assert_not_called()


async def test_grace_tenant_allowed_through_to_service() -> None:
    db = AsyncMock()
    body = TransferTransitionRequest(next_status="RECEIVED")

    with patch(
        "shared.permissions.middleware.check_permission",
        AsyncMock(return_value=PermissionResult(allowed=True)),
    ), patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        AsyncMock(return_value=_stage("GRACE")),
    ), patch("routers.transfer.InventoryService") as mock_svc_cls:
        mock_svc = mock_svc_cls.return_value
        mock_svc.receive_transfer = AsyncMock(return_value=MagicMock())
        await transition_transfer(transfer_id=uuid4(), body=body, user=_user(), db=db)

    mock_svc_cls.assert_called_once_with(db)
