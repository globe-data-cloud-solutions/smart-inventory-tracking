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

cp docs/GETTING_STARTED.md frontend/public/help/getting-started.md

echo "Synced docs/GETTING_STARTED.md -> frontend/public/help/getting-started.md"

# SA-internal, backend-only, never frontend/public.
mkdir -p backend/services/tenant-service/static
cp docs/SA_OPERATIONS_MANUAL.md backend/services/tenant-service/static/sa_operations_manual.md

echo "Synced docs/SA_OPERATIONS_MANUAL.md -> backend/services/tenant-service/static/sa_operations_manual.md"

# Legal drafts (docs/legal/ = source of truth, Alex's text). Public filenames
# carry TERMS_VERSION/PRIVACY_VERSION (currently 2026-10) — never rename them
# without bumping the version, or owners won't be asked to re-accept.
mkdir -p frontend/public/legal
cp docs/legal/GDC_SMART_Terms_of_Service_DRAFT_v0.2.md frontend/public/legal/terms-2026-10.md
cp docs/legal/GDC_SMART_Privacy_Statement_DRAFT_v0.2.md frontend/public/legal/privacy-2026-10.md

echo "Synced docs/legal/*.md -> frontend/public/legal/{terms,privacy}-2026-10.md"
