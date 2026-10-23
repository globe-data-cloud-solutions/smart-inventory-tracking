"""RB-9 / P7 guard: user-reachable error codes carry the named detail fields
their en message templates need.

Every backend dict literal of the form {"code": "<CODE>", ...} for a code in
P7_REQUIRED_FIELDS must include each required key. Each en template's
{placeholders} must be a subset of those required keys, so a message can
never reference a value the backend does not send.

The scan is static (ast over backend source), so it needs no DB and no
running service. Codes listed here are the user-reachable subset of
docs/i18n/error-codes-s19.md "needs field (P7)". Gateway, pre-auth and
billing codes are excluded on purpose.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]

P7_REQUIRED_FIELDS: dict[str, set[str]] = {
    "FIELD_TOO_LONG": {"field", "limit"},
    "INVALID_PHONE": {"field"},
    "IMAGE_TOO_LARGE": {"max_mb"},
    "INVALID_CONTRACT_DATES": {"field"},
    "INVALID_DATE": {"field"},
    "INVALID_LOCALE": {"allowed"},
    "INVALID_ROLE_CODE": {"role_code", "allowed"},
    "INVALID_SOURCE_FACTORY": {"sku", "factory_name"},
    "NODE_INACTIVE": {"side"},
    "LEVEL_COUNT_LOCKED": {"level"},
    "NODE_HAS_OPEN_TRANSFERS": {"count"},
    "NODE_HAS_PENDING_ADJUSTMENTS": {"count"},
    "NODE_HAS_SOLE_USERS": {"count"},
    "POSITION_HAS_ACTIVE_PERSONNEL": {"count"},
}

_SKIP_PARTS = {"tests", "__pycache__", "migrations"}


def _backend_source_files() -> list[pathlib.Path]:
    files = []
    for path in (REPO_ROOT / "backend").rglob("*.py"):
        if _SKIP_PARTS & set(path.parts) or "_ARCHIVED" in path.name:
            continue
        files.append(path)
    return files


def _code_dicts() -> dict[str, list[tuple[str, int, set[str]]]]:
    """Map code -> [(file, line, keys)] for every dict literal with a constant 'code' key."""
    found: dict[str, list[tuple[str, int, set[str]]]] = {}
    for path in _backend_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys: set[str] = set()
            code_value = None
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
                    if k.value == "code" and isinstance(v, ast.Constant):
                        code_value = v.value
            if code_value in P7_REQUIRED_FIELDS:
                found.setdefault(code_value, []).append(
                    (str(path.relative_to(REPO_ROOT)), node.lineno, keys)
                )
    return found


def _en_errors() -> dict[str, str]:
    data = json.loads((REPO_ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    return data["errors"]


@pytest.mark.parametrize("code", sorted(P7_REQUIRED_FIELDS))
def test_every_raise_site_sends_required_fields(code: str) -> None:
    sites = _code_dicts().get(code, [])
    assert sites, f"{code}: no backend dict literal found; did the code move or get renamed?"
    for file, line, keys in sites:
        missing = P7_REQUIRED_FIELDS[code] - keys
        assert not missing, f"{code} at {file}:{line} is missing detail fields {sorted(missing)}"


@pytest.mark.parametrize("code", sorted(P7_REQUIRED_FIELDS))
def test_en_template_placeholders_are_sent_by_backend(code: str) -> None:
    template = _en_errors().get(code, "")
    placeholders = set(re.findall(r"\{(\w+)\}", template))
    unsupported = placeholders - P7_REQUIRED_FIELDS[code]
    assert not unsupported, (
        f"{code} en template uses {sorted(unsupported)} which the backend does not send"
    )
