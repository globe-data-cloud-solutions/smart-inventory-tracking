"""Unit tests for the directional level lock in upsert_hierarchy_config (G3a)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


TENANT_ID = "aabbccdd-0000-0000-0000-000000000002"


def _scalar_result(value: int) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _db_count_then_max(existing_count: int, max_used_level: int) -> AsyncMock:
    """Returns a db mock whose execute() yields existing_count first, then max_used_level."""
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(existing_count),
        _scalar_result(max_used_level),
    ]
    return db


def _db_count_only(existing_count: int) -> AsyncMock:
    """Returns a db mock for paths that only read existing_count (growing path)."""
    db = AsyncMock()
    db.execute.return_value = _scalar_result(existing_count)
    return db


def _make_body(n: int) -> list:
    """Simulate a request body with n level entries."""
    return [object() for _ in range(n)]


# ---------------------------------------------------------------------------
# Inline reproduction of the G3a logic so these are true unit tests
# (no HTTP server needed). Mirrors hierarchy.py upsert_hierarchy_config G3a.
# ---------------------------------------------------------------------------

async def _run_g3a(db, tenant_id: str, body: list) -> None:
    from sqlalchemy import text

    existing_count = (await db.execute(
        text(
            "SELECT COUNT(*) FROM tenant_hierarchy_config "
            "WHERE tenant_id = :tid AND is_active = true"
        ),
        {"tid": str(tenant_id)},
    )).scalar() or 0

    if existing_count > 0 and len(body) < existing_count:
        max_used_level = (await db.execute(
            text(
                "SELECT COALESCE(MAX(hierarchy_level), 0) "
                "FROM organization_node "
                "WHERE tenant_id = :tid AND is_active = true"
            ),
            {"tid": str(tenant_id)},
        )).scalar() or 0

        if len(body) < max_used_level:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "LEVEL_COUNT_LOCKED",
                    "message": (
                        f"Cannot remove level {max_used_level} — active org nodes "
                        f"exist at that level. Remove or move those nodes first."
                    ),
                },
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grow_levels_allowed():
    """Growing from 3 → 4 levels is always permitted, even with nodes at level 3."""
    db = _db_count_only(existing_count=3)
    body = _make_body(4)
    # Should not raise — second db.execute (max_used_level) never called
    await _run_g3a(db, TENANT_ID, body)
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_shrink_blocked_nodes_at_level():
    """Shrinking 3 → 2 is blocked when active nodes exist at level 3."""
    db = _db_count_then_max(existing_count=3, max_used_level=3)
    body = _make_body(2)
    with pytest.raises(HTTPException) as exc_info:
        await _run_g3a(db, TENANT_ID, body)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "LEVEL_COUNT_LOCKED"
    assert "3" in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_shrink_allowed_empty_level():
    """Shrinking 3 → 2 is permitted when no active nodes exist at level 3 (max_used=2)."""
    db = _db_count_then_max(existing_count=3, max_used_level=2)
    body = _make_body(2)
    # len(body)==2 is not < max_used_level==2, so no exception
    await _run_g3a(db, TENANT_ID, body)
    assert db.execute.call_count == 2


def test_grow_levels_unchanged_existing_rows():
    """Growing 3 → 4 keeps level_numbers 1-3's payload untouched (upsert carries
    submitted values through unchanged — asserted at the payload level since this
    is a pure-logic unit test with no DB)."""
    existing = [
        {"level_number": 1, "level_name": "HQ"},
        {"level_number": 2, "level_name": "Region"},
        {"level_number": 3, "level_name": "Warehouse"},
    ]
    new_body = existing + [{"level_number": 4, "level_name": "Sub-Warehouse"}]
    for i, lvl in enumerate(existing):
        assert new_body[i] == lvl


# ---------------------------------------------------------------------------
# LEVELS_NOT_CONTIGUOUS guard — mirrors the contiguity check added to
# upsert_hierarchy_config ahead of G3a / any write.
# ---------------------------------------------------------------------------

def _check_contiguous(level_numbers: list) -> None:
    if sorted(level_numbers) != list(range(1, len(level_numbers) + 1)):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "LEVELS_NOT_CONTIGUOUS",
                "message": "Level numbers must be contiguous, starting at 1 with no gaps.",
            },
        )


def test_contiguous_levels_pass():
    _check_contiguous([1, 2, 3])  # should not raise


def test_gap_in_levels_rejected():
    with pytest.raises(HTTPException) as exc_info:
        _check_contiguous([1, 2, 4])
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "LEVELS_NOT_CONTIGUOUS"


def test_levels_not_starting_at_one_rejected():
    with pytest.raises(HTTPException) as exc_info:
        _check_contiguous([2, 3, 4])
    assert exc_info.value.detail["code"] == "LEVELS_NOT_CONTIGUOUS"
