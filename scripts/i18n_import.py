#!/usr/bin/env python3
"""Apply a translator CSV (from i18n_export.py) back into a locale file.

Usage:
  python scripts/i18n_import.py FILE --locale am|or [--dry-run]

Applies non-empty new_value cells; rejects unknown keys, and any row whose
{placeholders} differ from the English value's. Writes the JSON keeping key
order and 2-space indent, prints counts (applied / skipped / rejected with
reasons), then runs check_locale_parity.py.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EN_PATH = os.path.join(ROOT, "locales", "en.json")

PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, full_key))
        else:
            out[full_key] = v
    return out


def set_nested(d, dotted_key, value):
    parts = dotted_key.split(".")
    node = d
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = value


def placeholders(s):
    return set(PLACEHOLDER_RE.findall(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--locale", required=True, choices=["am", "or"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    en_flat = flatten(load(EN_PATH))
    locale_path = os.path.join(ROOT, "locales", f"{args.locale}.json")
    locale_data = load(locale_path)
    locale_flat = flatten(locale_data)

    applied, skipped, rejected = 0, 0, []

    with open(args.file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("key") or "").strip()
            new_value = (row.get("new_value") or "").strip()
            if not new_value:
                skipped += 1
                continue
            if key not in en_flat or key not in locale_flat:
                rejected.append((key, "unknown key"))
                continue
            english = en_flat[key]
            if placeholders(new_value) != placeholders(english):
                rejected.append((key, "placeholder mismatch"))
                continue
            set_nested(locale_data, key, new_value)
            applied += 1

    print(f"{applied} applied / {skipped} skipped / {len(rejected)} rejected")
    for key, reason in rejected:
        print(f"  rejected {key}: {reason}")

    if args.dry_run:
        print("Dry run — no file written.")
        return 0

    if applied:
        with open(locale_path, "w", encoding="utf-8") as f:
            json.dump(locale_data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "check_locale_parity.py")],
        cwd=ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
