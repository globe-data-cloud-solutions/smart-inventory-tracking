"""Regression tests for RB-1 sweep HOLE 6 (docs/reviews/2026-10-19-rb1-sweep.md):
create_transfer_request() resolved product/warehouse names from request-body
ids without checking tenant ownership, and stored the unvalidated ids as FKs
regardless. Fixed on fix/rb1-holes: each id is now validated against the
caller's tenant before insert.
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_INV_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _INV_ROOT not in sys.path:
    sys.path.insert(0, _INV_ROOT)

pytestmark = pytest.mark.asyncio

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
REQ_WH = "20000000-0000-0000-0000-000000000001"
SRC_WH_OTHER_TENANT = "30000000-0000-0000-0000-000000000002"
PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000099"

_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


def _user() -> MagicMock:
    u = MagicMock()
    u.role, u.tenant_id, u.user_id = "WM", TENANT_A, "u-wm-1"
    return u


def _body(**overrides) -> MagicMock:
    from schemas.analytics import TransferRequestCreate

    defaults = dict(
        requesting_warehouse_id=uuid.UUID(REQ_WH),
        source_warehouse_id=uuid.UUID(SRC_WH_OTHER_TENANT),
        product_id=uuid.UUID(PRODUCT_ID),
        quantity=10,
    )
    defaults.update(overrides)
    return TransferRequestCreate(**defaults)


async def test_source_warehouse_from_another_tenant_is_rejected() -> None:
    """The source warehouse doesn't resolve within the caller's tenant ->
    404, and nothing is inserted (no unvalidated cross-tenant FK stored)."""
    from routers.transfer_requests import create_transfer_request

    db = AsyncMock()
    statements: list[str] = []

    async def _execute(stmt, params=None):
        sql = " ".join(str(stmt).split())
        statements.append(sql)
        if "FROM warehouses WHERE id = :id AND tenant_id = :tid" in sql and params["id"] == REQ_WH:
            return MagicMock(fetchone=MagicMock(return_value=MagicMock(name="Requesting WH")))
        if "FROM warehouses WHERE id = :id AND tenant_id = :tid" in sql:
            return MagicMock(fetchone=MagicMock(return_value=None))
        if "FROM organization_node WHERE id = :id AND tenant_id = :tid" in sql:
            return MagicMock(fetchone=MagicMock(return_value=None))
        return MagicMock(fetchone=MagicMock(return_value=None))

    db.execute = AsyncMock(side_effect=_execute)

    with _GRANT_ALL, pytest.raises(HTTPException) as exc:
        await create_transfer_request(body=_body(), user=_user(), db=db)

    assert exc.value.status_code == 404
    assert not any(s.startswith("INSERT INTO transfer_requests") for s in statements), (
        "a transfer_request referencing an unvalidated cross-tenant warehouse must never be stored"
    )
