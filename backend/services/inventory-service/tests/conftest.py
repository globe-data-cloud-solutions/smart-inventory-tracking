import pytest
from httpx import AsyncClient

from services.inventory_service.main import app


@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def wm_user():
    """Warehouse Manager with valid tenant and warehouse scope."""
    class _User:
        user_id = "00000000-0000-0000-0000-000000000001"
        tenant_id = "10000000-0000-0000-0000-000000000001"
        warehouse_id = "20000000-0000-0000-0000-000000000001"
        region_id = None
        role = "WM"
    return _User()


@pytest.fixture
def au_user():
    """Auditor — read-only role."""
    class _User:
        user_id = "00000000-0000-0000-0000-000000000002"
        tenant_id = "10000000-0000-0000-0000-000000000001"
        warehouse_id = None
        region_id = None
        role = "AU"
    return _User()


@pytest.fixture
def other_tenant_user():
    """WM from a different tenant — must not access Tenant A data."""
    class _User:
        user_id = "00000000-0000-0000-0000-000000000003"
        tenant_id = "99999999-0000-0000-0000-000000000001"
        warehouse_id = "20000000-0000-0000-0000-000000000001"
        region_id = None
        role = "WM"
    return _User()
