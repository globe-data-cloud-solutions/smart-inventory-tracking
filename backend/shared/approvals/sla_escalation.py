"""Timer-driven escalation of stuck transfer approval steps.

Decisions (Alex, 2026-10-25; Project doc claude/stuck-approval-escalation-scope.md):
  - A step's clock starts when the transfer is created: the step is overdue once
    created_at + sla_hours has passed. After an escalation, the next deadline runs
    from that escalation (escalated_at + sla_hours), so a step climbs one level
    per period instead of jumping straight to the top.
  - Overdue: the step moves to the holder(s) of the next position up the
    reports_to chain, skipping the transfer's creator (no self-approval). With no
    holder above, the step goes to the tenant's TA.
  - The TA is notified on every escalation (ta_user_ids on the outbox event).
  - A step held by a TA never escalates further.

Run by the escalate_overdue_approvals beat task (shared/outbox/worker.py) under
set_system_rls_context. The caller commits. Each transfer is handled in its own
SAVEPOINT, so one bad row does not hold back the rest of the batch. The step
reassignment, its audit row and its outbox event share that transaction.

Scope: transfer approval steps only (resolved_approval_steps). Adjustment
approvals have no sla_hours and are not touched.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import bindparam, text, types
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import ApprovalStepEscalatedPayload
from shared.outbox.writer import write_to_outbox
from shared.permissions.audit import audit_log

logger = logging.getLogger(__name__)

TA_POSITION_TITLE = "Tenant Admin"
ESCALATION_REASON = "SLA_EXPIRED"
BATCH_LIMIT = 200
_MAX_CHAIN_HOPS = 10

_OVERDUE_CANDIDATES_SQL = text(
    """
    SELECT to_.id, to_.tenant_id, to_.created_by, to_.created_at,
           to_.current_approval_step, to_.resolved_approval_steps
    FROM   transfer_orders to_
    JOIN   tenants t ON t.id = to_.tenant_id
    WHERE  to_.status = 'PENDING_APPROVAL'
    AND    jsonb_typeof(to_.resolved_approval_steps) = 'array'
    AND    t.is_active = true
    AND    t.status = 'ACTIVE'
    ORDER  BY to_.created_at
    LIMIT  :lim
    FOR UPDATE OF to_ SKIP LOCKED
    """
)

_PARENT_POSITION_SQL = text(
    """
    SELECT p.id, p.title, pp.user_id, u.full_name
    FROM   positions p
    LEFT JOIN personnel_positions pp
           ON pp.position_id = p.id AND pp.is_active = true
           AND pp.assignment_type = 'PRIMARY'
           AND (pp.valid_until IS NULL OR pp.valid_until >= CURRENT_DATE)
    LEFT JOIN users u ON u.id = pp.user_id AND u.is_active = true
    WHERE  p.id = (SELECT reports_to_position_id FROM positions
                   WHERE id = :pid AND tenant_id = :tid)
    AND    p.tenant_id = :tid
    """
)

_TENANT_TAS_SQL = text(
    """
    SELECT id, full_name FROM users
    WHERE  tenant_id = :tid AND system_role = 'TA' AND is_active = true
    ORDER  BY created_at
    """
)


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _load_steps(raw: Any) -> list[dict]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []


def step_due_at(step: dict, created_at: Any) -> datetime | None:
    """When the step becomes overdue, or None if it has no usable sla_hours.

    First deadline: created_at + sla_hours. After an escalation:
    sla_escalated_at + sla_hours (sla_escalated_at is only set by this module).
    """
    try:
        sla = int(step.get("sla_hours") or 0)
    except (TypeError, ValueError):
        return None
    if sla <= 0:
        return None
    base = _parse_ts(step.get("sla_escalated_at")) or _parse_ts(created_at)
    if base is None:
        return None
    return base + timedelta(hours=sla)


async def _tenant_tas(session: AsyncSession, tenant_id: str) -> list[dict[str, str]]:
    rows = (await session.execute(_TENANT_TAS_SQL, {"tid": tenant_id})).fetchall()
    return [{"user_id": str(r.id), "name": str(r.full_name or "")} for r in rows]


async def _next_holders_up(
    session: AsyncSession,
    tenant_id: str,
    position_id: str,
    exclude: set[str],
) -> tuple[str, str, list[dict[str, str]]] | None:
    """Walk reports_to from position_id; return the first position above it
    that has an active holder not in exclude, as (position_id, title, holders).
    None when the chain runs out (the caller then routes to the TA)."""
    visited: set[str] = set()
    cur = position_id
    for _ in range(_MAX_CHAIN_HOPS):
        if cur in visited:
            return None  # reports_to cycle
        visited.add(cur)
        rows = (
            await session.execute(_PARENT_POSITION_SQL, {"pid": cur, "tid": tenant_id})
        ).fetchall()
        if not rows or rows[0].id is None:
            return None  # top of the chain
        holders = [
            {"user_id": str(r.user_id), "name": str(r.full_name or "")}
            for r in rows
            if r.user_id is not None and str(r.user_id) not in exclude
        ]
        if holders:
            return str(rows[0].id), str(rows[0].title), holders
        cur = str(rows[0].id)
    return None


async def _escalate_one(
    session: AsyncSession,
    row: Any,
    now: datetime,
) -> bool:
    """Escalate the current step of one transfer if it is overdue."""
    steps = _load_steps(row.resolved_approval_steps)
    if not steps:
        return False
    idx = max(0, (row.current_approval_step or 1) - 1)
    if idx >= len(steps):
        return False
    step = steps[idx]
    if (step.get("status") or "pending") != "pending":
        return False

    tenant_id = str(row.tenant_id)
    tas = await _tenant_tas(session, tenant_id)
    ta_ids = {t["user_id"] for t in tas}

    # Stops at the TA: a step that is already on a TA never escalates further.
    assigned = str(step.get("assigned_to_user_id") or "")
    if step.get("escalated_to_ta") or (assigned and assigned in ta_ids):
        return False

    due = step_due_at(step, row.created_at)
    if due is None or now < due:
        return False

    creator = str(row.created_by) if row.created_by else ""
    exclude = {creator} if creator else set()
    from_pos = step.get("sla_escalation_position_id") or step.get("position_id")
    target = (
        await _next_holders_up(session, tenant_id, str(from_pos), exclude) if from_pos else None
    )

    if target is not None:
        to_pos_id: str | None = target[0]
        to_title = target[1]
        holders = target[2]
        to_ta = False
    else:
        holders = [t for t in tas if t["user_id"] != creator]
        if not holders:
            logger.warning(
                "escalate_overdue_approvals: transfer %s step %s is overdue but tenant %s "
                "has no TA to receive it; left in place",
                row.id,
                idx + 1,
                tenant_id,
            )
            return False
        to_pos_id = None
        to_title = TA_POSITION_TITLE
        to_ta = True

    from_title = step.get("position_title")
    history = list(step.get("sla_escalation_history") or [])
    history.append(
        {
            "at": now.isoformat(),
            "due_at": due.isoformat(),
            "reason": ESCALATION_REASON,
            "from_position_title": from_title,
            "from_user_id": assigned or None,
            "to_position_title": to_title,
            "to_user_ids": [h["user_id"] for h in holders],
            "to_ta": to_ta,
        }
    )
    step.update(
        {
            "position_title": to_title,
            "assigned_to_user_id": holders[0]["user_id"],
            "assigned_to_name": holders[0]["name"],
            "all_holders": holders,
            "holder_count": len(holders),
            "is_vacant": False,
            # escalated=True also lets any TA approve the step (see
            # inventory_service._check_can_approve), which is how "TA is
            # notified to move the process" becomes something the TA can act on.
            "escalated": True,
            "escalated_to_ta": to_ta,
            "sla_escalated_at": now.isoformat(),
            "sla_escalation_position_id": to_pos_id,
            "sla_escalation_history": history,
        }
    )
    steps[idx] = step

    await session.execute(
        text(
            "UPDATE transfer_orders SET resolved_approval_steps = :steps, updated_at = now() "
            "WHERE id = :id AND tenant_id = :tid"
        ).bindparams(bindparam("steps", type_=types.JSON)),
        {"steps": steps, "id": str(row.id), "tid": tenant_id},
    )

    level = len(history)
    await audit_log(
        SimpleNamespace(user_id=None, tenant_id=tenant_id, role="SYS"),
        "transfer:approval_escalated",
        {
            "resource_type": "transfer",
            "resource_id": str(row.id),
            "tenant_id": tenant_id,
            "step": idx + 1,
            "escalation": level,
            "to_ta": to_ta,
        },
        "GRANTED",
        (
            f"Step {idx + 1} passed its {step.get('sla_hours')}h limit; moved from "
            f"'{from_title or 'unassigned'}' to '{to_title}'"
        ),
        db=session,
    )
    await write_to_outbox(
        session,
        tenant_id,
        "ApprovalStepEscalated",
        ApprovalStepEscalatedPayload(
            transfer_order_id=str(row.id),
            step=idx + 1,
            sla_hours=int(step.get("sla_hours") or 0),
            due_at=due.isoformat(),
            from_position_title=from_title,
            to_position_title=to_title,
            to_user_ids=[h["user_id"] for h in holders],
            ta_user_ids=sorted(ta_ids),
            escalated_to_ta=to_ta,
        ),
        idempotency_key=f"approval-escalation:{row.id}:{idx + 1}:{level}",
    )
    return True


async def escalate_overdue_steps(
    session: AsyncSession,
    now: datetime | None = None,
    limit: int = BATCH_LIMIT,
) -> int:
    """Escalate every overdue current step in one batch. Returns how many moved.

    The caller sets the system RLS context and commits.
    """
    now = now or datetime.now(UTC)
    rows = (await session.execute(_OVERDUE_CANDIDATES_SQL, {"lim": limit})).fetchall()
    moved = 0
    for row in rows:
        try:
            async with session.begin_nested():
                if await _escalate_one(session, row, now):
                    moved += 1
        except Exception:  # one bad row must not stop the batch
            logger.exception("escalate_overdue_approvals: transfer %s failed; skipped", row.id)
    return moved
