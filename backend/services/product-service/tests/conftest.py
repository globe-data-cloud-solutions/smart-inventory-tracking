"""Test fixtures for product-service unit tests.

All DB and permission-store calls are mocked.
Integration tests that hit dev AWS RDS run in CI (pytest -m integration).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

import pytest
from httpx import AsyncClient

from main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@dataclass
class _User:
    user_id: str
    tenant_id: str
    role: str
    warehouse_id: Optional[str] = None
    region_id: Optional[str] = None


TENANT_A = "10000001-0000-0000-0000-000000000001"
TENANT_B = "99999999-0000-0000-0000-000000000099"

TA_USER  = _User("u-ta",  TENANT_A, "TA")
SA_USER  = _User("u-sa",  TENANT_A, "SA")
WM_USER  = _User("u-wm",  TENANT_A, "WM", warehouse_id="20000001-0000-0000-0000-000000000001")
TA_B     = _User("u-ta-b",TENANT_B, "TA")

VALID_BODY = {"name": "Test Product Alpha", "unit": "KG", "pack_size": 1}
