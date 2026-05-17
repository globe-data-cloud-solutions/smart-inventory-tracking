"""Shared test data and helper factories for product-service tests.

Placed at the service root (not inside tests/) so it is importable as
`product_test_data` when the product-service root is on sys.path, with
no risk of colliding with inventory-service's `tests` package.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock


@dataclass
class _User:
    user_id: str
    tenant_id: str
    role: str
    warehouse_id: Optional[str] = None
    region_id: Optional[str] = None


TENANT_A = "10000001-0000-0000-0000-000000000001"
TENANT_B = "99999999-0000-0000-0000-000000000099"

TA_USER = _User("10000001-0000-0000-0000-000000000010", TENANT_A, "TA")
SA_USER = _User("10000001-0000-0000-0000-000000000011", TENANT_A, "SA")
WM_USER = _User("10000001-0000-0000-0000-000000000012", TENANT_A, "WM",
                warehouse_id="20000001-0000-0000-0000-000000000001")

VALID_BODY = {"name": "Test Product Alpha", "unit": "KG", "pack_size": 1}


def mock_full_grant() -> MagicMock:
    g = MagicMock()
    g.grant_type = "FULL"
    return g


def _make_mock_db(
    org_type: str = "PRODUCER",
    sku_cap: Optional[int] = None,
    sku_prefix: str = "ETH",
    sku_counter: int = 46,
    dup_exists: bool = False,
    count_at_cap: bool = False,
) -> AsyncMock:
    db = AsyncMock()

    tenant_row = MagicMock()
    tenant_row.organisation_type = org_type
    tenant_row.sku_cap = sku_cap
    tenant_row.sku_prefix = sku_prefix
    tenant_row.sku_counter = sku_counter

    sku_row = MagicMock()
    sku_row.sku_prefix = sku_prefix
    sku_row.sku_counter = sku_counter + 1

    default = MagicMock()
    default.fetchone.return_value = None
    default.scalar.return_value = 0

    tenant_res = MagicMock()
    tenant_res.fetchone.return_value = tenant_row

    count_res = MagicMock()
    count_res.scalar.return_value = sku_cap if count_at_cap else 0

    dup_res = MagicMock()
    dup_res.fetchone.return_value = MagicMock(id="existing") if dup_exists else None

    sku_res = MagicMock()
    sku_res.fetchone.return_value = sku_row

    if sku_cap:
        db.execute = AsyncMock(side_effect=[
            tenant_res, count_res, dup_res, sku_res, default, default, default,
        ])
    else:
        db.execute = AsyncMock(side_effect=[
            tenant_res, dup_res, sku_res, default, default, default,
        ])
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _cap_db(cap: int, current_count: int, org_type: str = "PRODUCER") -> AsyncMock:
    return _make_mock_db(org_type=org_type, sku_cap=cap, count_at_cap=(current_count >= cap))


def _make_db_override(db: AsyncMock):
    """Returns an async generator function for use in app.dependency_overrides."""
    async def _override():
        yield db
    return _override
