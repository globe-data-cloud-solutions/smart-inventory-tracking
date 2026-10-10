#!/usr/bin/env bash
# scripts/check_help_docs.sh
# Fails if docs/TA_ONBOARDING_GUIDE.md or docs/GETTING_STARTED.md (sources
# of truth) have drifted from their frontend/public/help/ copies (the Help
# page and the public /getting-started page serve those copies, CLAUDE.md
# §15 S12). Run alongside check_i18n.sh — before every frontend commit and
# in the frontend build.
#
# Fix: bash scripts/sync_help_docs.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PAIRS=(
  "docs/TA_ONBOARDING_GUIDE.md:frontend/public/help/ta-onboarding-guide.md"
  "docs/GETTING_STARTED.md:frontend/public/help/getting-started.md"
)

echo "=== SMART Help Docs Check ==="
echo ""

EXIT=0
for pair in "${PAIRS[@]}"; do
  SRC="${pair%%:*}"
  COPY="${pair##*:}"

  if [ ! -f "$COPY" ]; then
    echo "FAIL: $COPY does not exist."
    EXIT=1
    continue
  fi

  if cmp -s "$SRC" "$COPY"; then
    echo "PASS: $SRC and $COPY are identical."
  else
    echo "FAIL: $SRC and $COPY have drifted apart."
    EXIT=1
  fi
done

if [ "$EXIT" -ne 0 ]; then
  echo ""
  echo "Fix: bash scripts/sync_help_docs.sh"
fi

exit $EXIT
