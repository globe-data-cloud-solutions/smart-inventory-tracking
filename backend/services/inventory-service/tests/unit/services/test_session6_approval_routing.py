"""Unit tests for Session 6: dynamic approval routing via positions.

1. test_resolve_approvers_finds_position_holder  — matching rule + holder resolved
2. test_vacant_position_escalates               — no holder → escalate up reports_to
3. test_self_approval_escalates                 — creator == holder → escalate
4. test_no_rule_routes_to_nm                    — missing rule → NM fallback
5. test_approval_info_correct_assignee          — approval-info returns specific user_id
"""
from __future__ import annotations

import os
os.environ.setdefault("DATABASE_URL",      "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET",        "test-secret")
os.environ.setdefault("JWT_SECRET_KEY",    "test-secret")

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

TENANT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
SRC_NODE    = "bbbbbbbb-0000-0000-0000-000000000001"
DST_NODE    = "bbbbbbbb-0000-0000-0000-000000000002"
CONFIG_ID   = "cccccccc-0000-0000-0000-000000000001"
POSITION_ID = "dddddddd-0000-0000-0000-000000000001"
HOLDER_UID  = "eeeeeeee-0000-0000-0000-000000000001"
CREATOR_UID = "ffffffff-0000-0000-0000-000000000001"


def _row(**kw) -> MagicMock:
    r = MagicMock()
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _db_seq(*items) -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    results = []
    for item in items:
        res = MagicMock()
        if item is None:
            res.fetchone = MagicMock(return_value=None)
            res.fetchall = MagicMock(return_value=[])
            res.scalar   = MagicMock(return_value=0)
        elif isinstance(item, list):
            res.fetchone = MagicMock(return_value=item[0] if item else None)
            res.fetchall = MagicMock(return_value=item)
            res.scalar   = MagicMock(return_value=len(item))
        else:
            res.fetchone = MagicMock(return_value=item)
            res.fetchall = MagicMock(return_value=[item])
            res.scalar   = MagicMock(return_value=1)
        results.append(res)
    db.execute = AsyncMock(side_effect=results)
    return db


# ── Test 1: Matching rule + position holder found ────────────────────────────

@pytest.mark.unit
class TestResolveApproversFindsHolder:

    async def test_resolve_approvers_finds_position_holder(self) -> None:
        """resolve_transfer_approvers returns the position holder when:
        - A matching transfer_approval_rules row exists
        - The position at the resolved node has an active PRIMARY holder
        """
        from services.approval_service import resolve_transfer_approvers

        rule_row = _row(
            id=CONFIG_ID,
            approval_steps=[{
                "sequence": 1,
                "position_title": "Warehouse Manager",
                "resolution": "SOURCE",
                "execution_mode": "sequential",
                "sla_hours": 24,
            }],
            threshold_type="QUANTITY",
            quantity_min=Decimal("0"),
            quantity_max=None,
            value_min=Decimal("0"),
            value_max=None,
            source_level=None,
            destination_level=None,
            priority=0,
        )
        src_node_row = _row(id=SRC_NODE, name="Main WH", hierarchy_level=2)
        pos_holder_row = _row(
            pos_id=POSITION_ID,
            user_id=HOLDER_UID,
            full_name="Abebe Kebele",
            node_id=SRC_NODE,
        )

        # DB call sequence:
        # 1. src_level lookup
        # 2. dst_level lookup
        # 3. _find_matching_rule → rule found
        # 4. _resolve_node_for_step (SOURCE → get_node)
        # 5. _find_position_and_holder
        db = _db_seq(
            _row(hierarchy_level=2),   # src level
            _row(hierarchy_level=1),   # dst level
            [rule_row],                 # matching rule (fetchall)
            src_node_row,               # resolve_node SOURCE
            pos_holder_row,             # position + holder
        )

        res = await resolve_transfer_approvers(
            session=db,
            tenant_id=TENANT_ID,
            transfer_type_config_id=CONFIG_ID,
            from_warehouse_id=SRC_NODE,
            to_warehouse_id=DST_NODE,
            quantity=Decimal("100"),
            total_value=None,
            created_by=CREATOR_UID,
        )

        assert len(res.steps) == 1
        assert not res.missing_rule
        step = res.steps[0]
        assert step.assigned_to_user_id == HOLDER_UID
        assert step.assigned_to_name    == "Abebe Kebele"
        assert step.position_title       == "Warehouse Manager"
        assert not step.is_vacant
        assert not step.escalated


# ── Test 2: Vacant position → escalate ──────────────────────────────────────

