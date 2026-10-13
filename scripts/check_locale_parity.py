#!/usr/bin/env python3
"""
check_locale_parity.py — Verify that am.json and or.json have the same keys as en.json
(keys may have different values, but the structure must match for fallback to work).
Run: python3 scripts/check_locale_parity.py (returns 0 if all match, 1 if mismatch)
"""

import json
import sys
from pathlib import Path

def load_locale(path: str) -> dict:
    """Load a locale JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_all_keys(d: dict, prefix: str = '') -> set:
    """Recursively extract all dotted keys from a nested dict."""
    keys = set()
    for k, v in d.items():
        full_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            keys.update(get_all_keys(v, full_key))
        else:
            keys.add(full_key)
    return keys

def main():
    base_path = Path(__file__).parent.parent
    en_path = base_path / 'locales' / 'en.json'
    am_path = base_path / 'locales' / 'am.json'
    or_path = base_path / 'locales' / 'or.json'
    
    try:
        en = load_locale(str(en_path))
        am = load_locale(str(am_path))
        or_locale = load_locale(str(or_path))
    except FileNotFoundError as e:
        print(f"ERROR: Missing locale file: {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in locale file: {e}")
        return 1
    
    en_keys = get_all_keys(en)
    am_keys = get_all_keys(am)
    or_keys = get_all_keys(or_locale)
    
    errors = []

    # Check am.json — warn if missing keys from en.json (for fallback to work)
    missing_in_am = en_keys - am_keys
    if missing_in_am:
        errors.append(f"  am.json missing keys: {', '.join(sorted(missing_in_am))}")

    # Check or.json — warn if missing keys from en.json (for fallback to work)
    missing_in_or = en_keys - or_keys
    if missing_in_or:
        errors.append(f"  or.json missing keys: {', '.join(sorted(missing_in_or))}")
    
    if errors:
        print("ERROR: Locale key parity mismatch:")
        for err in errors:
            print(err)
        print()
        print("Fix: Ensure all keys from en.json are present in am.json and or.json.")
        return 1
    
    print("  PASS: All locales have matching key structure.")
    return 0

if __name__ == '__main__':
    sys.exit(main())
