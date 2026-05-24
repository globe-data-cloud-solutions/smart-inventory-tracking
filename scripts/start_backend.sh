#!/usr/bin/env bash
# scripts/start_backend.sh
# Starts all five SMART backend services in dependency order.
# Each service is health-checked before the next one starts.
# Run from anywhere; the script resolves paths relative to the repo root.
#
# Usage:
#   bash scripts/start_backend.sh
#
# Logs are written to logs/services/ (created if absent).
# PIDs are printed so you can kill services with: kill <PID>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR="$REPO_ROOT/logs/services"
mkdir -p "$LOGS_DIR"

# ── Load .env ─────────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
  echo "✔ Loaded $ENV_FILE"
else
  echo "⚠  No .env found at $ENV_FILE — using existing environment variables"
fi

# ── Helper: start one service ─────────────────────────────────────────────────
# Usage: start_service <name> <port>
# The service directory must be backend/services/<name>/ and contain main.py
start_service() {
  local name="$1"
  local port="$2"
  local svc_dir="$REPO_ROOT/backend/services/$name"
  local log_file="$LOGS_DIR/$name.log"

  echo ""
  echo "▶ Starting $name on port $port …"

  # Run uvicorn from inside the service directory so 'main:app' resolves correctly
  (
    cd "$svc_dir"
    py -3.12 -m uvicorn main:app --host 0.0.0.0 --port "$port" \
      >> "$log_file" 2>&1
  ) &
  local pid=$!
  echo "  PID $pid → log: $log_file"

  # Wait for health check to pass before continuing
  echo -n "  Waiting for http://localhost:$port/health "
  local attempts=0
  until curl -sf "http://localhost:$port/health" > /dev/null 2>&1; do
    sleep 1
    attempts=$((attempts + 1))
    echo -n "."
    if [[ $attempts -ge 60 ]]; then
      echo ""
      echo "✖ $name failed to start within 60 s — check $log_file"
      exit 1
    fi
  done
  echo " ready (${attempts}s)"
}

# ── Start services in dependency order ────────────────────────────────────────
start_service "auth-service"      8001
start_service "api-gateway"       8000
start_service "tenant-service"    8002
start_service "product-service"   8003
start_service "inventory-service" 8004

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  All SMART backend services are running"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ auth-service      http://localhost:8001"
echo "  ✅ api-gateway       http://localhost:8000"
echo "  ✅ tenant-service    http://localhost:8002"
echo "  ✅ product-service   http://localhost:8003"
echo "  ✅ inventory-service http://localhost:8004"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Logs:  $LOGS_DIR/"
echo "  Stop:  kill \$(pgrep -f 'uvicorn main:app')"
echo ""
