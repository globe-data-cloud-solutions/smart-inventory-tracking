"""Unit tests for shared/approvals/sla_escalation.py (timer-driven escalation).

No real DB: a fake session answers each query by its SQL. Rules under test
(Alex, 2026-10-25): clock from transfer creation; overdue step moves to the next
position up; TA notified on every escalation; TA fallback when nothing is above;
a step on a TA never escalates further.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.approvals.sla_escalation import (
    TA_POSITION_TITLE,
    escalate_overdue_steps,
    step_due_at,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TENANT = "11111111-1111-1111-1111-111111111111"
CREATOR = "c0000000-0000-0000-0000-000000000001"
RM_USER = "c0000000-0000-0000-0000-000000000002"
NM_USER = "c0000000-0000-0000-0000-000000000003"
TA_USER = "c0000000-0000-0000-0000-000000000009"
WM_POS, RM_POS, NM_POS = "p-wm", "p-rm", "p-nm"


def _row(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def _step(**kw: Any) -> dict:
    base = {
        "sequence": 1,
        "position_title": "Warehouse Manager",
        "position_id": WM_POS,
        "node_id": "n-wh",
        "assigned_to_user_id": "c0000000-0000-0000-0000-0000000000aa",
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


def _transfer(
    steps: list[dict], *, created_hours_ago: float = 30, current: int = 1, tid: str = "t-1"
) -> SimpleNamespace:
    return _row(
        id=tid,
        tenant_id=TENANT,
        created_by=CREATOR,
        created_at=NOW - timedelta(hours=created_hours_ago),
        current_approval_step=current,
        resolved_approval_steps=steps,
    )


def _holder(pos: str, title: str, user: str | None, name: str = "") -> SimpleNamespace:
    return _row(id=pos, title=title, user_id=user, full_name=name)


class _Nested:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False  # let errors reach escalate_overdue_steps' per-row handler


class _FakeSession:
    def __init__(
        self,
        transfers: list[SimpleNamespace],
        chain: dict[str, list[SimpleNamespace]] | None = None,
        tas: list[SimpleNamespace] | None = None,
        fail_on_pid: str | None = None,
    ) -> None:
        self.transfers = transfers
        self.chain = chain or {}
        self.tas = tas if tas is not None else [_row(id=TA_USER, full_name="Tenant Admin User")]
        self.fail_on_pid = fail_on_pid
        self.executed: list[tuple[str, dict]] = []

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def execute(self, stmt: Any, params: dict | None = None) -> MagicMock:
        sql = str(stmt)
        params = params or {}
        self.executed.append((sql, params))
        res = MagicMock()
        if "FROM   transfer_orders to_" in sql:
            res.fetchall.return_value = self.transfers
        elif "reports_to_position_id" in sql:
            if params.get("pid") == self.fail_on_pid:
                raise RuntimeError("boom")
            res.fetchall.return_value = self.chain.get(params["pid"], [])
        elif "system_role = 'TA'" in sql:
            res.fetchall.return_value = self.tas
        else:
            res.fetchall.return_value = []
        return res

    # helpers for assertions
    def updates(self) -> list[dict]:
        return [p for s, p in self.executed if s.lstrip().startswith("UPDATE transfer_orders")]

    def inserts(self, table: str) -> list[dict]:
        return [p for s, p in self.executed if f"INSERT INTO {table}" in s]


def _updated_step(session: _FakeSession, idx: int = 0) -> dict:
    ups = session.updates()
    assert len(ups) == 1
    return ups[0]["steps"][idx]


# ── due-time rule ────────────────────────────────────────────────────────────


def test_due_time_counts_from_creation() -> None:
    created = NOW - timedelta(hours=5)
    assert step_due_at(_step(sla_hours=24), created) == created + timedelta(hours=24)


def test_due_time_after_escalation_counts_from_escalation() -> None:
    esc = NOW - timedelta(hours=2)
    step = _step(sla_hours=24, sla_escalated_at=esc.isoformat())
    assert step_due_at(step, NOW - timedelta(days=10)) == esc + timedelta(hours=24)


@pytest.mark.parametrize("sla", [None, 0, -3, "abc"])
def test_no_usable_sla_means_never_due(sla: Any) -> None:
    assert step_due_at(_step(sla_hours=sla), NOW - timedelta(days=30)) is None


# ── batch behaviour ──────────────────────────────────────────────────────────


async def test_step_not_yet_due_is_left_alone() -> None:
    session = _FakeSession([_transfer([_step()], created_hours_ago=23)])
    assert await escalate_overdue_steps(session, now=NOW) == 0
    assert session.updates() == []
    assert session.inserts("outbox") == []


async def test_step_exactly_at_due_time_escalates() -> None:
    session = _FakeSession(
        [_transfer([_step()], created_hours_ago=24)],
        chain={WM_POS: [_holder(RM_POS, "Regional Manager", RM_USER, "RM Person")]},
    )
    assert await escalate_overdue_steps(session, now=NOW) == 1


async def test_overdue_step_moves_to_next_position_up_and_notifies_ta() -> None:
    session = _FakeSession(
        [_transfer([_step()])],
        chain={WM_POS: [_holder(RM_POS, "Regional Manager", RM_USER, "RM Person")]},
    )
    assert await escalate_overdue_steps(session, now=NOW) == 1

    step = _updated_step(session)
    assert step["position_title"] == "Regional Manager"
    assert step["assigned_to_user_id"] == RM_USER
    assert step["all_holders"] == [{"user_id": RM_USER, "name": "RM Person"}]
    assert step["escalated"] is True
    assert step["escalated_to_ta"] is False
    assert step["sla_escalation_position_id"] == RM_POS
    assert step["sla_escalated_at"] == NOW.isoformat()
    assert step["sla_escalation_history"][0]["from_position_title"] == "Warehouse Manager"

    audit = session.inserts("audit_logs")
    assert len(audit) == 1
    assert audit[0]["action"] == "transfer:approval_escalated"
    assert audit[0]["role"] == "SYS"
    assert audit[0]["tenant_id"] == TENANT

    outbox = session.inserts("outbox")
    assert len(outbox) == 1
    assert outbox[0]["etype"] == "ApprovalStepEscalated"
    assert outbox[0]["ikey"] == "approval-escalation:t-1:1:1"
    payload = json.loads(outbox[0]["payload"])
    assert payload["to_user_ids"] == [RM_USER]
    assert payload["ta_user_ids"] == [TA_USER]  # TA told even when not the target
    assert payload["escalated_to_ta"] is False


async def test_vacant_parent_is_skipped_for_the_next_holder_above() -> None:
    session = _FakeSession(
        [_transfer([_step()])],
        chain={
            WM_POS: [_holder(RM_POS, "Regional Manager", None)],
            RM_POS: [_holder(NM_POS, "National Manager", NM_USER, "NM Person")],
        },
    )
    assert await escalate_overdue_steps(session, now=NOW) == 1
    step = _updated_step(session)
    assert step["position_title"] == "National Manager"
    assert step["assigned_to_user_id"] == NM_USER


async def test_creator_is_never_the_escalation_target() -> None:
    session = _FakeSession(
        [_transfer([_step()])],
        chain={
            WM_POS: [_holder(RM_POS, "Regional Manager", CREATOR, "Creator")],
            RM_POS: [_holder(NM_POS, "National Manager", NM_USER, "NM Person")],
        },
    )
    assert await escalate_overdue_steps(session, now=NOW) == 1
    assert _updated_step(session)["assigned_to_user_id"] == NM_USER


async def test_nothing_above_routes_to_ta() -> None:
    session = _FakeSession([_transfer([_step()])], chain={})
    assert await escalate_overdue_steps(session, now=NOW) == 1
    step = _updated_step(session)
    assert step["position_title"] == TA_POSITION_TITLE
    assert step["assigned_to_user_id"] == TA_USER
    assert step["escalated_to_ta"] is True
    assert json.loads(session.inserts("outbox")[0]["payload"])["escalated_to_ta"] is True


async def test_step_already_on_ta_stops() -> None:
    step = _step(escalated_to_ta=True, assigned_to_user_id=TA_USER)
    session = _FakeSession([_transfer([step], created_hours_ago=500)])
    assert await escalate_overdue_steps(session, now=NOW) == 0
    assert session.updates() == []


async def test_step_assigned_to_a_ta_at_creation_also_stops() -> None:
    step = _step(assigned_to_user_id=TA_USER, position_title=TA_POSITION_TITLE)
    session = _FakeSession([_transfer([step], created_hours_ago=500)])
    assert await escalate_overdue_steps(session, now=NOW) == 0


async def test_second_escalation_waits_another_period_then_climbs_from_new_position() -> None:
    escalated = _step(
        position_title="Regional Manager",
        assigned_to_user_id=RM_USER,
        sla_escalated_at=(NOW - timedelta(hours=2)).isoformat(),
        sla_escalation_position_id=RM_POS,
        sla_escalation_history=[{"to_position_title": "Regional Manager"}],
        escalated=True,
    )
    chain = {RM_POS: [_holder(NM_POS, "National Manager", NM_USER, "NM Person")]}

    # 2h since the last escalation: not due again yet, although created long ago.
    session = _FakeSession([_transfer([dict(escalated)], created_hours_ago=200)], chain=chain)
    assert await escalate_overdue_steps(session, now=NOW) == 0

    # 25h since the last escalation: climbs from RM to NM.
    escalated["sla_escalated_at"] = (NOW - timedelta(hours=25)).isoformat()
    session = _FakeSession([_transfer([dict(escalated)], created_hours_ago=200)], chain=chain)
    assert await escalate_overdue_steps(session, now=NOW) == 1
    step = _updated_step(session)
    assert step["assigned_to_user_id"] == NM_USER
    assert len(step["sla_escalation_history"]) == 2
    assert session.inserts("outbox")[0]["ikey"] == "approval-escalation:t-1:1:2"


async def test_only_the_current_step_is_considered() -> None:
    steps = [
        _step(sequence=1, status="approved"),
        _step(sequence=2, position_id=RM_POS, position_title="Regional Manager"),
    ]
    session = _FakeSession(
        [_transfer(steps, current=2)],
        chain={RM_POS: [_holder(NM_POS, "National Manager", NM_USER, "NM Person")]},
    )
    assert await escalate_overdue_steps(session, now=NOW) == 1
    ups = session.updates()[0]["steps"]
    assert ups[0]["status"] == "approved"
    assert ups[0].get("escalated") is False
    assert ups[1]["assigned_to_user_id"] == NM_USER


async def test_no_target_and_no_ta_leaves_step_in_place() -> None:
    session = _FakeSession([_transfer([_step()])], chain={}, tas=[])
    assert await escalate_overdue_steps(session, now=NOW) == 0
    assert session.updates() == []


async def test_one_failing_transfer_does_not_stop_the_batch() -> None:
    bad = _transfer([_step(position_id="p-bad")], tid="t-bad")
    good = _transfer([_step()], tid="t-good")
    session = _FakeSession(
        [bad, good],
        chain={WM_POS: [_holder(RM_POS, "Regional Manager", RM_USER, "RM Person")]},
        fail_on_pid="p-bad",
    )
    assert await escalate_overdue_steps(session, now=NOW) == 1
    assert session.updates()[0]["id"] == "t-good"


async def test_candidate_query_locks_rows_and_skips_inactive_tenants() -> None:
    session = _FakeSession([])
    await escalate_overdue_steps(session, now=NOW)
    sql = session.executed[0][0]
    assert "FOR UPDATE OF to_ SKIP LOCKED" in sql
    assert "t.status = 'ACTIVE'" in sql
    assert "to_.status = 'PENDING_APPROVAL'" in sql


# ── worker wiring ────────────────────────────────────────────────────────────


def test_beat_schedules_the_escalation_task() -> None:
    from shared.outbox import worker

    entry = worker.app.conf.beat_schedule["escalate-overdue-approvals"]
    assert entry["task"] == "shared.outbox.worker.escalate_overdue_approvals"
    assert entry["schedule"] == 300
    assert "ApprovalStepEscalated" in worker.OUTBOX_HANDLERS


async def test_worker_runs_under_system_rls_and_commits() -> None:
    from shared.outbox import worker

    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = session
    with (
        patch.object(worker, "AsyncSessionLocal", return_value=ctx),
        patch.object(worker, "set_system_rls_context", new=AsyncMock()) as rls,
        patch(
            "shared.approvals.sla_escalation.escalate_overdue_steps",
            new=AsyncMock(return_value=3),
        ) as run,
    ):
        assert await worker._escalate_overdue_approvals() == 3
    rls.assert_awaited_once_with(session, "escalate_overdue_approvals")
    run.assert_awaited_once_with(session)
    session.commit.assert_awaited_once()
