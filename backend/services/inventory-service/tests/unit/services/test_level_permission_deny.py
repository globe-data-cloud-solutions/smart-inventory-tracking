"""Deny-by-default for transfer-type level permissions.

A level with no transfer_type_level_permissions row must refuse the transfer
(LEVEL_NOT_CONFIGURED), not pass silently. Missing rows used to skip the check.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

TENANT_ID = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"
PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CONFIG_UUID = "eeeeeeee-0000-0000-0000-000000000001"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


def _fetch(value):
    return MagicMock(fetchone=MagicMock(return_value=value))


def _session(init_perm, dst_perm, init_level: int, dst_level: int):
    """Positional mock sequence in the order create_transfer issues its queries:
    from/to active, factory check, config, initiator node, initiator perm,
    destination node, destination perm."""
    config_row = MagicMock(id=UUID(CONFIG_UUID))
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _fetch(MagicMock(is_active=True)),  # from active
            _fetch(MagicMock(is_active=True)),  # to active
            _fetch(None),  # factory check
            _fetch(config_row),  # config lookup
            _fetch(MagicMock(hierarchy_level=init_level)),  # initiator node
            _fetch(init_perm),  # initiator permission row
            _fetch(MagicMock(hierarchy_level=dst_level)),  # destination node
            _fetch(dst_perm),  # destination permission row
        ]
    )
    return session


def _request(transfer_type: str):
    from schemas.inventory import TransferLineRequest, TransferOrderRequest

    return TransferOrderRequest(
        transfer_type=transfer_type,
        from_warehouse_id=UUID(WAREHOUSE_A),
        to_warehouse_id=UUID(WAREHOUSE_B),
        lines=[TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal(50))],
    )


@pytest.mark.unit
class TestMissingLevelRowIsDenied:
    async def test_pull_initiator_row_missing_is_refused(self) -> None:
        from fastapi import HTTPException

        from services.inventory_service import InventoryService

        session = _session(init_perm=None, dst_perm=None, init_level=3, dst_level=2)
        user = _User("u-wm", TENANT_ID, WAREHOUSE_B, None, "WM")

        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).create_transfer(user, _request("PULL"))

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_NOT_CONFIGURED"
        assert exc_info.value.detail["level_number"] == 3
        assert exc_info.value.detail["transfer_type"] == "PULL"

    async def test_push_destination_row_missing_is_refused(self) -> None:
        """PUSH: the initiator (source) row allows, the destination level has no row."""
        from fastapi import HTTPException

        from services.inventory_service import InventoryService

        init_perm = MagicMock(can_initiate=True)
        session = _session(init_perm=init_perm, dst_perm=None, init_level=1, dst_level=2)
        user = _User("u-nm", TENANT_ID, WAREHOUSE_A, None, "NM")

        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).create_transfer(user, _request("PUSH"))

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_NOT_CONFIGURED"
        assert exc_info.value.detail["level_number"] == 2
        assert exc_info.value.detail["transfer_type"] == "PUSH"

    async def test_sister_row_missing_is_refused(self) -> None:
        from fastapi import HTTPException

        from services.inventory_service import InventoryService

        session = _session(init_perm=None, dst_perm=None, init_level=4, dst_level=4)
        user = _User("u-wm", TENANT_ID, WAREHOUSE_B, None, "WM")

        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).create_transfer(user, _request("SISTER"))

        assert exc_info.value.detail["code"] == "LEVEL_NOT_CONFIGURED"
        assert exc_info.value.detail["transfer_type"] == "SISTER"
