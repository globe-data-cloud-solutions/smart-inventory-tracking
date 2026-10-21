"""Unit tests for dependencies._rls_tenant_for — SA scopes RLS via ?tenant_id."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dependencies import UserContext, _rls_tenant_for

OWN = "11111111-1111-1111-1111-111111111111"
OTHER = "0e898780-9aa2-4f63-b39f-258f45ed161e"


def _req(**params: str) -> SimpleNamespace:
    return SimpleNamespace(query_params=params)


def _user(role: str, tenant_id: str | None) -> UserContext:
    return UserContext(user_id="u1", role=role, tenant_id=tenant_id, warehouse_id=None)


@pytest.mark.unit
class TestRlsTenantFor:
    def test_sa_with_tenant_id_uses_that_tenant(self) -> None:
        assert _rls_tenant_for(_user("SA", ""), _req(tenant_id=OTHER)) == OTHER

    def test_sa_without_tenant_id_keeps_user_tenant(self) -> None:
        assert _rls_tenant_for(_user("SA", OWN), _req()) == OWN

    def test_ta_cannot_switch_tenant_via_query(self) -> None:
        assert _rls_tenant_for(_user("TA", OWN), _req(tenant_id=OTHER)) == OWN

    def test_sa_with_non_uuid_tenant_id_keeps_user_tenant(self) -> None:
        assert _rls_tenant_for(_user("SA", OWN), _req(tenant_id="not-a-uuid")) == OWN
