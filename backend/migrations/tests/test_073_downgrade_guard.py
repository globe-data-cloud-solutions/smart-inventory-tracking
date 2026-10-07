"""Unit test for migration 073's downgrade guard: payments is never deleted
(CLAUDE.md §15), so downgrade() must refuse outright when any
invoice_kind='PRORATION' row exists, rather than silently dropping the
column that distinguishes it from a normal PERIOD invoice.

No live database connection: _refuse_if_proration_invoices_exist() is called
directly with alembic.op.get_bind() mocked to return a fake bind whose
.execute(...).scalar() answers the PRORATION-row count.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).resolve().parent.parent / "versions" / "073_proration.py"


def _load_073_module():
    spec = importlib.util.spec_from_file_location("migration_073_proration", _MODULE_PATH)
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


def test_refuses_when_proration_invoices_exist() -> None:
    module = _load_073_module()
    with patch.object(module.op, "get_bind", return_value=_fake_bind(2)):
        with pytest.raises(RuntimeError) as exc_info:
            module._refuse_if_proration_invoices_exist()

    assert "073 downgrade blocked" in str(exc_info.value)
    assert "2 PRORATION invoices exist" in str(exc_info.value)


def test_passes_when_no_proration_invoices_exist() -> None:
    module = _load_073_module()
    with patch.object(module.op, "get_bind", return_value=_fake_bind(0)):
        module._refuse_if_proration_invoices_exist()  # must not raise


def test_downgrade_calls_guard_before_any_schema_change() -> None:
    module = _load_073_module()

    with patch.object(module.op, "get_bind", return_value=_fake_bind(5)):
        with patch.object(module.op, "execute") as mock_op_execute:
            with pytest.raises(RuntimeError):
                module.downgrade()
            mock_op_execute.assert_not_called()
