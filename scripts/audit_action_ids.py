#!/usr/bin/env python3
"""List every audit action id the backend can write to audit_logs, and (with
--check) fail when one has no audit.actions label in locales/en.json.

Sources, all derived from the code (nothing hand-copied):
  1. backend/shared/permissions/registry.py — the permission middleware writes an
     audit_logs row (action = Permission.id) for every permission decision.
  2. audit_log(...) calls and `INSERT INTO audit_logs` statements — literal
     "<prefix>:<name>" action ids (middleware-independent business rows).
  3. f"{resource_type}:<name>" templates in audit_log(...) calls — expanded with
     the resource types listed in _TEMPLATE_PREFIXES below.

The label key for an id is audit.actions.<id with ':' -> '_'  (frontend getActionLabel).

Usage:
  python scripts/audit_action_ids.py            # print ids
  python scripts/audit_action_ids.py --check    # exit 1 if any id lacks an en.json label
  python scripts/audit_action_ids.py --resources  # print resource_type values written
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# f"{resource_type}:product_override_required" in inventory_service.py is called
# with these resource types (see _resolve_product_override callers). If a new
# template caller is added, extend this tuple.
_TEMPLATE_PREFIXES = ("transfer", "adjustment")

_ID = r"[a-z][a-z_]*:[a-z][a-z_]*"


def _source_files() -> list[Path]:
    out = []
    for p in (ROOT / "backend").rglob("*.py"):
        posix = p.as_posix()
        if "_ARCHIVED" in posix or "/tests/" in posix or "/migrations/" in posix:
            continue
        out.append(p)
    return out


def registry_ids() -> set[str]:
    text = (ROOT / "backend/shared/permissions/registry.py").read_text(encoding="utf-8")
    return set(re.findall(r'Permission\(\s*"(' + _ID + r')"', text))


def literal_ids() -> set[str]:
    ids: set[str] = set()
    for p in _source_files():
        s = p.read_text(encoding="utf-8")
        if "audit_log(" not in s and "INSERT INTO audit_logs" not in s:
            continue
        for m in re.finditer(r"audit_log\(", s):
            seg = s[m.end() : m.end() + 400]
            ids.update(re.findall(r'f?["\'](' + _ID + r')["\']', seg))
            for name in re.findall(r'f"\{[a-z_]+\}:([a-z][a-z_]*)"', seg):
                ids.update(f"{pfx}:{name}" for pfx in _TEMPLATE_PREFIXES)
        for m in re.finditer(r"INSERT INTO audit_logs", s):
            seg = s[m.end() : m.end() + 800]
            ids.update(re.findall(r"'(" + _ID + r")'", seg))
    return ids


def all_ids() -> set[str]:
    return registry_ids() | literal_ids()


def resource_types() -> set[str]:
    types: set[str] = set()
    for p in _source_files():
        s = p.read_text(encoding="utf-8")
        if "audit_log(" not in s and "INSERT INTO audit_logs" not in s:
            continue
        types.update(re.findall(r'"resource_type":\s*"([a-z_]+)"', s))
        for m in re.finditer(r"INSERT INTO audit_logs", s):
            seg = s[m.end() : m.end() + 800]
            types.update(re.findall(r"'[a-z_]+:[a-z_]+',\s*'([a-z_]+)'", seg))
    return types


def label_key(action_id: str) -> str:
    return action_id.replace(":", "_")


def main(argv: list[str]) -> int:
    if "--resources" in argv:
        print("\n".join(sorted(resource_types())))
        return 0
    ids = sorted(all_ids())
    if "--check" not in argv:
        print("\n".join(ids))
        return 0
    en = json.loads((ROOT / "locales/en.json").read_text(encoding="utf-8"))
    labels = en.get("audit", {}).get("actions", {})
    missing = [i for i in ids if label_key(i) not in labels]
    if missing:
        print(
            f"ERROR: {len(missing)} audit action id(s) have no audit.actions label in locales/en.json:"
        )
        for i in missing:
            print(f"  {i}  ->  audit.actions.{label_key(i)}")
        print(
            "Fix: add the label to locales/en.json (and mirror to the other locale files)."
        )
        return 1
    print(f"  PASS: all {len(ids)} audit action ids have an audit.actions label.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
