#!/usr/bin/env bash
# check_i18n.sh — Fail if raw i18n keys or missing t() keys appear in JSX.
# Warns (non-blocking) on dynamic template literal keys and hardcoded toast strings.
# Run before every frontend commit: bash scripts/check_i18n.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SRC="$ROOT/frontend/src/app"
COMPONENTS="$ROOT/frontend/src/components"
EXIT=0

echo "=== SMART i18n Check ==="
echo ""

# ── ERROR Check 1: Raw i18n-style keys in JSX text content ────────────────
# Pattern: JSX text like >wizard.step1_title< or >common.loading<
echo "Checking for raw i18n keys in JSX text..."

RAW_KEYS=$(grep -rn \
  '>[a-z][a-z_]*\.[a-z][a-z_]*<' \
  "$SRC" "$COMPONENTS" \
  --include="*.tsx" 2>/dev/null \
  | grep -v "className\|href\|style=\|//\|test\|spec\|t(\|{t(" \
  | grep -v "\.toLowerCase\|\.toUpperCase\|\.split\|\.replace\|\.trim" \
  | grep -v "data-\|aria-\|key=" \
  || true)

if [ -n "$RAW_KEYS" ]; then
  echo ""
  echo "ERROR: Raw i18n keys found in JSX text:"
  echo "$RAW_KEYS"
  echo ""
  echo "Fix: wrap each key in t('key.name') and add to locales/en.json first."
  EXIT=1
else
  echo "  PASS: No raw i18n keys in JSX."
fi

# ── ERROR Check 2: t() calls with keys missing from en.json ───────────────
# Runs from $ROOT (cd'd above) using repo-relative paths only — the embedded
# Python is native Windows Python under Git Bash and cannot open the
# POSIX-style absolute paths ("/c/...") that `pwd` produces there.
echo ""
echo "Checking for t() calls with missing en.json keys..."

CHECK2_SCRIPT="$(mktemp)"
cat > "$CHECK2_SCRIPT" <<'PYEOF'
import re, os, json, sys

with open('locales/en.json', encoding='utf-8') as f:
    en = json.load(f)

def key_exists(d, key_path):
    parts = key_path.split('.')
    cur = d
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    return True

pattern = re.compile(r"t\([\"']([\w.]+)[\"']\)")
missing = set()
scanned = 0

for base in ('frontend/src/app', 'frontend/src/components'):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ('node_modules', '.next')]
        for fn in files:
            if not fn.endswith(('.tsx', '.ts')):
                continue
            scanned += 1
            path = os.path.join(root, fn)
            content = open(path, encoding='utf-8').read()
            for m in pattern.finditer(content):
                key = m.group(1)
                if '.' in key and len(key) > 4 and not key.startswith('.'):
                    if not key_exists(en, key):
                        missing.add(key)

print(f'__SCANNED__ {scanned}')
for k in sorted(missing):
    print(k)
PYEOF

set +e
CHECK2_OUTPUT="$(python3 "$CHECK2_SCRIPT" 2>&1)"
CHECK2_EXIT=$?
set -e
rm -f "$CHECK2_SCRIPT"

if [ "$CHECK2_EXIT" -ne 0 ]; then
  echo ""
  echo "ERROR: i18n checker crashed"
  echo "$CHECK2_OUTPUT"
  EXIT=1
else
  SCANNED=$(echo "$CHECK2_OUTPUT" | grep '^__SCANNED__ ' | awk '{print $2}' || true)
  MISSING=$(echo "$CHECK2_OUTPUT" | grep -v '^__SCANNED__ ' || true)
  echo "  scanned $SCANNED files"
  if [ -n "$MISSING" ]; then
    echo ""
    echo "ERROR: t() calls with missing en.json keys:"
    echo "$MISSING"
    echo ""
    echo "Fix: add these keys to locales/en.json (then sync to am.json and or.json)."
    EXIT=1
  else
    echo "  PASS: All static t() keys found in en.json."
  fi
fi

# ── ERROR Check 2b: hardcoded English strings in JSX/attrs/error calls ────
echo ""
echo "Checking for hardcoded English strings in JSX..."
if ! python3 scripts/check_hardcoded_jsx.py; then
  EXIT=1
fi

# ── WARNING Check 3: Dynamic template literal t() calls ───────────────────
# These use t(\`key.\${var}\`) — the script cannot verify all possible values.
# Caller must manually ensure all dynamic values have entries in en.json.
echo ""
echo "Checking for dynamic template literal t() calls..."

DYNAMIC=$(grep -rn \
  "t(\`[a-z][a-z_.]*\\\${" \
  "$SRC" "$COMPONENTS" \
  --include="*.tsx" 2>/dev/null \
  | grep -v "//\|test\|spec" \
  || true)

if [ -n "$DYNAMIC" ]; then
  echo ""
  echo "WARNING: Dynamic template literal t() calls found:"
  echo "$DYNAMIC"
  echo ""
  echo "  Manual check required: ensure every possible value of the variable"
  echo "  has a corresponding key in locales/en.json."
  echo "  (This is a warning — build is not blocked.)"
