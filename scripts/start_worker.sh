#!/usr/bin/env bash
# scripts/start_worker.sh
# Starts the outbox Celery worker + beat scheduler (local dev only).
# On Linux/ECS, use the default prefork pool (no --pool=solo) and run beat
# as exactly ONE instance across the deployment — never more than one beat.
#
# Usage:
#   bash scripts/start_worker.sh
#
# Logs are written to logs/services/ (created if absent).
# PIDs are printed so you can kill the processes with: kill <PID>

export PYTHONIOENCODING=utf-8

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

cd "$REPO_ROOT/backend"
export PYTHONPATH=.

# ── Check Redis is reachable (Celery broker) ──────────────────────────────────
echo ""
echo "▶ Checking Redis …"
python -c "
import os, sys
import redis
url = os.environ['CELERY_BROKER_URL']
try:
    redis.from_url(url).ping()
except Exception as exc:
    print(f'✖ Redis ping failed at {url}: {exc}', file=sys.stderr)
    sys.exit(1)
print('  ✔ Redis reachable')
"

# ── Start Celery worker (solo pool — Windows Git Bash friendly) ───────────────
echo ""
echo "▶ Starting outbox worker …"
celery -A shared.outbox.worker worker --pool=solo --loglevel=INFO \
  > "$LOGS_DIR/celery_worker.log" 2>&1 &
WORKER_PID=$!
echo "  PID $WORKER_PID → log: $LOGS_DIR/celery_worker.log"

# ── Start Celery beat ──────────────────────────────────────────────────────────
echo ""
echo "▶ Starting outbox beat scheduler …"
celery -A shared.outbox.worker beat --loglevel=INFO \
  > "$LOGS_DIR/celery_beat.log" 2>&1 &
BEAT_PID=$!
echo "  PID $BEAT_PID → log: $LOGS_DIR/celery_beat.log"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Outbox worker + beat running"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ worker  PID $WORKER_PID  log: $LOGS_DIR/celery_worker.log"
echo "  ✅ beat    PID $BEAT_PID  log: $LOGS_DIR/celery_beat.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Stop:  kill $WORKER_PID $BEAT_PID"
echo ""
