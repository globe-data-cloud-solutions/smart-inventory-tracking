"""Guardrail against a repeat of the duplicate-017 incident: a second
migration file reusing an already-used revision id, which produced two
heads and silently forked the migration graph. These checks run against
the script directory only — no database connection required.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = MIGRATIONS_DIR / "versions"

pytestmark = pytest.mark.unit


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory(str(MIGRATIONS_DIR))


def test_exactly_one_head() -> None:
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"expected exactly one head, found {len(heads)}: {heads}"


def test_all_revision_ids_unique() -> None:
    pattern = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
    seen: dict[str, Path] = {}
    duplicates: list[str] = []

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            continue
        rev_id = match.group(1)
        if rev_id in seen:
            duplicates.append(f"{rev_id!r} used in both {seen[rev_id].name} and {path.name}")
        else:
            seen[rev_id] = path

    assert not duplicates, "duplicate revision ids found: " + "; ".join(duplicates)


def test_head_is_070_with_expected_down_revision() -> None:
    script_dir = _script_directory()
    heads = script_dir.get_heads()
    assert heads == ["070"], f"expected head '070', found {heads}"

    head_script = script_dir.get_revision("070")
    assert head_script.down_revision == "069", (
        f"expected revision 070's down_revision to be '069', "
        f"found {head_script.down_revision!r}"
    )
