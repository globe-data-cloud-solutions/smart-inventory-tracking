#!/usr/bin/env python3
"""Fail if a backend error code has no errors.<CODE> locale entry.

Collects every error code the backend can return to a client — string
literals in `"code": "X"` / `'code': 'X'` dict entries and `code="X"` keyword
args — under backend/services/** and backend/shared/** (skipping tests,
_ARCHIVED* files, and migrations), then checks each one has an
errors.<CODE> key in locales/en.json, am.json, and or.json.

Also reports (warning only) errors.* keys whose code no longer appears
anywhere in the scanned backend sources.

Run from the repo root: python scripts/check_error_codes.py
"""

import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ["backend/services", "backend/shared"]
LOCALE_FILES = {
    "en": "locales/en.json",
    "am": "locales/am.json",
    "or": "locales/or.json",
}

CODE_RE_DQ = re.compile(r'"code"\s*:\s*"([A-Z][A-Z0-9_]*)"')
CODE_RE_SQ = re.compile(r"'code'\s*:\s*'([A-Z][A-Z0-9_]*)'")
CODE_RE_KW = re.compile(r'(?<![A-Za-z0-9_.])code\s*=\s*["\']([A-Z][A-Z0-9_]*)["\']')
# Positional-code exceptions (e.g. raise ValueError("ADDON_NOT_FOUND"),
# raise DispatchError("LOT_EXPIRED", ...)) whose callers turn str(exc) into
# the client-facing "code" field — a real pattern used across billing/dispatch.
CODE_RE_EXC = re.compile(r'\b\w+Error\(\s*["\']([A-Z][A-Z0-9_]*)["\']')


def should_skip_dir(dirname):
    if dirname.startswith("_ARCHIVED"):
        return True
    if dirname == "tests":
        return True
    if dirname == "migrations":
        return True
    return False


def should_skip_file(fn):
    if fn.startswith("_ARCHIVED"):
        return True
    return False


def collect_codes():
    """Returns dict: code -> list of "path:line" occurrences."""
    found = {}
    for base in SCAN_DIRS:
        base_path = os.path.join(ROOT, base)
        for root, dirs, files in os.walk(base_path):
            dirs[:] = [
                d
                for d in dirs
                if not should_skip_dir(d)
                and d not in ("node_modules", ".next", "__pycache__")
            ]
            for fn in files:
                if not fn.endswith(".py") or should_skip_file(fn):
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, ROOT).replace("\\", "/")
                try:
                    lines = open(path, encoding="utf-8").read().splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for i, line in enumerate(lines, start=1):
                    for pattern in (CODE_RE_DQ, CODE_RE_SQ, CODE_RE_KW, CODE_RE_EXC):
                        for m in pattern.finditer(line):
                            code = m.group(1)
                            found.setdefault(code, []).append(f"{rel}:{i}")
    return found


def flatten_keys(d, prefix=""):
    keys = set()
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= flatten_keys(v, full)
        else:
            keys.add(full)
    return keys


def load_error_keys(path):
    """Returns set of CODE values under the top-level 'errors' object."""
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        d = json.load(f)
    errors = d.get("errors", {})
    return set(k for k, v in errors.items() if not isinstance(v, dict))


def main():
    codes = collect_codes()
    locale_error_keys = {
        loc: load_error_keys(path) for loc, path in LOCALE_FILES.items()
    }

    missing = {}
    for code in sorted(codes):
        missing_in = [
            loc for loc, keys in locale_error_keys.items() if code not in keys
        ]
        if missing_in:
            missing[code] = missing_in

    print(
        f"Scanned backend/services and backend/shared: {len(codes)} distinct error codes found."
    )
    print()

    if missing:
        print(f"MISSING errors.<CODE> entries ({len(missing)} codes):")
        for code in sorted(missing):
            locs = ",".join(missing[code])
            first_occ = codes[code][0]
            print(f"  {code}  (missing in: {locs})  first seen: {first_occ}")
    else:
        print("All backend error codes have errors.<CODE> entries in en/am/or.")

    # Warning-only: errors.* keys with no corresponding backend code.
    all_locale_codes = set()
    for keys in locale_error_keys.values():
        all_locale_codes |= keys
    orphaned = sorted(c for c in all_locale_codes if c not in codes)
    if orphaned:
        print()
        print(
            f"WARNING: {len(orphaned)} errors.* keys have no matching backend code anymore:"
        )
        for code in orphaned:
            print(f"  {code}")

    print()
    if missing:
        print(f"FAIL: {len(missing)} error code(s) missing locale entries.")
        return 1

    print("ERROR CODES PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
