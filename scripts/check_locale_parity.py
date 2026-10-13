#!/usr/bin/env python3
"""Fail if any key in locales/en.json is missing from frontend/src/lib/locales/en.json.

Run before every frontend commit: python scripts/check_locale_parity.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_EN = os.path.join(ROOT, "locales", "en.json")
FRONTEND_EN = os.path.join(ROOT, "frontend", "src", "lib", "locales", "en.json")


def flatten(d, prefix=""):
    keys = set()
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= flatten(v, full_key)
        else:
            keys.add(full_key)
    return keys


def main():
    with open(ROOT_EN, encoding="utf-8") as f:
        root_en = json.load(f)
    with open(FRONTEND_EN, encoding="utf-8") as f:
        frontend_en = json.load(f)

    root_keys = flatten(root_en)
    frontend_keys = flatten(frontend_en)

    missing = sorted(root_keys - frontend_keys)

    if missing:
        print("MISSING KEYS (in locales/en.json but not in frontend/src/lib/locales/en.json):")
        for key in missing:
            print(f"  {key}")
        sys.exit(1)

    print("PARITY PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
