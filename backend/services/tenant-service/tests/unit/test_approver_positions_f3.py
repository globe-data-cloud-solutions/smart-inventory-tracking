"""E2E finding F3: transfer approval rules must name approvers who can approve.

A rule that routes a step to a Logistics Manager saved fine, but LM has no
transfer:approve, so the step could never be signed off. check_approver_positions
rejects such a step before the rules are replaced.

Imports of the router happen inside each test: the tenant-service conftest explains
why (other services' `routers` package can be cached first in a full-suite run).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
POSITION = str(uuid.UUID("e5b06279-d9ef-465b-869d-2125da78f22f"))


def _rule(position_id: str | None):
    from routers.transfer_types import ApprovalRuleIn, ApprovalStepIn

    return ApprovalRuleIn(
        transfer_type_config_id=uuid.uuid4(),
        quantity_min=0,
        quantity_max=999,
        threshold_type="QUANTITY",
        currency="ETB",
        approval_steps=[ApprovalStepIn(sequence=1, position_id=position_id)],
    )


def _db(role_code: str | None, granted: bool) -> AsyncMock:
    """First execute looks up the position's role; second looks up its grant."""
    db = AsyncMock()
    position_row = MagicMock()
    position_row.fetchone.return_value = (role_code,) if role_code else None
    grant_row = MagicMock()
    grant_row.fetchone.return_value = (1,) if granted else None
    db.execute = AsyncMock(side_effect=[position_row, grant_row])
    return db


def _check():
    from routers.transfer_types import check_approver_positions

    return check_approver_positions


@pytest.mark.unit
class TestApproverPositions:
    async def test_position_whose_role_cannot_approve_is_rejected(self) -> None:
        db = _db(role_code="LM", granted=False)
        with pytest.raises(HTTPException) as exc:
            await _check()(db, TENANT, [_rule(POSITION)])
        assert exc.value.status_code == 422
        assert exc.value.detail == {
            "code": "APPROVER_ROLE_CANNOT_APPROVE",
            "position_id": POSITION,
            "role_code": "LM",
        }

    async def test_unknown_position_is_rejected(self) -> None:
        db = _db(role_code=None, granted=False)
        with pytest.raises(HTTPException) as exc:
            await _check()(db, TENANT, [_rule(POSITION)])
        assert exc.value.detail["code"] == "APPROVER_ROLE_CANNOT_APPROVE"
        assert exc.value.detail["role_code"] is None

    async def test_position_whose_role_can_approve_passes(self) -> None:
        db = _db(role_code="RM", granted=True)
        await _check()(db, TENANT, [_rule(POSITION)])

    async def test_step_without_position_is_not_checked(self) -> None:
        db = AsyncMock()
        await _check()(db, TENANT, [_rule(None)])
        db.execute.assert_not_awaited()
