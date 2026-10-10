"""Drift guard: docs/GETTING_STARTED.md (source of truth) must stay
byte-identical to frontend/public/help/getting-started.md (the copy served
by the public /getting-started page and the in-app Help page, CLAUDE.md
§15 S12). Mirrors test_sa_docs_operations_manual.py's
test_manual_copy_matches_source_of_truth for the same kind of doc pair.

Fix on failure: bash scripts/sync_help_docs.sh
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.mark.unit
def test_getting_started_copy_matches_source_of_truth() -> None:
    repo_root = Path(_TENANT_ROOT).resolve().parent.parent.parent
    source = repo_root / "docs" / "GETTING_STARTED.md"
    if not source.exists():
        pytest.skip("docs/GETTING_STARTED.md not present in this checkout")

    copy = repo_root / "frontend" / "public" / "help" / "getting-started.md"
    assert copy.exists(), (
        "frontend/public/help/getting-started.md is missing — "
        "run scripts/sync_help_docs.sh"
    )
    assert copy.read_bytes() == source.read_bytes(), (
        "frontend/public/help/getting-started.md has drifted from "
        "docs/GETTING_STARTED.md — re-run scripts/sync_help_docs.sh"
    )
