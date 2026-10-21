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
            duplicates.append(
                f"{rev_id!r} used in both {seen[rev_id].name} and {path.name}"
            )
        else:
            seen[rev_id] = path

    assert not duplicates, "duplicate revision ids found: " + "; ".join(duplicates)


def _numeric_revision_map() -> dict[int, str]:
    """Map each purely-numeric revision id (as int) to its original string,
    e.g. {70: "070", 71: "071"} — scanned fresh so this test never needs
    updating when a new migration is added."""
    pattern = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
    mapping: dict[int, str] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match and match.group(1).isdigit():
            mapping[int(match.group(1))] = match.group(1)
    return mapping


def test_head_is_highest_numbered_revision() -> None:
    """The single head must be the highest-numbered migration on disk, and
    its down_revision must be the next-lower numbered one — not a hardcoded
    pair, so this test stays correct as new migrations are added."""
    numeric_revisions = _numeric_revision_map()
    assert numeric_revisions, "no purely-numeric revision ids found in versions/"

    max_num = max(numeric_revisions)
    expected_head = numeric_revisions[max_num]

    script_dir = _script_directory()
    heads = script_dir.get_heads()
    assert heads == [expected_head], f"expected head {expected_head!r}, found {heads}"

    head_script = script_dir.get_revision(expected_head)
    expected_down_revision = numeric_revisions.get(max_num - 1)
    assert head_script.down_revision == expected_down_revision, (
        f"expected revision {expected_head!r}'s down_revision to be "
        f"{expected_down_revision!r}, found {head_script.down_revision!r}"
    )
