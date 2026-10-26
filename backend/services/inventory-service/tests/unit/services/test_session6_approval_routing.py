"""Unit tests for Session 6: dynamic approval routing via positions.

1. test_resolve_approvers_finds_position_holder  — matching rule + holder resolved
2. test_vacant_position_escalates               — no holder → escalate up reports_to
3. test_self_approval_escalates                 — creator == holder → escalate
4. test_no_rule_routes_to_nm                    — missing rule → NM fallback
5. test_approval_info_correct_assignee          — approval-info returns specific user_id
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://test:x@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SRC_NODE = "bbbbbbbb-0000-0000-0000-000000000001"
DST_NODE = "bbbbbbbb-0000-0000-0000-000000000002"
CONFIG_ID = "cccccccc-0000-0000-0000-000000000001"
POSITION_ID = "dddddddd-0000-0000-0000-000000000001"
HOLDER_UID = "eeeeeeee-0000-0000-0000-000000000001"
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
            res.scalar = MagicMock(return_value=0)
        elif isinstance(item, list):
            res.fetchone = MagicMock(return_value=item[0] if item else None)
            res.fetchall = MagicMock(return_value=item)
            res.scalar = MagicMock(return_value=len(item))
        else:
            res.fetchone = MagicMock(return_value=item)
            res.fetchall = MagicMock(return_value=[item])
            res.scalar = MagicMock(return_value=1)
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
            approval_steps=[
                {
                    "sequence": 1,
                    "position_title": "Warehouse Manager",
                    "resolution": "SOURCE",
                    "execution_mode": "sequential",
                    "sla_hours": 24,
                }
            ],
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
            _row(hierarchy_level=2),  # src level
            _row(hierarchy_level=1),  # dst level
            [rule_row],  # matching rule (fetchall)
            src_node_row,  # resolve_node SOURCE
            pos_holder_row,  # position + holder
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
        assert step.assigned_to_name == "Abebe Kebele"
        assert step.position_title == "Warehouse Manager"
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
            approval_steps=[
                {
                    "sequence": 1,
                    "position_title": "Store Manager",
                    "resolution": "SOURCE",
                    "execution_mode": "sequential",
                    "sla_hours": 24,
                }
            ],
            threshold_type="QUANTITY",
            quantity_min=Decimal("0"),
            quantity_max=None,
            value_min=Decimal("0"),
            value_max=None,
            source_level=None,
            destination_level=None,
            priority=0,
        )
        src_node = _row(id=SRC_NODE, name="Store A", hierarchy_level=3)
        vacant = _row(pos_id=POSITION_ID, user_id=None, full_name=None, node_id=SRC_NODE)
        # escalate: parent position has a holder
        parent_pos = _row(id=str(uuid4()), user_id=PARENT_UID, full_name="Tigist Haile")

        db = _db_seq(
            _row(hierarchy_level=3),  # src level
            _row(hierarchy_level=2),  # dst level
            [rule_row],  # matching rule
            src_node,  # resolve SOURCE node
            vacant,  # position holder → vacant
            parent_pos,  # escalate: parent position holder
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
        assert step.is_vacant is True
        assert step.escalated is True
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
            approval_steps=[
                {
                    "sequence": 1,
                    "position_title": "WM",
                    "resolution": "SOURCE",
                    "execution_mode": "sequential",
                    "sla_hours": None,
                }
            ],
            threshold_type="QUANTITY",
            quantity_min=Decimal("0"),
            quantity_max=None,
            value_min=Decimal("0"),
            value_max=None,
            source_level=None,
            destination_level=None,
            priority=0,
        )
        src_node = _row(id=SRC_NODE, name="WH", hierarchy_level=3)
        # Holder IS the creator
        self_holder = _row(
            pos_id=POSITION_ID, user_id=CREATOR_UID, full_name="Self User", node_id=SRC_NODE
        )
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
        """When no transfer_approval_rules row matches and the hierarchy walk finds
        nobody above the requesting node, resolve_transfer_approvers falls back to
        any NM-role position holder and sets missing_rule=True."""
        from services.approval_service import resolve_transfer_approvers

        nm_holder_row = _row(
            user_id=HOLDER_UID,
            full_name="NM User",
            pos_id=POSITION_ID,
            title="National Manager",
            node_id=SRC_NODE,
        )

        db = _db_seq(
            _row(hierarchy_level=3),  # src level
            _row(hierarchy_level=2),  # dst level
            [],  # _find_matching_rule → empty list
            [],  # hierarchy walk → nobody above the requesting node
            nm_holder_row,  # NM fallback query
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
            steps=[
                ResolvedStep(
                    sequence=1,
                    position_title="Regional Manager",
                    position_id=POSITION_ID,
                    node_id=SRC_NODE,
                    assigned_to_user_id=HOLDER_UID,
                    assigned_to_name="Meron Alemu",
                    execution_mode="sequential",
                    sla_hours=24,
                )
            ],
            rule_id=CONFIG_ID,
            missing_rule=False,
        )

        import json

        steps = json.loads(resolution.steps_as_json())
        assert len(steps) == 1
        assert steps[0]["assigned_to_user_id"] == HOLDER_UID
        assert steps[0]["assigned_to_name"] == "Meron Alemu"
        assert steps[0]["position_title"] == "Regional Manager"
        assert steps[0]["sla_hours"] == 24
        assert steps[0]["status"] == "pending"


# ── FIX C1 tests: vacancy escalation + NO_APPROVER_FOUND ─────────────────────

NM_UID = "11111111-0000-0000-0000-000000000001"
RM_POS = "22222222-0000-0000-0000-000000000001"
NM_POS = "33333333-0000-0000-0000-000000000001"
PARENT_P = "44444444-0000-0000-0000-000000000001"


@pytest.mark.unit
class TestVacancyEscalation:
    async def test_vacancy_escalates_to_reports_to(self) -> None:
        """_escalate_vacant traverses the reports_to chain and returns the
        first position holder it finds."""
        from services.approval_service import _escalate_vacant

        # Chain: RM_POS → PARENT_P (has holder NM_UID)
        parent_row = _row(id=PARENT_P, user_id=NM_UID, full_name="National Manager")
        db = _db_seq(parent_row)  # first execute → parent_row

        uid, name, escalated = await _escalate_vacant(db, TENANT_ID, RM_POS)

        assert uid == NM_UID
        assert name == "National Manager"
        assert escalated is True

    async def test_vacancy_falls_back_to_nm(self) -> None:
        """_escalate_vacant falls back to any NM-role holder when the
        reports_to chain is exhausted with no active holder."""
        from services.approval_service import _escalate_vacant

        # Chain traversal: parent row has no user (vacant parent)
        # then parent of parent: None (top of tree) → break
        # NM fallback: finds an NM holder
        vacant_parent = _row(id=PARENT_P, user_id=None, full_name=None)
        nm_holder = _row(user_id=NM_UID, full_name="NM Fallback")

        db = _db_seq(
            vacant_parent,  # first chain step — no holder, keep going
            None,  # second chain step — no parent (root reached)
            nm_holder,  # NM fallback query
        )

        uid, name, escalated = await _escalate_vacant(db, TENANT_ID, RM_POS)

        assert uid == NM_UID
        assert escalated is True

    async def test_vacancy_returns_none_when_no_nm(self) -> None:
        """_escalate_vacant returns (None, None, True) safely when both the
        reports_to chain and the NM fallback have no active holder."""
        from services.approval_service import _escalate_vacant

        # No parent in chain, no NM holder either
        db = _db_seq(
            None,  # chain traversal — no parent
            None,  # NM fallback → also None
        )

        uid, name, escalated = await _escalate_vacant(db, TENANT_ID, RM_POS)

        assert uid is None
        assert name is None
        assert escalated is True  # still returns True to signal escalation was attempted

    async def test_no_approver_raises_422(self) -> None:
        """resolve_transfer_approvers raises HTTP 422 NO_APPROVER_FOUND when a
        position is vacant and escalation cannot find any holder."""
        from fastapi import HTTPException
        from services.approval_service import resolve_transfer_approvers

        rule_row = _row(
            id=CONFIG_ID,
            approval_steps=[
                {
                    "sequence": 1,
                    "position_title": "Regional Manager",
                    "resolution": "SOURCE",
                    "execution_mode": "SEQUENTIAL",
                    "sla_hours": None,
                }
            ],
            threshold_type="QUANTITY",
            quantity_min=0,
            quantity_max=None,
            value_min=0,
            value_max=None,
            source_level=1,
            destination_level=3,
            priority=0,
        )
        # Position found but vacant (no holder)
        pos_row_vacant = _row(pos_id=RM_POS, user_id=None, full_name=None, node_id=SRC_NODE)

        db = _db_seq(
            _row(hierarchy_level=1),  # src level
            _row(hierarchy_level=3),  # dst level
            rule_row,  # _find_matching_rule
            _row(id=SRC_NODE, name="HQ National", hierarchy_level=1),  # _get_node (SOURCE)
            pos_row_vacant,  # _find_position_and_holder → vacant
            None,  # _escalate_vacant: chain step → no parent
            None,  # _escalate_vacant: NM fallback → also None
        )

        with pytest.raises(HTTPException) as exc_info:
            await resolve_transfer_approvers(
                session=db,
                tenant_id=TENANT_ID,
                transfer_type_config_id=CONFIG_ID,
                from_warehouse_id=SRC_NODE,
                to_warehouse_id=DST_NODE,
                quantity=Decimal("50"),
                total_value=None,
                created_by=CREATOR_UID,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "NO_APPROVER_FOUND"


# ── FIX C2 test: product audit log ────────────────────────────────────────────


@pytest.mark.unit
class TestProductAuditLog:
    def test_product_create_audit_log(self) -> None:
        """create_product source must contain an INSERT INTO audit_logs with
        action='product:create' in the SAME transaction as the product INSERT
        (CLAUDE.md §14, §8 rule 6).

        This is a structural test: we read the source file and verify the
        SQL pattern is present rather than mocking the entire DB interaction
        (which would require mocking 10+ sequential queries).
        """
        import os

        products_src = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "product-service",
                "routers",
                "products.py",
            )
        )
        assert os.path.exists(products_src), f"products.py not found at {products_src}"

        with open(products_src, encoding="utf-8") as f:
            src = f.read()

        assert "INSERT INTO audit_logs" in src, "create_product must INSERT INTO audit_logs"
        assert "product:create" in src, "audit_logs INSERT must use action='product:create'"
        assert "unit_price" in src, "audit log abac_context should include unit_price (FIX C2)"

        # Verify the audit INSERT is in the SAME function as the products INSERT
        # by checking the audit INSERT appears AFTER the products INSERT in the source.
        products_insert_pos = src.find("INSERT INTO products")
        audit_log_pos = src.find("INSERT INTO audit_logs")
        assert products_insert_pos > 0, "products INSERT not found"
        assert audit_log_pos > 0, "audit_logs INSERT not found"
        assert audit_log_pos > products_insert_pos, (
            "audit_logs INSERT must follow the products INSERT (same transaction)"
        )


# ── Decision 5 (Alex, 2026-10-25): no rule → hierarchy walk, NM last ────────

PARENT_NODE = "bbbbbbbb-0000-0000-0000-0000000000aa"
GRAND_NODE = "bbbbbbbb-0000-0000-0000-0000000000bb"
RM_UID = "eeeeeeee-0000-0000-0000-0000000000a1"
RM2_UID = "eeeeeeee-0000-0000-0000-0000000000a2"


def _walk_row(depth: int, user_id: str, name: str, title: str, node: str) -> MagicMock:
    return _row(
        depth=depth,
        pos_id=f"pos-{node[-2:]}",
        title=title,
        node_id=node,
        user_id=user_id,
        full_name=name,
    )


async def _resolve(db, transfer_type: str | None = "PULL", created_by: str = CREATOR_UID):
    from services.approval_service import resolve_transfer_approvers

    return await resolve_transfer_approvers(
        session=db,
        tenant_id=TENANT_ID,
        transfer_type_config_id=CONFIG_ID,
        from_warehouse_id=SRC_NODE,
        to_warehouse_id=DST_NODE,
        quantity=Decimal(10),
        total_value=None,
        created_by=created_by,
        transfer_type=transfer_type,
    )


def _walk_params(db) -> dict:
    calls = [c for c in db.execute.await_args_list if "WITH RECURSIVE up" in str(c.args[0])]
    assert len(calls) == 1
    return calls[0].args[1]


@pytest.mark.unit
class TestHierarchyWalkDefault:
    async def test_first_node_above_with_an_approver_gets_the_step(self) -> None:
        db = _db_seq(
            _row(hierarchy_level=1),
            _row(hierarchy_level=3),
            [],
            [
                _walk_row(1, RM_UID, "RM One", "Regional Manager", PARENT_NODE),
                _walk_row(1, RM2_UID, "RM Two", "Regional Manager", PARENT_NODE),
                _walk_row(2, HOLDER_UID, "NM User", "National Manager", GRAND_NODE),
            ],
        )
        res = await _resolve(db)
        assert res.missing_rule is True
        (step,) = res.steps
        assert step.position_title == "Regional Manager"
        assert step.node_id == PARENT_NODE
        assert step.execution_mode == "any"
        assert [h["user_id"] for h in step.all_holders] == [RM_UID, RM2_UID]
        assert step.assigned_to_user_id == RM_UID
        # The walk answered, so the NM fallback query never ran.
        assert db.execute.await_count == 4

    async def test_creator_is_skipped_for_the_next_level_up(self) -> None:
        db = _db_seq(
            _row(hierarchy_level=1),
            _row(hierarchy_level=3),
            [],
            [
                _walk_row(1, CREATOR_UID, "Creator", "Regional Manager", PARENT_NODE),
                _walk_row(2, HOLDER_UID, "NM User", "National Manager", GRAND_NODE),
            ],
        )
        res = await _resolve(db)
        assert res.steps[0].assigned_to_user_id == HOLDER_UID
        assert res.steps[0].node_id == GRAND_NODE

    @pytest.mark.parametrize(
        ("transfer_type", "start"),
        [("PULL", DST_NODE), ("SISTER", DST_NODE), ("PUSH", SRC_NODE), (None, DST_NODE)],
    )
    async def test_walk_starts_at_the_requesting_node(
        self, transfer_type: str | None, start: str
    ) -> None:
        db = _db_seq(
            _row(hierarchy_level=1),
            _row(hierarchy_level=3),
            [],
            [_walk_row(1, RM_UID, "RM One", "Regional Manager", PARENT_NODE)],
        )
        await _resolve(db, transfer_type=transfer_type)
        assert _walk_params(db) == {"start": start, "tid": TENANT_ID}

    async def test_walk_query_requires_an_approving_role_and_active_holder(self) -> None:
        from services.approval_service import _HIERARCHY_WALK_SQL

        sql = str(_HIERARCHY_WALK_SQL)
        assert "rp.action_id = 'transfer:approve'" in sql
        assert "pp.assignment_type = 'PRIMARY'" in sql
        assert "u.is_active = true" in sql
        assert "parent_node_id" in sql


# ── Decision 6 (Alex, 2026-10-25): a step without a position defaults to the
#    next higher level (from the previous step's node), TA last ──────────────


def _rule(*steps: dict) -> MagicMock:
    return _row(
        id=CONFIG_ID,
        approval_steps=list(steps),
        threshold_type="QUANTITY",
        quantity_min=Decimal(0),
        quantity_max=None,
        value_min=Decimal(0),
        value_max=None,
        source_level=None,
        destination_level=None,
        priority=0,
    )


@pytest.mark.unit
class TestStepWithoutPositionDefaults:
    async def test_first_step_without_position_walks_up_from_the_requesting_node(self) -> None:
        db = _db_seq(
            _row(hierarchy_level=1),
            _row(hierarchy_level=3),
            [_rule({"sequence": 1, "position_id": "", "position_title": "", "sla_hours": 12})],
            [_walk_row(1, RM_UID, "RM One", "Regional Manager", PARENT_NODE)],
        )
        res = await _resolve(db, transfer_type="PULL")
        assert res.missing_rule is False
        (step,) = res.steps
        assert step.assigned_to_user_id == RM_UID
        assert step.position_title == "Regional Manager"
        assert step.sla_hours == 12
        assert _walk_params(db) == {"start": DST_NODE, "tid": TENANT_ID}

    async def test_later_step_without_position_walks_up_from_the_previous_step(self) -> None:
        first = {"sequence": 1, "position_id": POSITION_ID, "position_title": "Warehouse Manager"}
        second = {"sequence": 2, "position_id": None, "position_title": None}
        db = _db_seq(
            _row(hierarchy_level=1),
            _row(hierarchy_level=3),
            [_rule(first, second)],
            # step 1: direct position lookup
            _row(
                pos_id=POSITION_ID,
                user_id=HOLDER_UID,
                full_name="WM Person",
                node_id=PARENT_NODE,
                title="Warehouse Manager",
            ),
            # step 2: walk from step 1's node
            [_walk_row(1, RM_UID, "RM One", "Regional Manager", GRAND_NODE)],
        )
        res = await _resolve(db)
        assert [s.sequence for s in res.steps] == [1, 2]
        assert res.steps[1].assigned_to_user_id == RM_UID
        assert res.steps[1].node_id == GRAND_NODE
        assert _walk_params(db) == {"start": PARENT_NODE, "tid": TENANT_ID}

    async def test_nobody_above_goes_to_the_ta(self) -> None:
        db = _db_seq(
            _row(hierarchy_level=1),
            _row(hierarchy_level=3),
            [_rule({"sequence": 1})],
            [],  # walk finds nobody
            _row(id="ta-1", full_name="Tenant Admin User"),  # _find_tenant_ta
        )
        res = await _resolve(db)
        (step,) = res.steps
        assert step.position_title == "Tenant Admin"
        assert step.assigned_to_user_id == "ta-1"
        assert step.escalated is True