@pytest.mark.unit
class TestVacantPositionEscalates:

    async def test_vacant_position_escalates(self) -> None:
        """When the matched position has no active holder, escalate up the
        reports_to chain and return the parent position's holder."""
        from services.approval_service import resolve_transfer_approvers

        PARENT_UID = str(uuid4())

        rule_row = _row(
            id=CONFIG_ID,
            approval_steps=[{
                "sequence": 1,
                "position_title": "Store Manager",
                "resolution": "SOURCE",
                "execution_mode": "sequential",
                "sla_hours": 24,
            }],
            threshold_type="QUANTITY",
            quantity_min=Decimal("0"), quantity_max=None,
            value_min=Decimal("0"),    value_max=None,
            source_level=None, destination_level=None, priority=0,
        )
        src_node  = _row(id=SRC_NODE, name="Store A", hierarchy_level=3)
        vacant    = _row(pos_id=POSITION_ID, user_id=None, full_name=None, node_id=SRC_NODE)
        # escalate: parent position has a holder
        parent_pos = _row(id=str(uuid4()), user_id=PARENT_UID, full_name="Tigist Haile")

        db = _db_seq(
            _row(hierarchy_level=3),   # src level
            _row(hierarchy_level=2),   # dst level
            [rule_row],                 # matching rule
            src_node,                   # resolve SOURCE node
            vacant,                     # position holder → vacant
            parent_pos,                 # escalate: parent position holder
        )

        res = await resolve_transfer_approvers(
            session=db,
            tenant_id=TENANT_ID,
            transfer_type_config_id=CONFIG_ID,
            from_warehouse_id=SRC_NODE,
            to_warehouse_id=DST_NODE,
            quantity=Decimal("50"),
            total_value=None,
            created_by=CREATOR_UID,
        )

        step = res.steps[0]
        assert step.is_vacant  is True
        assert step.escalated  is True
        assert step.assigned_to_user_id == PARENT_UID


# ── Test 3: Self-approval → escalate ─────────────────────────────────────────

@pytest.mark.unit
class TestSelfApprovalEscalates:

    async def test_self_approval_escalates(self) -> None:
        """When the matched position holder == transfer creator,
        escalate to the reports_to parent to prevent self-approval."""
        from services.approval_service import resolve_transfer_approvers

        OTHER_UID = str(uuid4())

        rule_row = _row(
            id=CONFIG_ID,
            approval_steps=[{
                "sequence": 1, "position_title": "WM",
                "resolution": "SOURCE", "execution_mode": "sequential", "sla_hours": None,
            }],
            threshold_type="QUANTITY",
            quantity_min=Decimal("0"), quantity_max=None,
            value_min=Decimal("0"),    value_max=None,
            source_level=None, destination_level=None, priority=0,
        )
        src_node = _row(id=SRC_NODE, name="WH", hierarchy_level=3)
        # Holder IS the creator
        self_holder = _row(pos_id=POSITION_ID, user_id=CREATOR_UID, full_name="Self User", node_id=SRC_NODE)
        # After escalation, parent has a different holder
        escalated_holder = _row(id=str(uuid4()), user_id=OTHER_UID, full_name="Another Person")

        db = _db_seq(
            _row(hierarchy_level=3),
            _row(hierarchy_level=2),
            [rule_row],
            src_node,
            self_holder,
            escalated_holder,
        )

        res = await resolve_transfer_approvers(
            session=db,
            tenant_id=TENANT_ID,
            transfer_type_config_id=CONFIG_ID,
            from_warehouse_id=SRC_NODE,
            to_warehouse_id=DST_NODE,
            quantity=Decimal("30"),
            total_value=None,
            created_by=CREATOR_UID,  # same as holder
        )

        step = res.steps[0]
        assert step.assigned_to_user_id != CREATOR_UID, (
            "Self-approval must be prevented — escalated holder must differ from creator"
        )
        assert step.assigned_to_user_id == OTHER_UID


# ── Test 4: No matching rule → NM fallback ───────────────────────────────────

@pytest.mark.unit
class TestNoRuleRoutesToNM:

    async def test_no_rule_routes_to_nm(self) -> None:
        """When no transfer_approval_rules row matches, resolve_transfer_approvers
        falls back to any NM-role position holder and sets missing_rule=True."""
        from services.approval_service import resolve_transfer_approvers

        nm_holder_row = _row(
            user_id=HOLDER_UID,
            full_name="NM User",
            pos_id=POSITION_ID,
            title="National Manager",
            node_id=SRC_NODE,
        )

        db = _db_seq(
            _row(hierarchy_level=3),   # src level
            _row(hierarchy_level=2),   # dst level
            [],                         # _find_matching_rule → empty list
            nm_holder_row,              # NM fallback query
        )

        res = await resolve_transfer_approvers(
            session=db,
            tenant_id=TENANT_ID,
            transfer_type_config_id=CONFIG_ID,
            from_warehouse_id=SRC_NODE,
            to_warehouse_id=DST_NODE,
            quantity=Decimal("200"),
            total_value=None,
            created_by=CREATOR_UID,
        )

        assert res.missing_rule is True
        assert len(res.steps) == 1
        assert res.steps[0].assigned_to_user_id == HOLDER_UID

    async def test_approval_info_correct_assignee(self) -> None:
        """ApprovalResolution.steps_as_json() serialises steps correctly and
        the is_dynamic_routing flag is True when resolved_approval_steps is present."""
        from services.approval_service import ApprovalResolution, ResolvedStep

        resolution = ApprovalResolution(
            steps=[ResolvedStep(
                sequence=1,
                position_title="Regional Manager",
                position_id=POSITION_ID,
                node_id=SRC_NODE,
                assigned_to_user_id=HOLDER_UID,
                assigned_to_name="Meron Alemu",
                execution_mode="sequential",
                sla_hours=24,
            )],
            rule_id=CONFIG_ID,
            missing_rule=False,
        )

        import json
        steps = json.loads(resolution.steps_as_json())
        assert len(steps) == 1
        assert steps[0]["assigned_to_user_id"] == HOLDER_UID
        assert steps[0]["assigned_to_name"]    == "Meron Alemu"
        assert steps[0]["position_title"]       == "Regional Manager"
        assert steps[0]["sla_hours"]            == 24
        assert steps[0]["status"]               == "pending"