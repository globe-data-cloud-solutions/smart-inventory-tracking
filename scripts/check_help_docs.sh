#!/usr/bin/env bash
# scripts/check_help_docs.sh
# Fails if docs/TA_ONBOARDING_GUIDE.md (source of truth) and
# frontend/public/help/ta-onboarding-guide.md (the copy the Help page
# serves, CLAUDE.md §15 S12) have drifted apart. Run alongside
# check_i18n.sh — before every frontend commit and in the frontend build.
#
# Fix: bash scripts/sync_help_docs.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SRC="docs/TA_ONBOARDING_GUIDE.md"
COPY="frontend/public/help/ta-onboarding-guide.md"

echo "=== SMART Help Docs Check ==="
echo ""

if [ ! -f "$COPY" ]; then
  echo "FAIL: $COPY does not exist."
  echo "Fix: bash scripts/sync_help_docs.sh"
  exit 1
fi

if cmp -s "$SRC" "$COPY"; then
  echo "PASS: $SRC and $COPY are identical."
  exit 0
else
  echo "FAIL: $SRC and $COPY have drifted apart."
  echo "Fix: bash scripts/sync_help_docs.sh"
  exit 1
fi
