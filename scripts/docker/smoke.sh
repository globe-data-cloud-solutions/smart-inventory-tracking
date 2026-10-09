#!/usr/bin/env bash
# Container smoke test — builds every backend service image, runs them against
# throwaway Postgres 16 + Redis 7 containers, applies fresh-DB migrations, and
# exercises a signup/login/plan e2e path through the gateway. Docker only — no
# other local dependency. See docs/claude/ci-cd.md "Container smoke test (CI)".
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

NETWORK="smart-smoke"
PG_NAME="smoke-pg"
REDIS_NAME="smoke-redis"
TMP_ENV_DIR=""
STARTED_CONTAINERS=()
FAILED=0

log() { printf '%s\n' "$*"; }
section() { printf '\n=== %s ===\n' "$*"; }

cleanup() {
  section "Cleanup"
  for c in "${STARTED_CONTAINERS[@]:-}"; do
    [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1 && log "removed container: $c"
  done
  docker network rm "$NETWORK" >/dev/null 2>&1 && log "removed network: $NETWORK" || true
  if [ -n "$TMP_ENV_DIR" ] && [ -d "$TMP_ENV_DIR" ]; then
    rm -rf "$TMP_ENV_DIR"
    log "removed temp env dir: $TMP_ENV_DIR"
  fi
}
trap cleanup EXIT

fail() { log "FAIL: $*"; FAILED=1; }

# ── a. network + throwaway Postgres/Redis ───────────────────────────────────
section "Network + datastores"
docker network create "$NETWORK" >/dev/null
log "network created: $NETWORK"

docker run -d --name "$PG_NAME" --network "$NETWORK" \
  -e POSTGRES_USER=smoke -e POSTGRES_PASSWORD=smoke -e POSTGRES_DB=smart_inventory \
  postgres:16 >/dev/null
STARTED_CONTAINERS+=("$PG_NAME")

docker run -d --name "$REDIS_NAME" --network "$NETWORK" redis:7 >/dev/null
STARTED_CONTAINERS+=("$REDIS_NAME")

wait_for() {
  local desc="$1"; shift
  local -i t=0
  until "$@" >/dev/null 2>&1; do
    t=$((t + 2))
    if [ "$t" -ge 60 ]; then
      fail "$desc did not become ready within 60s"
      docker logs --tail 60 "$2" || true
      return 1
    fi
    sleep 2
  done
  log "$desc ready after ${t}s"
}
wait_for "postgres" docker exec "$PG_NAME" pg_isready -U smoke
wait_for "redis" bash -c "docker exec $REDIS_NAME redis-cli ping | grep -q PONG"

# ── b. build every service image ─────────────────────────────────────────
section "Image builds"
printf '%-20s %-6s %6s %10s\n' "SERVICE" "OK/FAIL" "SECS" "SIZE"
SERVICES=()
for d in backend/services/*/; do
  name="$(basename "$d")"
  [ -f "${d}Dockerfile" ] || continue
  SERVICES+=("$name")
  start=$(date +%s)
  if docker build -q -f "${d}Dockerfile" -t "smart-${name}:smoke" "$REPO_ROOT" >/tmp/build-"$name".log 2>&1; then
    secs=$(( $(date +%s) - start ))
    size=$(docker images --format '{{.Size}}' "smart-${name}:smoke" | head -1)
    printf '%-20s %-6s %6s %10s\n' "$name" "OK" "${secs}s" "$size"
  else
    secs=$(( $(date +%s) - start ))
    printf '%-20s %-6s %6s %10s\n' "$name" "FAIL" "${secs}s" "-"
    tail -40 /tmp/build-"$name".log
    fail "image build: $name"
  fi
done
[ "$FAILED" -eq 0 ] || { log "SUMMARY: build failures present, aborting before container run"; exit 1; }

# ── c. fresh-DB migrations + permission seed ────────────────────────────────
section "Fresh-DB migrations"
DB_URL="postgresql+asyncpg://smoke:smoke@${PG_NAME}:5432/smart_inventory"
if docker run --rm --network "$NETWORK" \
    -v "$REPO_ROOT":/repo:ro \
    -e DATABASE_URL="$DB_URL" -e DATABASE_READ_URL="$DB_URL" \
    -e PYTHONPATH=/repo/backend \
    -w /repo/backend/migrations \
    python:3.12-slim bash -c '
      set -e
      pip install --no-cache-dir -q uv
      uv pip install --system -q -e /repo/backend/shared
      alembic upgrade head
      echo "--- alembic current ---"
      alembic current
      cd /repo/scripts
      python seed_permissions.py
    '; then
  log "migrations + permission seed: OK"
else
  fail "migrations + permission seed"
fi
[ "$FAILED" -eq 0 ] || exit 1

# ── d. temp env file ─────────────────────────────────────────────────────
section "Temp env file"
TMP_ENV_DIR="$(mktemp -d)"
ENV_FILE="$TMP_ENV_DIR/smoke.env"
JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)"
# ENVIRONMENT value for the AWS dev tier — docs/claude/ci-cd.md §6, "Secret naming
# convention": `smart/{env}/...` examples use `dev` (Environment: dev | stage | prod).
ENVIRONMENT_VALUE="dev"
log "ENVIRONMENT=$ENVIRONMENT_VALUE (docs/claude/ci-cd.md section 6, secret naming convention)"

cat > "$ENV_FILE" <<EOF
DATABASE_URL=${DB_URL}
DATABASE_READ_URL=${DB_URL}
REDIS_URL=redis://${REDIS_NAME}:6379/0
CELERY_BROKER_URL=redis://${REDIS_NAME}:6379/1
CELERY_RESULT_BACKEND=redis://${REDIS_NAME}:6379/2
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
ENVIRONMENT=${ENVIRONMENT_VALUE}
EMAIL_DELIVERY_MODE=log
EMAIL_FROM=no-reply@smoke.local
TERMS_VERSION=2026-10
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_HOPS=0
APP_BASE_URL=http://localhost:8080
AWS_REGION=us-east-1
STUB_WEBHOOK_SECRET=smoke-webhook-secret
EMAIL_VERIFICATION_REQUIRED=false
AUTH_SERVICE_URL=http://auth-service:8000
TENANT_SERVICE_URL=http://tenant-service:8000
PRODUCT_SERVICE_URL=http://product-service:8000
INVENTORY_SERVICE_URL=http://inventory-service:8000
ORDER_SERVICE_URL=http://order-service:8000
LOGISTICS_SERVICE_URL=http://logistics-service:8000
ANALYTICS_SERVICE_URL=http://analytics-service:8000
EOF
log "wrote temp env file with keys:"
grep -oE '^[A-Z0-9_]+' "$ENV_FILE"

# ── e. run every service ────────────────────────────────────────────────────
section "Run services"
declare -A HOST_PORT
port=9001
for name in "${SERVICES[@]}"; do
  [ "$name" = "api-gateway" ] && continue
  HOST_PORT["$name"]=$port
  docker run -d --name "$name" --network "$NETWORK" --env-file "$ENV_FILE" \
    -p "${port}:8000" "smart-${name}:smoke" >/dev/null
  STARTED_CONTAINERS+=("$name")
  port=$((port + 1))
done
docker run -d --name api-gateway --network "$NETWORK" --env-file "$ENV_FILE" \
  -e TRUSTED_PROXY_HOPS=0 -p 8080:8000 "smart-api-gateway:smoke" >/dev/null
STARTED_CONTAINERS+=("api-gateway")
HOST_PORT["api-gateway"]=8080

printf '%-20s %-6s %-8s\n' "SERVICE" "PORT" "STATUS"
for name in "${SERVICES[@]}"; do
  p="${HOST_PORT[$name]}"
  ok=0
  for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${p}/health" || echo 000)"
    if [ "$code" = "200" ]; then ok=1; break; fi
    sleep 2
  done
  if [ "$ok" -eq 1 ]; then
    printf '%-20s %-6s %-8s\n' "$name" "$p" "200"
  else
    printf '%-20s %-6s %-8s\n' "$name" "$p" "FAIL"
    docker logs --tail 60 "$name" || true
    fail "health check: $name"
  fi
done
[ "$FAILED" -eq 0 ] || exit 1

# ── f. e2e via gateway ───────────────────────────────────────────────────────
section "E2E via gateway (localhost:8080)"
show() { log "$1 -> ${2}; body: $(printf '%s' "$3" | head -c 120)"; }

resp="$(curl -s -w '\n%{http_code}' http://localhost:8080/api/v1/tenants/public/packages)"
code="$(tail -1 <<<"$resp")"; body="$(sed '$d' <<<"$resp")"
show "GET /api/v1/tenants/public/packages" "$code" "$body"
[ "$code" = "200" ] || fail "public/packages expected 200, got $code"

slug="zz-smoke-$(date +%s)"
signup_payload=$(cat <<JSON
{"company_name":"${slug}","organisation_type":"PRODUCER","default_locale":"en","tier":"STARTER","billing_period":"MONTHLY","admin_full_name":"Smoke Test","admin_email":"${slug}@example.com","admin_password":"Smoke123!Pass","accept_terms":true,"terms_version":"2026-10"}
JSON
)
resp="$(curl -s -w '\n%{http_code}' -H 'Content-Type: application/json' -d "$signup_payload" http://localhost:8080/api/v1/tenants/public/signup)"
code="$(tail -1 <<<"$resp")"; body="$(sed '$d' <<<"$resp")"
show "POST /api/v1/tenants/public/signup" "$code" "$body"
[ "$code" = "201" ] || fail "public/signup expected 201, got $code"

resp="$(curl -s -w '\n%{http_code}' -H 'Content-Type: application/json' -d "{\"email\":\"${slug}@example.com\",\"password\":\"Smoke123!Pass\"}" http://localhost:8080/api/v1/auth/token)"
code="$(tail -1 <<<"$resp")"; body="$(sed '$d' <<<"$resp")"
show "POST /api/v1/auth/token" "$code" "$body"
[ "$code" = "200" ] || fail "auth/token expected 200, got $code"
token="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))" <<<"$body" 2>/dev/null || true)"

resp="$(curl -s -w '\n%{http_code}' -H "Authorization: Bearer ${token}" http://localhost:8080/api/v1/tenants/me/plan)"
code="$(tail -1 <<<"$resp")"; body="$(sed '$d' <<<"$resp")"
show "GET /api/v1/tenants/me/plan" "$code" "$body"
[ "$code" = "200" ] || fail "tenants/me/plan expected 200, got $code"
[ "$FAILED" -eq 0 ] || exit 1

# ── g. outbox worker (+ beat) ────────────────────────────────────────────────
section "Outbox worker"
# Derived from backend/shared/outbox/worker.py: app = Celery("smart", ...) in module
# shared.outbox.worker, with a beat_schedule defined on that same app.
WORKER_CMD="celery -A shared.outbox.worker worker --loglevel=info"
BEAT_CMD="celery -A shared.outbox.worker beat --loglevel=info"
log "worker command: $WORKER_CMD"
log "beat command: $BEAT_CMD"

docker run -d --name outbox-worker --network "$NETWORK" --env-file "$ENV_FILE" \
  --entrypoint bash "smart-tenant-service:smoke" -c "$WORKER_CMD" >/dev/null
STARTED_CONTAINERS+=("outbox-worker")
ready=0
for _ in $(seq 1 23); do
  if docker logs outbox-worker 2>&1 | grep -qi "ready"; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -eq 1 ]; then
  docker logs outbox-worker 2>&1 | grep -i "ready" | tail -1
else
  fail "outbox worker did not report ready within 45s"
  docker logs --tail 60 outbox-worker || true
fi

docker run -d --name outbox-beat --network "$NETWORK" --env-file "$ENV_FILE" \
  --entrypoint bash "smart-tenant-service:smoke" -c "$BEAT_CMD" >/dev/null
STARTED_CONTAINERS+=("outbox-beat")
ready=0
for _ in $(seq 1 23); do
  if docker logs outbox-beat 2>&1 | grep -qi "ready\|beat.*starting\|Scheduler"; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -eq 1 ]; then
  docker logs outbox-beat 2>&1 | grep -i "ready\|beat.*starting\|Scheduler" | tail -1
else
  fail "outbox beat did not report ready within 45s"
  docker logs --tail 60 outbox-beat || true
fi

# ── h. summary ───────────────────────────────────────────────────────────────
section "SUMMARY"
if [ "$FAILED" -eq 0 ]; then
  log "All image builds, migrations, health checks, e2e calls, and the outbox worker/beat succeeded."
  exit 0
else
  log "One or more steps FAILED — see output above."
  exit 1
fi
