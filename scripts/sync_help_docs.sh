#!/usr/bin/env bash
# scripts/sync_help_docs.sh
# Copies docs/TA_ONBOARDING_GUIDE.md (the source of truth) into
# frontend/public/help/, where the Help & Documents page serves it.
# Anything under frontend/public is readable without login — never add a
# source here that isn't meant to be customer-facing (CLAUDE.md §15 S12).
#
# Run before every frontend commit that touches docs/TA_ONBOARDING_GUIDE.md:
#   bash scripts/sync_help_docs.sh
#
# scripts/check_help_docs.sh fails CI if the two copies ever drift apart.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p frontend/public/help
cp docs/TA_ONBOARDING_GUIDE.md frontend/public/help/ta-onboarding-guide.md

echo "Synced docs/TA_ONBOARDING_GUIDE.md -> frontend/public/help/ta-onboarding-guide.md"
