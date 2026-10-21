"""Drift guard: docs/legal/*.md (Alex's source drafts) must stay
byte-identical to frontend/public/legal/{terms,privacy}-2026-10.md (served
by the public /terms and /privacy pages, CLAUDE.md §15 S12). Mirrors
test_getting_started_doc.py's pattern for the same kind of doc pair.

The public filenames carry TERMS_VERSION/PRIVACY_VERSION (2026-10) — do not
rename them to match a docs/legal/ filename bump without also bumping the
version, or owners won't be asked to re-accept.

Fix on failure: bash scripts/sync_help_docs.sh
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_TENANT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

_PAIRS = [
    ("GDC_SMART_Terms_of_Service_DRAFT_v0.2.md", "terms-2026-10.md"),
    ("GDC_SMART_Privacy_Statement_DRAFT_v0.2.md", "privacy-2026-10.md"),
]


@pytest.mark.unit
@pytest.mark.parametrize("source_name,copy_name", _PAIRS)
def test_legal_doc_copy_matches_source_of_truth(source_name: str, copy_name: str) -> None:
    repo_root = Path(_TENANT_ROOT).resolve().parent.parent.parent
    source = repo_root / "docs" / "legal" / source_name
    if not source.exists():
        pytest.skip(f"docs/legal/{source_name} not present in this checkout")

    copy = repo_root / "frontend" / "public" / "legal" / copy_name
    assert copy.exists(), (
        f"frontend/public/legal/{copy_name} is missing — run scripts/sync_help_docs.sh"
    )
    assert copy.read_bytes() == source.read_bytes(), (
        f"frontend/public/legal/{copy_name} has drifted from docs/legal/{source_name} — "
        "re-run scripts/sync_help_docs.sh"
    )
