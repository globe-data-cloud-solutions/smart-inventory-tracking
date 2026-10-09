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

S3_NAME="smoke-s3"
S3_BUCKET="smart-smoke-attachments"
# Moto's moto_server — the prior S3-compatible test image is no longer
# publicly pullable, so this smoke test now installs a pure-Python
# S3-compatible mock fresh via pip into python:3.12-slim instead.
docker run -d --name "$S3_NAME" --network "$NETWORK" python:3.12-slim \
  bash -c 'pip install -q "moto[server]" && moto_server -H 0.0.0.0 -p 5000' >/dev/null
STARTED_CONTAINERS+=("$S3_NAME")

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

# moto_server needs `pip install` to finish inside the container first, so
# give it up to 90s (vs. the 60s budget above) before declaring it unready.
s3_ready=0
for _ in $(seq 1 45); do
  code="$(docker run --rm --network "$NETWORK" -e S3_URL="http://${S3_NAME}:5000/" \
      python:3.12-slim python3 -c '
import os, urllib.request
try:
    print(urllib.request.urlopen(os.environ["S3_URL"], timeout=3).status)
except Exception:
    print(0)
' 2>/dev/null)"
  if [ "$code" = "200" ]; then
    s3_ready=1
    break
  fi
  sleep 2
done
if [ "$s3_ready" -eq 1 ]; then
  log "moto S3 server ready: $S3_NAME"
else
  fail "moto S3 server did not become ready within 90s"
  s3_logs="$(docker logs "$S3_NAME" 2>&1)"
  log "${s3_logs: -2000}"
fi
[ "$FAILED" -eq 0 ] || exit 1

if docker run --rm --network "$NETWORK" \
    -e AWS_ACCESS_KEY_ID=testing -e AWS_SECRET_ACCESS_KEY=testing -e AWS_DEFAULT_REGION=us-east-1 \
    -e S3_ENDPOINT="http://${S3_NAME}:5000" -e S3_BUCKET="$S3_BUCKET" \
    python:3.12-slim bash -c '
      set -e
      pip install -q boto3
      python3 -c "
