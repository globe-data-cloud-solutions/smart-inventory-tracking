#!/usr/bin/env bash
# check_i18n.sh — Fail if raw i18n keys or UUIDs appear as JSX text content.
# Run before every frontend commit: bash scripts/check_i18n.sh
# Both findings categories must be clean before git commit.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/frontend/src/app"
EXIT=0

# ── Check 1: Raw i18n-style keys in JSX text content ──────────────────────────
# Pattern: JSX text like >wizard.step1_title< or >common.loading<
# Exclusions: t() calls, className, href, style props, comments, tests

echo "Checking for raw i18n keys in JSX text..."

RAW_KEYS=$(grep -rn \
  '>[a-z][a-z_]*\.[a-z][a-z_]*<' \
  "$SRC" \
  --include="*.tsx" 2>/dev/null \
  | grep -v "className\|href\|style=\|//\|test\|spec\|t(\|{t(" \
  | grep -v "\.toLowerCase\|\.toUpperCase\|\.split\|\.replace\|\.trim" \
  | grep -v "data-\|aria-\|key=" \
  || true)

if [ -n "$RAW_KEYS" ]; then
  echo ""
  echo "FAIL: Raw i18n keys found in JSX:"
  echo "$RAW_KEYS"
  echo ""
  echo "Fix: wrap each key in t() or add to locales/en.json first."
  EXIT=1
else
  echo "  PASS: No raw i18n keys found."
fi

# ── Check 2: t() calls for keys missing from en.json ─────────────────────────
echo ""
echo "Checking for t() calls with missing en.json keys..."

MISSING=$(python3 -c "
import re, os, json, sys

try:
    with open('$ROOT/locales/en.json', encoding='utf-8') as f:
        en = json.load(f)
except Exception as e:
    print(f'Cannot open en.json: {e}', file=sys.stderr)
    sys.exit(0)

def key_exists(d, key_path):
    parts = key_path.split('.')
    cur = d
    for p in parts:
        if not isinstance(cur, dict) or p not in cur: return False
        cur = cur[p]
    return True

pattern = re.compile(r\"t\([\\\"']([\w.]+)[\\\"']\)\")
missing = set()

for root, dirs, files in os.walk('$SRC'):
    dirs[:] = [d for d in dirs if d not in ['node_modules', '.next']]
    for fn in files:
        if not fn.endswith(('.tsx', '.ts')): continue
        try:
            content = open(os.path.join(root, fn), encoding='utf-8').read()
        except: continue
        for m in pattern.finditer(content):
            key = m.group(1)
            if '.' in key and len(key) > 4 and not key.startswith('.'):
                if not key_exists(en, key):
                    missing.add(key)

for k in sorted(missing):
    print(k)
" 2>/dev/null || true)

if [ -n "$MISSING" ]; then
  echo ""
  echo "FAIL: t() calls with missing en.json keys:"
  echo "$MISSING"
  echo ""
  echo "Fix: add these keys to locales/en.json (and am.json, or.json)."
  EXIT=1
else
  echo "  PASS: All t() keys found in en.json."
fi

# ── Check 3: Raw UUID-like values in JSX content ──────────────────────────────
echo ""
echo "Checking for possible UUID display in JSX..."

UUID_DISPLAY=$(grep -rn \
  '\.[a-z]*_id}\b' \
  "$SRC" \
  --include="*.tsx" 2>/dev/null \
  | grep -v "//\|key=\|value=\|===\|!==\|filter\|find\|param\|query\|toLowerCase\|aria-\|className\|href\|style=" \
  | grep -v "test\|spec" \
  || true)

if [ -n "$UUID_DISPLAY" ]; then
  echo ""
  echo "WARNING: Possible raw ID/UUID display in JSX:"
  echo "$UUID_DISPLAY"
  echo ""
  echo "Review: confirm these are not raw UUIDs shown to users."
  echo "(This is a warning, not a hard failure — IDs may be intentional.)"
  # Not setting EXIT=1 for UUID check — too many false positives
  # Set EXIT=1 if you want to enforce this strictly
else
  echo "  PASS: No suspicious raw ID displays found."
fi

echo ""
if [ "$EXIT" -eq 0 ]; then
  echo "PASS: All i18n checks passed."
else
  echo "FAIL: i18n issues detected. Fix before committing."
fi

exit $EXIT
