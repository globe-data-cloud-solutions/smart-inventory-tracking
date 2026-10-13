#!/usr/bin/env python3
"""Locale key parity checks. Exits 1 if any check fails.

1. EN fallback: every key in locales/en.json must exist in
   frontend/src/lib/locales/en.json (the frontend's bundled English copy).
   A missing key shows users a raw code instead of English text.
2. Translations: every key in locales/en.json must exist in
   locales/am.json and locales/or.json.

Run: python3 scripts/check_locale_parity.py   (scripts/check_i18n.sh runs it too)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_EN = os.path.join(ROOT, "locales", "en.json")
FRONTEND_EN = os.path.join(ROOT, "frontend", "src", "lib", "locales", "en.json")
TRANSLATIONS = {
    "am": os.path.join(ROOT, "locales", "am.json"),
    "or": os.path.join(ROOT, "locales", "or.json"),
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def flatten(d, prefix=""):
    keys = set()
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= flatten(v, full_key)
        else:
            keys.add(full_key)
    return keys


def report(label, missing):
    if missing:
        print(f"MISSING KEYS ({label}):")
        for key in missing:
            print(f"  {key}")
        return False
    print(f"  PASS: {label}")
    return True


def main():
    try:
        root_keys = flatten(load(ROOT_EN))
        frontend_keys = flatten(load(FRONTEND_EN))
        translated = {lang: flatten(load(path)) for lang, path in TRANSLATIONS.items()}
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read a locale file: {e}")
        return 1

    # Section 1 — EN fallback (the original check from 65a5139)
    ok = report(
        "in locales/en.json but not in frontend/src/lib/locales/en.json",
        sorted(root_keys - frontend_keys),
    )
    # Section 2 — Amharic / Oromo translations
    for lang, keys in translated.items():
        ok = report(
            f"in locales/en.json but not in locales/{lang}.json",
            sorted(root_keys - keys),
        ) and ok

    if ok:
        print("PARITY PASS")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
