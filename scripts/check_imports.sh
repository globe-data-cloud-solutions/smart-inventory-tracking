#!/usr/bin/env bash
# scripts/check_imports.sh
# Smoke test: verify every backend service imports without error.
# Used in CLAUDE.md §29 before every backend commit.
#
# Usage:
#   bash scripts/check_imports.sh
#
# Exit code: 0 if all services import OK, 1 if any fail.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env if present
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

any_failed=0

# Iterate over all backend/services/<name>/ directories that contain main.py
for svc_dir in "$REPO_ROOT"/backend/services/*/; do
  if [[ ! -f "$svc_dir/main.py" ]]; then
    continue  # skip directories without main.py
  fi

  svc_name=$(basename "$svc_dir")

  # Try to import the service
  if (cd "$svc_dir" && py -3.12 -c "import main" 2>&1); then
    echo "$svc_name: IMPORT OK"
  else
    echo "$svc_name: IMPORT FAILED"
    any_failed=1
  fi
done

if [[ $any_failed -eq 1 ]]; then
  echo ""
  echo "❌ One or more services failed to import"
  exit 1
else
  echo ""
  echo "✅ All services imported successfully"
  exit 0
fi