import os, boto3
s3 = boto3.client(\"s3\", endpoint_url=os.environ[\"S3_ENDPOINT\"], region_name=\"us-east-1\")
s3.create_bucket(Bucket=os.environ[\"S3_BUCKET\"])
print(\"bucket created:\", os.environ[\"S3_BUCKET\"])
"
    ' >/tmp/moto-bucket.log 2>&1; then
  log "bucket created: $S3_BUCKET"
else
  fail "moto bucket creation failed"
  tail -40 /tmp/moto-bucket.log || true
fi
[ "$FAILED" -eq 0 ] || exit 1

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
start=$(date +%s)
if docker build -q -f backend/migrations/Dockerfile -t smart-migration:smoke "$REPO_ROOT" >/tmp/build-migration.log 2>&1; then
  secs=$(( $(date +%s) - start ))
  size=$(docker images --format '{{.Size}}' smart-migration:smoke | head -1)
  printf '%-20s %-6s %6s %10s\n' "migration" "OK" "${secs}s" "$size"
else
  secs=$(( $(date +%s) - start ))
  printf '%-20s %-6s %6s %10s\n' "migration" "FAIL" "${secs}s" "-"
  tail -40 /tmp/build-migration.log
  fail "image build: migration"
fi
[ "$FAILED" -eq 0 ] || { log "SUMMARY: build failures present, aborting before container run"; exit 1; }

# ── c. fresh-DB migrations + permission seed ────────────────────────────────
section "Fresh-DB migrations"
DB_URL="postgresql+asyncpg://smoke:smoke@${PG_NAME}:5432/smart_inventory"
if docker run --rm --network "$NETWORK" \
    -e DATABASE_URL="$DB_URL" -e DATABASE_READ_URL="$DB_URL" \
    smart-migration:smoke; then
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
STORAGE_BACKEND=s3
STORAGE_S3_BUCKET=${S3_BUCKET}
STORAGE_S3_ENDPOINT_URL=http://${S3_NAME}:5000
AWS_ACCESS_KEY_ID=testing
AWS_SECRET_ACCESS_KEY=testing
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

# ── f2. S3 upload via Moto (product-service STORAGE_BACKEND=s3) ─────────────
section "S3 upload via Moto"
log "endpoint used: POST /api/v1/upload/product-image (tier: STARTER — product:upload_image is not plan-gated)"

PNG_B64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
PNG_FILE="$TMP_ENV_DIR/test-upload.png"
printf '%s' "$PNG_B64" | base64 -d > "$PNG_FILE"
LOCAL_SHA="$(sha256sum "$PNG_FILE" | cut -d' ' -f1)"

resp="$(curl -s -w '\n%{http_code}' -H "Authorization: Bearer ${token}" \
  -F "file=@${PNG_FILE};type=image/png" http://localhost:8080/api/v1/upload/product-image)"
code="$(tail -1 <<<"$resp")"; body="$(sed '$d' <<<"$resp")"
show "POST /api/v1/upload/product-image" "$code" "$body"
[ "$code" = "200" ] || fail "product-image upload expected 200, got $code"
upload_url="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('data',{}).get('url',''))" <<<"$body" 2>/dev/null || true)"
log "uploaded URL: $upload_url"

if [ -n "$upload_url" ]; then
  get_code="$(curl -s -o "$TMP_ENV_DIR/fetched.png" -w '%{http_code}' "http://localhost:8080${upload_url}")"
  REMOTE_SHA="$(sha256sum "$TMP_ENV_DIR/fetched.png" | cut -d' ' -f1)"
  log "GET $upload_url -> $get_code; sha256 local=$LOCAL_SHA remote=$REMOTE_SHA"
  [ "$get_code" = "200" ] || fail "fetch uploaded file expected 200, got $get_code"
  [ "$LOCAL_SHA" = "$REMOTE_SHA" ] || fail "sha256 mismatch between uploaded and fetched file"
else
  fail "could not parse uploaded URL from upload response"
fi
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
  "smart-tenant-service:smoke" bash -c "$WORKER_CMD" >/dev/null
STARTED_CONTAINERS+=("outbox-worker")
ready=0
for _ in $(seq 1 23); do
  worker_logs="$(docker logs outbox-worker 2>&1)"
  if grep -qi "ready" <<<"$worker_logs"; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -eq 1 ]; then
  grep -i "ready" <<<"$worker_logs" | tail -1
else
  fail "outbox worker did not report ready within 45s"
  docker logs --tail 60 outbox-worker || true
fi

docker run -d --name outbox-beat --network "$NETWORK" --env-file "$ENV_FILE" \
  "smart-tenant-service:smoke" bash -c "$BEAT_CMD" >/dev/null
STARTED_CONTAINERS+=("outbox-beat")
ready=0
for _ in $(seq 1 23); do
  beat_logs="$(docker logs outbox-beat 2>&1)"
  if grep -qi "ready\|beat.*starting\|Scheduler" <<<"$beat_logs"; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -eq 1 ]; then
  grep -i "ready\|beat.*starting\|Scheduler" <<<"$beat_logs" | tail -1
else
  fail "outbox beat did not report ready within 45s"
  docker logs --tail 60 outbox-beat || true
fi

# ── g2. negative check: production config guard refuses unsafe prod config ──
# PASS requires exit code == 1 (not just nonzero — proves the ENTRYPOINT
# pre-flight ran and exited cleanly, not e.g. a crashed uvicorn --workers
# parent, which exits 0 even when a child worker fails to start) AND the
# FATAL line present exactly once (proves the pre-flight short-circuited
# before uvicorn/celery ever started, not a later in-process re-check).
check_guard_refuses() {
  local name="$1" image="$2"; shift 2
  docker run -d --name "$name" --network "$NETWORK" --env-file "$ENV_FILE" \
    -e ENVIRONMENT=prod "$image" "$@" >/dev/null
  STARTED_CONTAINERS+=("$name")
  local exit_code
  exit_code="$(timeout 30 docker wait "$name" 2>/dev/null || echo "")"
  local logs; logs="$(docker logs "$name" 2>&1 || true)"
  local fatal_count; fatal_count="$(grep -c "FATAL: unsafe production config" <<<"$logs" || true)"
  if [ "$exit_code" = "1" ] && [ "$fatal_count" = "1" ]; then
    log "PASS: $name exited 1 with FATAL: unsafe production config (x1)"
  else
    fail "$name did not refuse to start as expected (exit=${exit_code:-none}, fatal_count=$fatal_count)"
    log "${logs: -2000}"
  fi
}

section "Production config guard (negative check — auth-service)"
check_guard_refuses "guard-check-auth" "smart-auth-service:smoke"

section "Production config guard (negative check — outbox worker)"
check_guard_refuses "guard-check-worker" "smart-tenant-service:smoke" \
  bash -c "$WORKER_CMD"

[ "$FAILED" -eq 0 ] || exit 1

# ── h. summary ───────────────────────────────────────────────────────────────
section "SUMMARY"
if [ "$FAILED" -eq 0 ]; then
  log "All image builds, migrations, health checks, e2e calls, and the outbox worker/beat succeeded."
  exit 0
else
  log "One or more steps FAILED — see output above."
  exit 1
fi