else
  echo "  PASS: No dynamic t() template literals."
fi

# ── WARNING Check 4: Hardcoded English strings in toast/alert/error calls ─
echo ""
echo "Checking for hardcoded English strings in toast/alert/error calls..."

HARDCODED=$(grep -rn \
  'setToast(\|showError(\|showToast(\|toast\.error(\|toast\.warn(\|toast\.info(\|alert(' \
  "$SRC" "$COMPONENTS" \
  --include="*.tsx" 2>/dev/null \
  | grep '"[A-Z][a-z]\|'"'"'[A-Z][a-z]' \
  | grep -v "//\|t(\|{t(\|test\|spec" \
  || true)

if [ -n "$HARDCODED" ]; then
  echo ""
  echo "WARNING: Hardcoded English strings in toast/alert calls:"
  echo "$HARDCODED"
  echo ""
  echo "  Replace with t('key.name') and add the key to locales/en.json."
  echo "  (This is a warning — build is not blocked.)"
else
  echo "  PASS: No hardcoded strings in toast/alert calls."
fi

# ── WARNING Check 5: Raw UUID-like ID values in JSX content ───────────────
echo ""
echo "Checking for possible raw ID/UUID display in JSX..."

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
  echo "  Review: confirm these are not raw UUIDs shown to users."
  echo "  Use useTenantName(), useNodeName(), or resolve to a display name."
  echo "  (This is a warning — build is not blocked.)"
else
  echo "  PASS: No suspicious raw ID displays."
fi

# ── ERROR Check 6: EN fallback parity (root locales/en.json vs frontend) ──
echo ""
echo "Checking EN fallback parity..."
if ! python3 scripts/check_locale_parity.py; then
  EXIT=1
fi

# ── ERROR Check 7: every audit action id the backend writes has a label ───
# The id list is derived from backend/shared/permissions/registry.py plus the
# audit_log()/INSERT INTO audit_logs literals (scripts/audit_action_ids.py), so a
# new permission or audit write without an audit.actions.* label fails here.
echo ""
echo "Checking audit action labels (audit.actions.*)..."
if [ ! -f "$ROOT/backend/shared/permissions/registry.py" ]; then
  echo "  Check 7 skipped: backend sources not present (container build); enforced in container-smoke workflow"
elif ! python3 scripts/audit_action_ids.py --check; then
  EXIT=1
fi

# ── ERROR Check 8: raw toLocale*/Intl.DateTimeFormat|NumberFormat calls ───
# Dates/numbers must go through frontend/src/lib/format.ts so output follows the
# app's language, not the browser's. An `i18n-ignore:` marker on the same line or
# the line directly above exempts a call (e.g. a value only used for comparison).
echo ""
echo "Checking for raw locale-formatting calls outside lib/format.ts..."

CHECK8_SCRIPT="$(mktemp)"
cat > "$CHECK8_SCRIPT" <<'PYEOF'
import os, re, sys

PATTERN = re.compile(r"toLocaleDateString\(|toLocaleString\(|toLocaleTimeString\(|new Intl\.(DateTimeFormat|NumberFormat)\(")
violations = []

for base in ("frontend/src/app", "frontend/src/components"):
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".next", "_archived")]
        for fn in files:
            if not fn.endswith((".ts", ".tsx")):
                continue
            path = os.path.join(root, fn)
            lines = open(path, encoding="utf-8").read().splitlines()
            for i, line in enumerate(lines, start=1):
                if not PATTERN.search(line):
                    continue
                exempt = False
                for ln in (i, i - 1):
                    if 1 <= ln <= len(lines) and "i18n-ignore:" in lines[ln - 1]:
                        exempt = True
                        break
                if not exempt:
                    violations.append(f"{path}:{i}: {line.strip()}")

for v in violations:
    print(v)
sys.exit(1 if violations else 0)
PYEOF

set +e
CHECK8_OUTPUT="$(python3 "$CHECK8_SCRIPT" 2>&1)"
CHECK8_EXIT=$?
set -e
rm -f "$CHECK8_SCRIPT"

if [ "$CHECK8_EXIT" -ne 0 ]; then
  echo ""
  echo "ERROR: raw locale-formatting calls found outside lib/format.ts:"
  echo "$CHECK8_OUTPUT"
  echo ""
  echo "Fix: use formatNumber/formatDate/formatDateTime/formatTime from lib/format.ts,"
  echo "  or add an i18n-ignore: <reason> marker if the value is never displayed."
  EXIT=1
else
  echo "  PASS: No raw locale-formatting calls outside lib/format.ts."
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────"
if [ "$EXIT" -eq 0 ]; then
  echo "PASS: All i18n ERROR checks passed."
  echo "      Review any WARNINGs above manually."
else
  echo "FAIL: i18n ERROR(s) detected. Fix before committing or building."
fi
echo "─────────────────────────────────────────"

exit $EXIT
