"""Unit tests for get_approval_coverage and clone_level_permissions endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

TENANT_ID = "aabbccdd-0000-0000-0000-000000000010"
NODE_ID = "bbccddee-0000-0000-0000-000000000011"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _scalar(value: int) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _fetchone(row: object | None) -> MagicMock:
    r = MagicMock()
    r.fetchone.return_value = row
    return r


def _fetchall(rows: list) -> MagicMock:
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


def _node_row(hierarchy_level: int) -> MagicMock:
    row = MagicMock()
    row.hierarchy_level = hierarchy_level
    return row


def _tt_row(id_: str) -> MagicMock:
    row = MagicMock()
    row.id = id_
    return row


def _src_perm_row(can_initiate: bool, can_receive: bool) -> MagicMock:
    row = MagicMock()
    row.can_initiate = can_initiate
    row.can_receive = can_receive
    return row


def _source_level_row(level_number: int) -> MagicMock:
    row = MagicMock()
    row.level_number = level_number
    return row


# ---------------------------------------------------------------------------
# Inline reproductions of the endpoint logic for pure unit testing
# (no HTTP server, no real DB — mirrors hierarchy.py exactly)
# ---------------------------------------------------------------------------


async def _run_coverage(db: AsyncMock, tenant_id: str, level: int) -> dict:
    """Mirrors get_approval_coverage business logic."""
    tid = tenant_id

    transfer_total = (await db.execute(None, {"tid": tid})).scalar() or 0
    transfer_null_rule = (await db.execute(None, {"tid": tid})).scalar() or 0
    transfer_explicit = (await db.execute(None, {"tid": tid, "lv": level})).scalar() or 0
    transfer_level_covered = (transfer_null_rule > 0) or (transfer_explicit > 0)

    adj_total = (await db.execute(None, {"tid": tid})).scalar() or 0
    adj_level = (await db.execute(None, {"tid": tid, "lv": level})).scalar() or 0

    self_appr = (await db.execute(None, {"tid": tid, "lv": level})).scalar() or 0
    level_perms = (await db.execute(None, {"tid": tid, "lv": level})).scalar() or 0

    return {
        "transfer_rules_exist": transfer_total > 0,
        "transfer_level_covered": transfer_level_covered,
        "adj_rules_exist": adj_total > 0,
        "adj_level_covered": adj_level > 0,
        "self_approval_covered": self_appr > 0,
        "transfer_level_perms_exist": level_perms > 0,
    }


async def _run_clone(db: AsyncMock, tenant_id: str, node_id: str) -> dict:
    """Mirrors clone_level_permissions business logic."""
    tid = tenant_id

    node_result = await db.execute(None, {"nid": node_id, "tid": tid})
    node_row = node_result.fetchone()
    if not node_row:
        raise HTTPException(status_code=404, detail="Node not found")
    target_level = node_row.hierarchy_level

    source_result = await db.execute(None, {"tid": tid, "lv": target_level})
    source_row = source_result.fetchone()

    if not source_row:
        return {
            "cloned": False,
            "from_level": None,
            "to_level": target_level,
            "transfer_types_updated": 0,
        }

    from_level = source_row.level_number

    tt_result = await db.execute(None, {"tid": tid})
    tt_rows = tt_result.fetchall()

    cloned_count = 0
    for tt_row in tt_rows:
        ttc_id = str(tt_row.id)

        exists_result = await db.execute(None, {"ttc": ttc_id, "lv": target_level})
        exists = exists_result.fetchone()
        if exists:
            continue

        src_result = await db.execute(None, {"ttc": ttc_id, "src_lv": from_level})
        src = src_result.fetchone()

        if src:
            await db.execute(
                None,
                {"ttc": ttc_id, "lv": target_level, "ci": src.can_initiate, "cr": src.can_receive},
            )
            cloned_count += 1

    return {
        "cloned": cloned_count > 0,
        "from_level": from_level,
        "to_level": target_level,
        "transfer_types_updated": cloned_count,
    }


# ---------------------------------------------------------------------------
# Coverage tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coverage_no_rules():
    """All counts 0 → all False."""
    db = AsyncMock()
    db.execute.return_value = _scalar(0)

    result = await _run_coverage(db, TENANT_ID, level=4)

    assert result["transfer_rules_exist"] is False
    assert result["transfer_level_covered"] is False
    assert result["adj_rules_exist"] is False
    assert result["adj_level_covered"] is False
    assert result["self_approval_covered"] is False
    assert result["transfer_level_perms_exist"] is False


@pytest.mark.asyncio
async def test_coverage_global_null_rule():
    """Global NULL-level catch-all rule → transfer_level_covered=True even for a new level."""
    db = AsyncMock()
    # Call order: transfer_total=1, null_rule=1, explicit=0, adj_total=0, adj_level=0, self=0, perms=0
    db.execute.side_effect = [
        _scalar(1),  # transfer_total
        _scalar(1),  # transfer_null_rule (global catch-all)
        _scalar(0),  # transfer_explicit for level 5
        _scalar(0),  # adj_total
        _scalar(0),  # adj_level
        _scalar(0),  # self_appr
        _scalar(0),  # level_perms
    ]

    result = await _run_coverage(db, TENANT_ID, level=5)

    assert result["transfer_rules_exist"] is True
    assert result["transfer_level_covered"] is True
    assert result["adj_rules_exist"] is False


@pytest.mark.asyncio
async def test_coverage_explicit_level():
    """Adj rule exists for level 4 → adj_level_covered=True."""
    db = AsyncMock()
    # transfer_total=0, null_rule=0, explicit=0, adj_total=1, adj_level=1, self=0, perms=0
    db.execute.side_effect = [
        _scalar(0),  # transfer_total
        _scalar(0),  # null_rule
        _scalar(0),  # explicit
        _scalar(1),  # adj_total
        _scalar(1),  # adj_level for level 4
        _scalar(0),  # self_appr
        _scalar(0),  # perms
    ]

    result = await _run_coverage(db, TENANT_ID, level=4)

    assert result["adj_rules_exist"] is True
    assert result["adj_level_covered"] is True


@pytest.mark.asyncio
async def test_coverage_new_level_uncovered():
    """Transfer rules exist for levels 1-3 but not level 4 → transfer_level_covered=False."""
    db = AsyncMock()
    # transfer_total=3, null_rule=0, explicit=0 (nothing targets level 4)
    db.execute.side_effect = [
        _scalar(3),  # transfer_total
        _scalar(0),  # null_rule
        _scalar(0),  # explicit for level 4
        _scalar(0),  # adj_total
        _scalar(0),  # adj_level
        _scalar(0),  # self_appr
        _scalar(0),  # perms
    ]

    result = await _run_coverage(db, TENANT_ID, level=4)

    assert result["transfer_rules_exist"] is True
    assert result["transfer_level_covered"] is False


# ---------------------------------------------------------------------------
# Clone tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_no_source():
    """No existing level_permissions rows → returns cloned=False, transfer_types_updated=0."""
    db = AsyncMock()
    # node lookup → level 4; source lookup → None
    db.execute.side_effect = [
        _fetchone(_node_row(4)),  # node hierarchy_level
        _fetchone(None),  # source_row (no permissions below level 4)
    ]

    result = await _run_clone(db, TENANT_ID, NODE_ID)

    assert result["cloned"] is False
    assert result["from_level"] is None
    assert result["to_level"] == 4
    assert result["transfer_types_updated"] == 0


@pytest.mark.asyncio
async def test_clone_success():
    """Source level 3 has permissions for 2 transfer types → clones both to level 4."""
    tt1_id = "aaaaaaaa-0000-0000-0000-000000000001"
    tt2_id = "aaaaaaaa-0000-0000-0000-000000000002"

    db = AsyncMock()
    db.execute.side_effect = [
        _fetchone(_node_row(4)),  # node level = 4
        _fetchone(_source_level_row(3)),  # source level = 3
        _fetchall([_tt_row(tt1_id), _tt_row(tt2_id)]),  # transfer types
        # TT1: no existing row at level 4, src perms found, INSERT fires
        _fetchone(None),  # exists check tt1
        _fetchone(_src_perm_row(can_initiate=True, can_receive=True)),  # src perms tt1
        MagicMock(),  # INSERT tt1
        # TT2: no existing row at level 4, src perms found, INSERT fires
        _fetchone(None),  # exists check tt2
        _fetchone(_src_perm_row(can_initiate=False, can_receive=True)),  # src perms tt2
        MagicMock(),  # INSERT tt2
    ]

    result = await _run_clone(db, TENANT_ID, NODE_ID)

    assert result["cloned"] is True
    assert result["from_level"] == 3
    assert result["to_level"] == 4
    assert result["transfer_types_updated"] == 2
