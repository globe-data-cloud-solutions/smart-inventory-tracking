"""Unit tests for P2: contract status + renewal requests
(GET /me/contract-status, POST/GET /me/renewal-requests,
GET /sa/renewal-requests, PATCH /sa/renewal-requests/{id},
GET /sa/contracts/overview) plus the route-order guard and the
READ_ONLY-gate exceptions for the two new actions.

Mocked session + mocked RBAC/audit throughout — no real DB connection
required, matching the repo's existing tenant-service unit test pattern
(test_me_profile_plan_lock.py).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone

os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")
os.environ.setdefault("ENVIRONMENT",       "local")

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TENANT_ROOT not in sys.path:
    sys.path.insert(0, _TENANT_ROOT)

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "scripts"))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402 - sys.path/env setup above must run first

import pytest  # noqa: E402 - sys.path/env setup above must run first
from fastapi import HTTPException  # noqa: E402 - sys.path/env setup above must run first

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
REQUEST_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


def _user(role: str = "TA", tenant_id=TENANT_A):
    from dependencies import UserContext
    return UserContext(
        user_id="u-1", role=role,
        tenant_id=str(tenant_id) if tenant_id else None,
        warehouse_id=None,
    )


def _full_grant():
    grant = MagicMock()
    grant.grant_type = "FULL"
    return grant


def _matrix_grant(role: str, action_id: str):
    """Mirrors the REAL seed_permissions.py matrix — None means RBAC_DENIED,
    matching what store.get_role_permission() would return from a freshly
    seeded DB for this (role, action) pair."""
    import seed_permissions
    grant_type = seed_permissions.ROLE_PERMISSION_MATRIX.get(role, {}).get(action_id)
    if grant_type is None:
        return None
    grant = MagicMock()
    grant.grant_type = grant_type
    return grant


def _active_stage():
    return {"stage": "ACTIVE", "contract_end": None, "read_only_since": None, "grace_ends": None}


def _row(**kwargs):
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _one(row) -> MagicMock:
    """A db.execute() return value whose .fetchone() yields `row` (or None)."""
    return MagicMock(fetchone=MagicMock(return_value=row))


def _many(rows) -> MagicMock:
    """A db.execute() return value whose .fetchall() yields `rows`."""
    return MagicMock(fetchall=MagicMock(return_value=rows))


# ── GET /me/contract-status ──────────────────────────────────────────────────

async def test_get_contract_status_happy_path() -> None:
    from routers.tenants import get_my_contract_status

    stage_info = {
        "stage": "EXPIRING", "contract_end": date(2026, 10, 15),
        "grace_ends": date(2026, 10, 29), "read_only_since": date(2026, 10, 30),
    }
    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(id=REQUEST_ID, created_at=datetime(2026, 10, 1, tzinfo=timezone.utc))),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.tenants.get_tenant_contract_stage", new=AsyncMock(return_value=stage_info)), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        out = await get_my_contract_status(user=_user(), db=db)

    assert out.data.stage == "EXPIRING"
    assert out.data.contract_end == "2026-10-15"
    assert out.data.open_request is not None
    assert out.data.open_request.id == REQUEST_ID


async def test_nm_get_contract_status_allowed() -> None:
    """NM is granted tenant:view_contract_status in the real matrix -> 200."""
    from routers.tenants import get_my_contract_status

    db = AsyncMock()
    db.execute.side_effect = [_one(None)]  # no open request row

    with patch(
        "shared.permissions.middleware.get_role_permission",
        new=AsyncMock(side_effect=lambda role, action: _matrix_grant(role, action)),
    ), patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
       patch("routers.tenants.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())), \
       patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        out = await get_my_contract_status(user=_user(role="NM"), db=db)

    assert out.data.stage == "ACTIVE"


# ── POST /me/renewal-requests ────────────────────────────────────────────────

async def test_create_renewal_request_happy_path() -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(None),                                            # no existing OPEN
        _one(_row(email="ta@example.com")),                     # requester email lookup
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message="please renew",
            request_type="RENEWAL", requested_tier=None,
            status="OPEN", handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())), \
         patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
        out = await create_my_renewal_request(body=RenewalRequestIn(message="please renew"), user=_user(), db=db)

    assert out.data.id == REQUEST_ID
    assert out.data.status == "OPEN"
    assert out.data.request_type == "RENEWAL"


async def test_create_renewal_request_second_open_returns_409() -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [_one(_row(id=REQUEST_ID))]  # existing OPEN found

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        with pytest.raises(HTTPException) as exc_info:
            await create_my_renewal_request(body=RenewalRequestIn(message="again"), user=_user(), db=db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "RENEWAL_REQUEST_OPEN"
    assert exc_info.value.detail["id"] == str(REQUEST_ID)


async def test_create_renewal_request_allowed_when_read_only() -> None:
    """tenant:renewal_request is in ALLOWED_WRITE_ACTIONS -> allowed at ANY stage."""
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(None),
        _one(_row(email="ta@example.com")),
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message=None,
            request_type="RENEWAL", requested_tier=None,
            status="OPEN", handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch(
             "shared.billing.contract_stage.get_tenant_contract_stage",
             new=AsyncMock(return_value={
                 "stage": "READ_ONLY", "contract_end": None, "read_only_since": None, "grace_ends": None,
             }),
         ), patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
        out = await create_my_renewal_request(body=RenewalRequestIn(), user=_user(), db=db)

    assert out.data.status == "OPEN"


async def test_nm_create_renewal_request_forbidden() -> None:
    """NM has no grant for tenant:renewal_request in the real matrix -> 403."""
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    with patch(
        "shared.permissions.middleware.get_role_permission",
        new=AsyncMock(side_effect=lambda role, action: _matrix_grant(role, action)),
    ), patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await create_my_renewal_request(body=RenewalRequestIn(), user=_user(role="NM"), db=db)

    assert exc_info.value.status_code == 403
    db.execute.assert_not_called()


async def test_me_contacts_post_allowed_when_read_only() -> None:
    """POST /me/contacts is read_only_exempt=True -> allowed even READ_ONLY."""
    from routers.tenants import create_my_contact, TenantContactIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(
            id=uuid.uuid4(), full_name="Jane Doe", position_title=None,
            email=None, phone=None, mobile=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch(
             "shared.billing.contract_stage.get_tenant_contract_stage",
             new=AsyncMock(return_value={
                 "stage": "READ_ONLY", "contract_end": None, "read_only_since": None, "grace_ends": None,
             }),
         ):
        out = await create_my_contact(
            body=TenantContactIn(full_name="Jane Doe"), user=_user(), db=db,
        )

    assert out.data.full_name == "Jane Doe"


# ── GET /me/renewal-requests ──────────────────────────────────────────────────

async def test_list_my_renewal_requests_happy_path() -> None:
    from routers.tenants import list_my_renewal_requests

    db = AsyncMock()
    db.execute.return_value = _many([
        _row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message="renew please",
            request_type="RENEWAL", requested_tier=None,
            status="OPEN", handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        ),
    ])

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        out = await list_my_renewal_requests(user=_user(), db=db)

    assert len(out.data) == 1
    assert out.data[0].id == REQUEST_ID


# ── GET /sa/renewal-requests ──────────────────────────────────────────────────

async def test_sa_list_renewal_requests_happy_path() -> None:
    from routers.tenants import sa_list_renewal_requests

    db = AsyncMock()
    db.execute.return_value = _many([
        _row(
            id=REQUEST_ID, tenant_id=TENANT_A, tenant_name="Acme", tenant_slug="acme",
            plan_tier="GROWTH", contract_end=date(2026, 10, 15),
            requested_by=uuid.UUID(int=1), requested_by_email="ta@example.com",
            message="renew please", request_type="RENEWAL", requested_tier=None,
            status="OPEN",
            handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        ),
    ])

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await sa_list_renewal_requests(status="OPEN", type="ALL", user=_user(role="SA", tenant_id=None), db=db)

    assert len(out.data) == 1
    assert out.data[0].tenant_name == "Acme"


async def test_ta_calling_sa_renewal_requests_forbidden() -> None:
    """TA has no grant for tenant:renewal_manage in the real matrix -> RBAC_DENIED (403)."""
    from routers.tenants import sa_list_renewal_requests

    db = AsyncMock()
    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=None)), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await sa_list_renewal_requests(status="OPEN", user=_user(role="TA"), db=db)

    assert exc_info.value.status_code == 403
    db.execute.assert_not_called()


# ── PATCH /sa/renewal-requests/{id} ──────────────────────────────────────────

async def test_sa_handle_renewal_request_happy_path() -> None:
    from routers.tenants import sa_handle_renewal_request, RenewalRequestHandleIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(id=REQUEST_ID, tenant_id=TENANT_A, status="OPEN", request_type="RENEWAL")),
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message="renew please",
            request_type="RENEWAL", requested_tier=None,
            status="HANDLED", handled_by=uuid.UUID(int=2), handled_note="done",
            handled_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
            created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.tenants._log_tenant_activity", new=AsyncMock()) as mock_log:
        out = await sa_handle_renewal_request(
            request_id=REQUEST_ID,
            body=RenewalRequestHandleIn(status="HANDLED", note="done"),
            user=_user(role="SA", tenant_id=None), db=db,
        )

    assert out.data.status == "HANDLED"
    assert mock_log.call_args.kwargs["action"] == "RENEWAL_HANDLED"


async def test_sa_handle_non_open_renewal_request_returns_409() -> None:
    from routers.tenants import sa_handle_renewal_request, RenewalRequestHandleIn

    db = AsyncMock()
    db.execute.side_effect = [_one(_row(id=REQUEST_ID, tenant_id=TENANT_A, status="HANDLED"))]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await sa_handle_renewal_request(
                request_id=REQUEST_ID,
                body=RenewalRequestHandleIn(status="CANCELLED"),
                user=_user(role="SA", tenant_id=None), db=db,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "RENEWAL_REQUEST_NOT_OPEN"


# ── GET /sa/contracts/overview ────────────────────────────────────────────────

async def test_sa_contracts_overview_happy_path() -> None:
    from routers.tenants import sa_contracts_overview

    db = AsyncMock()
    db.execute.return_value = _many([
        _row(id=TENANT_A, name="Acme", slug="acme", plan_tier="GROWTH",
             contract_end=date(2026, 10, 15), open_request_id=REQUEST_ID),
        _row(id=uuid.uuid4(), name="Healthy Co", slug="healthy", plan_tier="ENTERPRISE",
             contract_end=date(2027, 1, 1), open_request_id=None),
    ])

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.tenants.datetime") as mock_dt:
        mock_dt.utcnow.return_value = datetime(2026, 10, 9)
        out = await sa_contracts_overview(user=_user(role="SA", tenant_id=None), db=db)

    # "Healthy Co" (contract_end 2027-01-01) is ACTIVE -> excluded from the overview.
    assert len(out.data.tenants) == 1
    assert out.data.tenants[0].name == "Acme"
    assert out.data.counts["EXPIRING"] == 1


# ── Route order: /me and /sa before /{tenant_id} ─────────────────────────────

async def test_create_upgrade_request_happy_path() -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(plan_tier="STARTER")),                       # current tier lookup
        _one(None),                                            # no existing OPEN upgrade
        _one(_row(email="ta@example.com")),                    # requester email lookup
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message=None,
            request_type="UPGRADE", requested_tier="GROWTH",
            status="OPEN", handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())), \
         patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
        out = await create_my_renewal_request(
            body=RenewalRequestIn(request_type="UPGRADE", requested_tier="GROWTH"),
            user=_user(), db=db,
        )

    assert out.data.request_type == "UPGRADE"
    assert out.data.requested_tier == "GROWTH"


async def test_create_upgrade_request_requires_tier() -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        with pytest.raises(HTTPException) as exc_info:
            await create_my_renewal_request(
                body=RenewalRequestIn(request_type="UPGRADE"), user=_user(), db=db,
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "REQUESTED_TIER_REQUIRED"
    db.execute.assert_not_called()


async def test_create_renewal_request_tier_not_allowed() -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        with pytest.raises(HTTPException) as exc_info:
            await create_my_renewal_request(
                body=RenewalRequestIn(request_type="RENEWAL", requested_tier="GROWTH"),
                user=_user(), db=db,
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "REQUESTED_TIER_NOT_ALLOWED"
    db.execute.assert_not_called()


@pytest.mark.parametrize("current_tier,requested_tier", [
    ("ENTERPRISE", "GROWTH"),   # lower tier
    ("GROWTH", "GROWTH"),       # same tier
])
async def test_create_upgrade_request_not_an_upgrade(current_tier, requested_tier) -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [_one(_row(plan_tier=current_tier))]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        with pytest.raises(HTTPException) as exc_info:
            await create_my_renewal_request(
                body=RenewalRequestIn(request_type="UPGRADE", requested_tier=requested_tier),
                user=_user(), db=db,
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "NOT_AN_UPGRADE"


async def test_renewal_and_upgrade_open_at_same_time_both_succeed() -> None:
    """A RENEWAL request stays open while a separate UPGRADE request is created
    for the same tenant — the one-open-per-type index allows both."""
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(plan_tier="STARTER")),
        _one(None),  # no existing OPEN upgrade (a RENEWAL may already be open, untouched)
        _one(_row(email="ta@example.com")),
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message=None,
            request_type="UPGRADE", requested_tier="GROWTH",
            status="OPEN", handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())), \
         patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
        out = await create_my_renewal_request(
            body=RenewalRequestIn(request_type="UPGRADE", requested_tier="GROWTH"),
            user=_user(), db=db,
        )

    assert out.data.status == "OPEN"
    assert out.data.request_type == "UPGRADE"


async def test_create_upgrade_request_second_open_returns_409_upgrade_code() -> None:
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(plan_tier="STARTER")),
        _one(_row(id=REQUEST_ID)),  # existing OPEN upgrade found
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("shared.billing.contract_stage.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        with pytest.raises(HTTPException) as exc_info:
            await create_my_renewal_request(
                body=RenewalRequestIn(request_type="UPGRADE", requested_tier="GROWTH"),
                user=_user(), db=db,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "UPGRADE_REQUEST_OPEN"
    assert exc_info.value.detail["id"] == str(REQUEST_ID)


async def test_get_contract_status_ignores_open_upgrade() -> None:
    """An OPEN UPGRADE request must not surface as a renewal open_request."""
    from routers.tenants import get_my_contract_status

    db = AsyncMock()
    db.execute.side_effect = [_one(None)]  # the RENEWAL-filtered query finds nothing

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.tenants.get_tenant_contract_stage", new=AsyncMock(return_value=_active_stage())):
        out = await get_my_contract_status(user=_user(), db=db)

    assert out.data.open_request is None


async def test_sa_list_renewal_requests_type_filter() -> None:
    from routers.tenants import sa_list_renewal_requests

    db = AsyncMock()
    db.execute.return_value = _many([
        _row(
            id=REQUEST_ID, tenant_id=TENANT_A, tenant_name="Acme", tenant_slug="acme",
            plan_tier="STARTER", contract_end=date(2026, 10, 15),
            requested_by=uuid.UUID(int=1), requested_by_email="ta@example.com",
            message=None, request_type="UPGRADE", requested_tier="GROWTH",
            status="OPEN",
            handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        ),
    ])

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()):
        out = await sa_list_renewal_requests(status="ALL", type="UPGRADE", user=_user(role="SA", tenant_id=None), db=db)

    assert len(out.data) == 1
    assert out.data[0].request_type == "UPGRADE"
    assert out.data[0].requested_tier == "GROWTH"


async def test_sa_handle_upgrade_request_logs_upgrade_handled_and_leaves_plan_unchanged() -> None:
    from routers.tenants import sa_handle_renewal_request, RenewalRequestHandleIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(id=REQUEST_ID, tenant_id=TENANT_A, status="OPEN", request_type="UPGRADE")),
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message=None,
            request_type="UPGRADE", requested_tier="GROWTH",
            status="HANDLED", handled_by=uuid.UUID(int=2), handled_note="approved",
            handled_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
            created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch("routers.tenants._log_tenant_activity", new=AsyncMock()) as mock_log:
        out = await sa_handle_renewal_request(
            request_id=REQUEST_ID,
            body=RenewalRequestHandleIn(status="HANDLED", note="approved"),
            user=_user(role="SA", tenant_id=None), db=db,
        )

    assert out.data.status == "HANDLED"
    assert mock_log.call_args.kwargs["action"] == "UPGRADE_HANDLED"
    # No plan-change call is made: only the two expected db.execute() calls (lookup + update).
    assert db.execute.call_count == 2


async def test_create_renewal_request_allowed_when_read_only_stage_for_upgrade() -> None:
    """tenant:renewal_request is in ALLOWED_WRITE_ACTIONS -> an UPGRADE request
    is also allowed at the READ_ONLY stage."""
    from routers.tenants import create_my_renewal_request, RenewalRequestIn

    db = AsyncMock()
    db.execute.side_effect = [
        _one(_row(plan_tier="STARTER")),
        _one(None),
        _one(_row(email="ta@example.com")),
        _one(_row(
            id=REQUEST_ID, tenant_id=TENANT_A, requested_by=uuid.UUID(int=1),
            requested_by_email="ta@example.com", message=None,
            request_type="UPGRADE", requested_tier="GROWTH",
            status="OPEN", handled_by=None, handled_note=None, handled_at=None,
            created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )),
    ]

    with patch("shared.permissions.middleware.get_role_permission", new=AsyncMock(return_value=_full_grant())), \
         patch("shared.permissions.middleware.audit_log", new=AsyncMock()), \
         patch(
             "shared.billing.contract_stage.get_tenant_contract_stage",
             new=AsyncMock(return_value={
                 "stage": "READ_ONLY", "contract_end": None, "read_only_since": None, "grace_ends": None,
             }),
         ), patch("routers.tenants._log_tenant_activity", new=AsyncMock()):
        out = await create_my_renewal_request(
            body=RenewalRequestIn(request_type="UPGRADE", requested_tier="GROWTH"),
            user=_user(), db=db,
        )

    assert out.data.status == "OPEN"
    assert out.data.request_type == "UPGRADE"


# ── Route order: /me and /sa before /{tenant_id} ─────────────────────────────

@pytest.mark.parametrize(
    "method,path,expected_fn",
    [
        ("GET",   "/api/v1/tenants/me/contract-status",       "get_my_contract_status"),
        ("POST",  "/api/v1/tenants/me/renewal-requests",       "create_my_renewal_request"),
        ("GET",   "/api/v1/tenants/me/renewal-requests",       "list_my_renewal_requests"),
        ("GET",   "/api/v1/tenants/sa/renewal-requests",       "sa_list_renewal_requests"),
        ("PATCH", f"/api/v1/tenants/sa/renewal-requests/{REQUEST_ID}", "sa_handle_renewal_request"),
        ("GET",   "/api/v1/tenants/sa/contracts/overview",     "sa_contracts_overview"),
    ],
)
def test_new_routes_not_shadowed_by_tenant_id_param(method, path, expected_fn) -> None:
    from starlette.routing import Match
    from main import app

    scope = {"type": "http", "method": method, "path": path, "path_params": {}}

    matched_route = None
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            matched_route = route
            break

    assert matched_route is not None, f"no route matched {method} {path}"
    assert matched_route.endpoint.__name__ == expected_fn, (
        f"expected {expected_fn!r} to match {method} {path!r}, got "
        f"{matched_route.endpoint.__name__!r} instead (declared-before-/{{tenant_id}} regression)"
    )
