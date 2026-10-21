"""Unit test for migration 072's downgrade guard: payment_line_items is
append-only (071's no_update_/no_delete_ RULEs), so downgrade() must refuse
outright when ADDON-type invoice lines exist, rather than silently dropping
the addon_price_id column (their only price reference) out from under them.

No live database connection: _refuse_if_addon_lines_exist() is called
directly with alembic.op.get_bind() mocked to return a fake bind whose
.execute(...).scalar() answers the ADDON-row count.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).resolve().parent.parent / "versions" / "072_addons.py"


def _load_072_module():
    spec = importlib.util.spec_from_file_location("migration_072_addons", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_bind(count: int) -> MagicMock:
    bind = MagicMock()
    result = MagicMock()
    result.scalar.return_value = count
    bind.execute.return_value = result
    return bind


def test_refuses_when_addon_lines_exist() -> None:
    module = _load_072_module()
    with patch.object(module.op, "get_bind", return_value=_fake_bind(3)):
        with pytest.raises(RuntimeError) as exc_info:
            module._refuse_if_addon_lines_exist()

    assert "072 downgrade blocked" in str(exc_info.value)
    assert "3 ADDON invoice lines exist" in str(exc_info.value)
    assert "append-only" in str(exc_info.value)


def test_passes_when_no_addon_lines_exist() -> None:
    module = _load_072_module()
    with patch.object(module.op, "get_bind", return_value=_fake_bind(0)):
        module._refuse_if_addon_lines_exist()  # must not raise


def test_downgrade_calls_guard_before_any_schema_change() -> None:
    """The guard must run before anything else in downgrade() — otherwise a
    blocked downgrade could still leave partial DDL applied."""
    module = _load_072_module()

    with patch.object(module.op, "get_bind", return_value=_fake_bind(5)):
        with patch.object(module.op, "execute") as mock_op_execute:
            with pytest.raises(RuntimeError):
                module.downgrade()
            mock_op_execute.assert_not_called()
