"""GET /transfers/{id}/approval-info: SLA escalation fields and step_label.

The transfers list shows "Escalated from <position>" and an "Overdue" badge from
these fields (rendered through i18n keys on the frontend). Also pins step_label,
which the router always set but the response model used to drop.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("ENVIRONMENT", "local")

_INV_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _INV_ROOT not in sys.path:
    sys.path.insert(0, _INV_ROOT)

pytestmark = pytest.mark.asyncio

TENANT = "aaaaaaaa-0000-0000-0000-000000000001"
TRANSFER = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
CREATOR = "cccccccc-0000-0000-0000-000000000001"
RM_USER = "cccccccc-0000-0000-0000-000000000002"
TA_TITLE = "Tenant Admin"

_GRANT_ALL = patch(
    "shared.permissions.middleware.check_permission",
    new=AsyncMock(return_value=MagicMock(allowed=True, condition=None)),
)


def _user() -> MagicMock:
    u = MagicMock()
    u.role, u.tenant_id, u.user_id = "RM", TENANT, RM_USER
    return u


def _db(steps: list[dict], *, created_hours_ago: float, current: int = 1) -> AsyncMock:
    row = MagicMock()
    row.transfer_type = "PUSH"
    row.created_by = CREATOR
    row.created_by_authority_level = 3
    row.resolved_approval_steps = steps
    row.current_approval_step = current
    row.created_at = datetime.now(UTC) - timedelta(hours=created_hours_ago)
    res = MagicMock()
    res.fetchone = MagicMock(return_value=row)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=res)
    return db


def _step(**kw) -> dict:
    base = {
        "sequence": 1,
        "position_title": "Warehouse Manager",
        "position_id": "p-wm",
        "assigned_to_user_id": "cccccccc-0000-0000-0000-0000000000aa",
        "assigned_to_name": "WM Person",
        "execution_mode": "sequential",
        "sla_hours": 24,
        "escalated": False,
        "status": "pending",
        "all_holders": [],
        "holder_count": 1,
    }
    base.update(kw)
    return base


async def _info(db: AsyncMock):
    from routers.transfer import get_approval_info

    with _GRANT_ALL:
        resp = await get_approval_info(transfer_id=TRANSFER, user=_user(), db=db)
    return resp.data


async def test_sla_escalated_step_reports_where_it_came_from() -> None:
    esc_at = datetime.now(UTC) - timedelta(hours=1)
    step = _step(
        position_title="Regional Manager",
        assigned_to_user_id=RM_USER,
        assigned_to_name="RM Person",
        escalated=True,
        sla_escalated_at=esc_at.isoformat(),
        sla_escalation_history=[
            {"from_position_title": "Warehouse Manager", "to_position_title": "Regional Manager"}
        ],
    )
    info = await _info(_db([step], created_hours_ago=30))

    assert info.sla_escalated is True
    assert info.escalated_from_position_title == "Warehouse Manager"
    assert info.escalated_to_ta is False
    # Not the self-approval wording the escalated flag used to imply.
    assert info.status_label == "Awaiting RM Person approval"
    # Next deadline runs from the escalation, so it is not overdue yet.
    assert info.sla_due_at == esc_at + timedelta(hours=24)
    assert info.is_overdue is False
    assert info.can_approve is True


async def test_escalated_from_names_the_original_position_after_two_hops() -> None:
    step = _step(
        position_title=TA_TITLE,
        escalated=True,
        escalated_to_ta=True,
        sla_escalated_at=datetime.now(UTC).isoformat(),
        sla_escalation_history=[
            {"from_position_title": "Warehouse Manager"},
            {"from_position_title": "Regional Manager"},
        ],
    )
    info = await _info(_db([step], created_hours_ago=60))
    assert info.escalated_from_position_title == "Warehouse Manager"
    assert info.escalated_to_ta is True


async def test_overdue_step_not_yet_escalated_is_flagged() -> None:
    info = await _info(_db([_step()], created_hours_ago=30))
    assert info.sla_escalated is False
    assert info.is_overdue is True
    assert info.escalated_from_position_title is None


async def test_step_within_its_hours_is_not_overdue() -> None:
    info = await _info(_db([_step()], created_hours_ago=2))
    assert info.is_overdue is False
    assert info.sla_due_at is not None


async def test_step_without_hours_has_no_deadline() -> None:
    info = await _info(_db([_step(sla_hours=None)], created_hours_ago=500))
    assert info.sla_due_at is None
    assert info.is_overdue is False


async def test_step_label_reaches_the_response() -> None:
    steps = [_step(sequence=1, status="approved"), _step(sequence=2)]
    info = await _info(_db(steps, created_hours_ago=1, current=2))
    assert info.step_label == "Step 2 of 2"
