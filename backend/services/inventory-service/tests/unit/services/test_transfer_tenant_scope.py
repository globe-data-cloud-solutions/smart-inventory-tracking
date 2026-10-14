"""Transfer lookups by id are tenant-filtered.

A transfer that belongs to another tenant answers 404 "Transfer not found",
exactly as a missing id does — get_transfer and transition_transfer alike.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException

TENANT_A    = "10000000-0000-0000-0000-00000000000a"
TENANT_B    = "10000000-0000-0000-0000-00000000000b"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"
TRANSFER_ID = UUID("cccccccc-0000-0000-0000-000000000001")


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


def _transfer_row(tenant_id: str = TENANT_A) -> MagicMock:
    row = MagicMock()
    row.id                = TRANSFER_ID
    row.tenant_id         = tenant_id
    row.transfer_type     = "PULL"
    row.status            = "DRAFT"
    row.from_warehouse_id = WAREHOUSE_A
    row.to_warehouse_id   = WAREHOUSE_B
    row.is_self_approved  = False
    return row


def _db(row: MagicMock) -> AsyncMock:
    """A session holding one transfer that behaves like the table: a lookup by
    id finds it, and a tenant_id = :tid filter drops it for any other tenant.
    (Without the filter the row comes back — the bug these tests pin.)"""

    async def execute(stmt: Any, params: dict | None = None) -> MagicMock:
        sql, params = str(stmt), params or {}
        if "FROM transfer_orders WHERE id = :id" in sql:
            found = params.get("id") == str(row.id) and (
                "tenant_id = :tid" not in sql or params.get("tid") == str(row.tenant_id)
            )
            return MagicMock(fetchone=MagicMock(return_value=row if found else None))
        raise AssertionError(f"unexpected query: {sql}")

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute)
    return session


OTHER_TENANT_TA = _User("u-ta-b", TENANT_B, None, None, "TA")


@pytest.mark.unit
class TestTransferLookupTenantFilter:

    async def test_get_transfer_other_tenant_is_404(self) -> None:
        from services.inventory_service import InventoryService

        with pytest.raises(HTTPException) as exc:
            await InventoryService(_db(_transfer_row())).get_transfer(OTHER_TENANT_TA, TRANSFER_ID)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Transfer not found"

    async def test_transition_transfer_other_tenant_is_404(self) -> None:
        from services.inventory_service import InventoryService

        with pytest.raises(HTTPException) as exc:
            await InventoryService(_db(_transfer_row())).transition_transfer(
                OTHER_TENANT_TA, TRANSFER_ID, "PENDING_REVIEW",
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Transfer not found"

    async def test_missing_id_gives_the_same_404(self) -> None:
        """Same tenant, different id — indistinguishable from the cross-tenant case."""
        from services.inventory_service import InventoryService

        same_tenant_ta = _User("u-ta-a", TENANT_A, None, None, "TA")
        with pytest.raises(HTTPException) as exc:
            await InventoryService(_db(_transfer_row())).get_transfer(
                same_tenant_ta, UUID("cccccccc-0000-0000-0000-0000000000ff"),
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Transfer not found"
