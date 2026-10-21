from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.permissions.hierarchy_service import get_descendant_node_ids

TENANT_ID = "07000007-0000-0000-0000-000000000001"
NODE_ID = "07000007-0004-0000-0000-000000000001"
CHILD_1 = "07000007-0004-0000-0000-000000000002"
CHILD_2 = "07000007-0004-0000-0000-000000000003"
GRANDCHILD = "07000007-0004-0000-0000-000000000004"


def _mock_db(
    rows: list[tuple[str]] | None = None, side_effect: Exception | None = None
) -> AsyncMock:
    db = AsyncMock()
    if side_effect is not None:
        db.execute.side_effect = side_effect
    else:
        result = MagicMock()
        result.fetchall.return_value = rows or []
        db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_own_node_always_included():
    db = _mock_db(rows=[])
    result = await get_descendant_node_ids(db, TENANT_ID, NODE_ID)
    assert result == {NODE_ID}


@pytest.mark.asyncio
async def test_single_node_no_children():
    db = _mock_db(rows=[(NODE_ID,)])
    result = await get_descendant_node_ids(db, TENANT_ID, NODE_ID)
    assert result == {NODE_ID}


@pytest.mark.asyncio
async def test_node_with_direct_children():
    db = _mock_db(rows=[(NODE_ID,), (CHILD_1,), (CHILD_2,)])
    result = await get_descendant_node_ids(db, TENANT_ID, NODE_ID)
    assert result == {NODE_ID, CHILD_1, CHILD_2}


@pytest.mark.asyncio
async def test_node_with_grandchildren():
    db = _mock_db(rows=[(NODE_ID,), (CHILD_1,), (GRANDCHILD,)])
    result = await get_descendant_node_ids(db, TENANT_ID, NODE_ID)
    assert result == {NODE_ID, CHILD_1, GRANDCHILD}


@pytest.mark.asyncio
async def test_db_error_fails_open():
    db = _mock_db(side_effect=Exception("connection lost"))
    result = await get_descendant_node_ids(db, TENANT_ID, NODE_ID)
    assert result == {NODE_ID}


@pytest.mark.asyncio
async def test_none_node_id():
    db = _mock_db(rows=[])
    result = await get_descendant_node_ids(db, TENANT_ID, None)
    assert result == {"None"}
