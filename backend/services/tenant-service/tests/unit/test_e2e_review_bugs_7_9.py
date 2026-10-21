"""Regression tests for the TenantClaude18 E2E review, bugs 7 and 9.

Bug 7: POST /nodes returned address=null although the address was persisted.
Bug 9: personnel_v2 user email used a strict EmailStr that rejected .local
       addresses, unlike signup's format check.
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("JWT_SECRET", "x" * 40)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "backend"))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402


class TestBug9UserEmail:
    # Imported inside each test: 'routers' is a name shared by every service.
    @staticmethod
    def _models():
        from routers.personnel_v2 import UserCreate, UserUpdateRequest

        return UserCreate, UserUpdateRequest

    def test_local_domain_accepted(self) -> None:
        UserCreate, UserUpdateRequest = self._models()
        u = UserCreate(name="A", email="ta@t06.local", password="x" * 8)
        assert u.email == "ta@t06.local"

    def test_plain_email_accepted_and_case_kept(self) -> None:
        UserCreate, UserUpdateRequest = self._models()
        u = UserCreate(name="A", email="  Ops@Example.com ", password="x" * 8)
        assert u.email == "Ops@Example.com"

    @pytest.mark.parametrize("bad", ["not-an-email", "@nodomain.com", "a@b", "a@"])
    def test_malformed_rejected(self, bad: str) -> None:
        UserCreate, UserUpdateRequest = self._models()
        with pytest.raises(ValidationError):
            UserCreate(name="A", email=bad, password="x" * 8)

    def test_update_accepts_local_domain_and_none(self) -> None:
        _, UserUpdateRequest = self._models()
        assert UserUpdateRequest(email="ta@t06.local").email == "ta@t06.local"
        assert UserUpdateRequest(name="only name").email is None

    def test_update_rejects_malformed(self) -> None:
        _, UserUpdateRequest = self._models()
        with pytest.raises(ValidationError):
            UserUpdateRequest(email="nope")


class TestBug7NodeAddressInResponse:
    async def test_create_node_response_carries_address(self) -> None:
        from routers import hierarchy

        body = hierarchy.OrgNodeCreate(
            name="WHA9 Test", level_number=2, is_stock_holding=False, address="Bole Rd 12"
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock())
        user = MagicMock(tenant_id=uuid.uuid4(), system_role="TA")
        with (
            patch.object(hierarchy, "_get_level_name", AsyncMock(return_value="Region")),
            patch.object(hierarchy, "check_plan_create_warehouse", AsyncMock(), create=True),
        ):
            fn = getattr(hierarchy.create_org_node, "__wrapped__", hierarchy.create_org_node)
            resp = await fn(tenant_id=user.tenant_id, body=body, user=user, db=db)
        assert resp.data.address == "Bole Rd 12"


class TestBug10ManagerUserIdRemoved:
    """Bug 10: manager_user_id was accepted and discarded. The field is gone;
    a stale client that still sends it is ignored, not persisted or echoed."""

    def test_field_removed_from_node_schemas(self) -> None:
        from routers.hierarchy import OrgNodeCreate, OrgNodeUpdate

        assert "manager_user_id" not in OrgNodeCreate.model_fields
        assert "manager_user_id" not in OrgNodeUpdate.model_fields

    def test_stale_client_payload_is_ignored(self) -> None:
        from routers.hierarchy import OrgNodeCreate

        body = OrgNodeCreate(name="X", level_number=2, manager_user_id=uuid.uuid4())
        assert not hasattr(body, "manager_user_id")
