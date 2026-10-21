"""Unit tests for shared.permissions.read_only (classification) and the
READ_ONLY gate wired into require_permission()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from shared.permissions.read_only import (
    ALLOWED_WRITE_ACTIONS,
    READ_ACTIONS,
    is_blocked_in_read_only,
)
from shared.permissions.registry import ALL_PERMISSIONS, PERMISSIONS
from shared.permissions.middleware import PermissionResult, require_permission

_ALL_ACTION_IDS = {p.id for p in ALL_PERMISSIONS}


def test_read_actions_exist_in_registry() -> None:
    missing = READ_ACTIONS - _ALL_ACTION_IDS
    assert not missing, f"READ_ACTIONS has ids not in registry: {missing}"


def test_allowed_write_actions_exist_in_registry() -> None:
    missing = ALLOWED_WRITE_ACTIONS - _ALL_ACTION_IDS
    assert not missing, f"ALLOWED_WRITE_ACTIONS has ids not in registry: {missing}"


def test_read_and_allowed_write_sets_are_disjoint() -> None:
    assert not (READ_ACTIONS & ALLOWED_WRITE_ACTIONS)


def test_read_action_never_blocked() -> None:
    assert is_blocked_in_read_only("inventory:view") is False


def test_allowed_write_action_never_blocked() -> None:
    assert is_blocked_in_read_only("notification:dismiss") is False


def test_unclassified_write_action_blocked_fail_closed() -> None:
    assert is_blocked_in_read_only("inventory:receive") is True


def test_route_exempt_overrides_write_classification() -> None:
    assert is_blocked_in_read_only("inventory:receive", route_exempt=True) is False


def test_force_write_blocks_even_a_read_classified_action() -> None:
    assert is_blocked_in_read_only("inventory:view", force_write=True) is True


def test_route_exempt_overrides_force_write() -> None:
    assert is_blocked_in_read_only("inventory:view", route_exempt=True, force_write=True) is False


# ── require_permission() decorator wiring ───────────────────────────────────


def _user(role: str = "WM", tenant_id: str | None = "tenant-1") -> MagicMock:
    u = MagicMock()
    u.role, u.tenant_id = role, tenant_id
    u.warehouse_id, u.region_id = None, None
    return u


def _allowed_result() -> PermissionResult:
    return PermissionResult(allowed=True)


async def _call_decorated(action, *, user, db, read_only_exempt: bool = False):
    @require_permission(action, read_only_exempt=read_only_exempt)
    async def handler(*, user, db=None) -> str:
        return "ok"

    return await handler(user=user, db=db)


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_write_action_blocked_when_read_only(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        with pytest.raises(HTTPException) as exc_info:
            await _call_decorated(PERMISSIONS.INVENTORY_RECEIVE, user=_user(), db=db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "CONTRACT_EXPIRED_READ_ONLY"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_read_action_allowed_when_read_only(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        result = await _call_decorated(PERMISSIONS.INVENTORY_VIEW, user=_user(), db=db)
    assert result == "ok"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_exempt_write_action_allowed_when_read_only(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        result = await _call_decorated(
            PERMISSIONS.INVENTORY_RECEIVE,
            user=_user(),
            db=db,
            read_only_exempt=True,
        )
    assert result == "ok"
    mock_stage.assert_not_called()


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_notification_dismiss_allowed_when_read_only(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        result = await _call_decorated(PERMISSIONS.NOTIFICATION_DISMISS, user=_user(), db=db)
    assert result == "ok"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_reset_password_allowed_when_read_only(mock_check) -> None:
    """Security actions stay available in READ_ONLY (CLAUDE.md §29 P6) — a
    staff member must still be able to get back in."""
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        result = await _call_decorated(PERMISSIONS.USER_RESET_PASSWORD, user=_user(), db=db)
    assert result == "ok"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_deactivate_user_allowed_when_read_only(mock_check) -> None:
    """A leaver's access must still be revocable while the tenant is read-only."""
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        result = await _call_decorated(PERMISSIONS.USER_DEACTIVATE, user=_user(), db=db)
    assert result == "ok"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_create_user_still_blocked_when_read_only(mock_check) -> None:
    """user:create is NOT a security action — it must stay blocked (fail-closed)."""
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        with pytest.raises(HTTPException) as exc_info:
            await _call_decorated(PERMISSIONS.USER_CREATE, user=_user(), db=db)
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "CONTRACT_EXPIRED_READ_ONLY"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_sa_bypasses_gate_entirely(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        result = await _call_decorated(
            PERMISSIONS.INVENTORY_RECEIVE,
            user=_user(role="SA", tenant_id=None),
            db=db,
        )
    assert result == "ok"
    mock_stage.assert_not_called()


@pytest.mark.parametrize("stage", ["ACTIVE", "EXPIRING", "GRACE"])
@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_write_allowed_outside_read_only(mock_check, stage) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()
    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": stage,
            "contract_end": None,
            "read_only_since": None,
        }
        result = await _call_decorated(PERMISSIONS.INVENTORY_RECEIVE, user=_user(), db=db)
    assert result == "ok"


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_no_db_raises_500_for_gated_write(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    with pytest.raises(HTTPException) as exc_info:
        await _call_decorated(PERMISSIONS.INVENTORY_RECEIVE, user=_user(), db=None)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "CONTRACT_CHECK_NO_DB"


# ── read_only_force_write ────────────────────────────────────────────────────


@patch("shared.permissions.middleware.check_permission", new_callable=AsyncMock)
async def test_force_write_blocks_a_nominally_read_action_when_read_only(mock_check) -> None:
    mock_check.return_value = _allowed_result()
    db = AsyncMock()

    @require_permission(PERMISSIONS.INVENTORY_VIEW, read_only_force_write=True)
    async def handler(*, user, db=None) -> str:
        return "ok"

    with patch(
        "shared.billing.contract_stage.get_tenant_contract_stage",
        new_callable=AsyncMock,
    ) as mock_stage:
        mock_stage.return_value = {
            "stage": "READ_ONLY",
            "contract_end": None,
            "read_only_since": None,
        }
        with pytest.raises(HTTPException) as exc_info:
            await handler(user=_user(), db=db)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "CONTRACT_EXPIRED_READ_ONLY"


def test_exempt_and_force_write_together_raises_value_error() -> None:
    with pytest.raises(ValueError):
        require_permission(
            PERMISSIONS.INVENTORY_VIEW,
            read_only_exempt=True,
            read_only_force_write=True,
        )
