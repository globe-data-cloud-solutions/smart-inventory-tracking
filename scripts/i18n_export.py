#!/usr/bin/env python3
"""Export locale keys to a translator-friendly CSV.

Usage:
  python scripts/i18n_export.py --locale am|or [--mode missing|all|review] [--out FILE]

Modes:
  missing (default) - keys whose current value equals the English value
  all               - every key
  review            - keys listed in docs/i18n/amharic-review-s19.md tables

Writes a UTF-8-with-BOM CSV (opens correctly in Excel):
  key, english, current_value, new_value (new_value is always empty)

All paths are repo-relative.
"""

import argparse
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EN_PATH = os.path.join(ROOT, "locales", "en.json")
REVIEW_DOC = os.path.join(ROOT, "docs", "i18n", "amharic-review-s19.md")


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


def review_keys():
    keys = set()
    row_re = re.compile(r"^\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|$")
    with open(REVIEW_DOC, encoding="utf-8") as f:
        for line in f:
            m = row_re.match(line.strip())
            if not m:
                continue
            key = m.group(1).strip()
            if key in ("Key", "---") or key.startswith("---"):
                continue
            keys.add(key)
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--locale", required=True, choices=["am", "or"])
    ap.add_argument("--mode", choices=["missing", "all", "review"], default="missing")
    ap.add_argument("--out")
    args = ap.parse_args()

    en_flat = flatten(load(EN_PATH))
    locale_path = os.path.join(ROOT, "locales", f"{args.locale}.json")
    locale_flat = flatten(load(locale_path))

    if args.mode == "review":
        wanted = review_keys()
        keys = [k for k in en_flat if k in wanted]
    elif args.mode == "all":
        keys = list(en_flat.keys())
    else:
        keys = [k for k in en_flat if locale_flat.get(k) == en_flat[k]]

    out_path = args.out or os.path.join(
        ROOT, "docs", "i18n", f"export_{args.locale}_{args.mode}.csv"
    )
    out_path_abs = out_path if os.path.isabs(out_path) else os.path.join(ROOT, out_path)
    os.makedirs(os.path.dirname(out_path_abs), exist_ok=True)

    with open(out_path_abs, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["key", "english", "current_value", "new_value"])
        for k in keys:
            writer.writerow([k, en_flat[k], locale_flat.get(k, ""), ""])

    rel_out = os.path.relpath(out_path_abs, ROOT)
    print(f"Wrote {len(keys)} rows to {rel_out}")


if __name__ == "__main__":
    sys.exit(main())
