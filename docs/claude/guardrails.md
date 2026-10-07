## 29. Engineering Guardrails — Lessons from Incidents

These rules exist because each one caused a real outage. Follow them on every change.

### Before every commit that touches backend Python

Shortcut: `bash scripts/check_imports.sh`

```
1. Every touched service must import cleanly:
     cd backend/services/<service> && py -3.12 -c "import main"
   Route handlers are evaluated at import time. A Pydantic model referenced in a
   route signature MUST be defined ABOVE that route in the file. Moving routes
   (e.g. placing /me/* above /{tenant_id}) requires moving their request/response
   models too. (Incident 2026-09-27 -> 2026-10-04: ContractUpdateRequest defined
   850 lines below its first use; tenant-service could not start for 7 days.)
2. Run the service's unit tests AND restart the service; confirm GET /health = 200.
   A passing test run does not prove the service starts.
```

### Route ordering in FastAPI routers

```
Fixed paths (/me/..., /sa/..., /platform/...) MUST be declared before any
parameterised path (/{tenant_id}...). FastAPI matches in declaration order.
```

### Alembic migrations

```
NEVER reuse a revision ID. The next migration number = highest existing + 1
(check: ls backend/migrations/versions | sort | tail -3).
down_revision MUST equal the current single head.
Before committing a migration:  alembic heads  -> must print exactly ONE head.
Two heads, or "Revision X is present more than once", = STOP and fix.
The migration graph is unit-tested (backend/migrations/tests/test_migration_graph.py).
```

### Diagnosing "data is missing" / 500 from the gateway

```
1. Check every service is listening FIRST:
     curl -s http://localhost:<port>/health   for ports 8000-8004
   The gateway returns 503 SERVICE_UNAVAILABLE / 504 UPSTREAM_TIMEOUT when a downstream service is down (A2).
2. Service logs in logs/services/*.log are APPEND-ONLY. Read the END of the file
   and check timestamps — older tracebacks in the same file are unrelated.
3. NEVER add mock/demo data or frontend fallbacks to make a screen "work".
   Mock data hides backend failures and caused a week of false "fixes".
```

### Local development (current reality)

```
Despite §5, development currently runs locally: PostgreSQL 18 (smart_dev),
Redis, services started via scripts/start_backend.sh (ports 8000-8004),
secrets in the untracked root .env. Always `set -a; source .env; set +a`
before alembic/psql/pytest. Use `psql -w` with PGPASSWORD — psql otherwise
waits silently for a password prompt and looks like a hang.
```

### Git hygiene

```
NEVER `git stash pop` / `apply` a stash wholesale without reviewing
`git stash show -p` first. Never commit deletion of package-lock.json or
pnpm-lock.yaml. Abandoned work is ARCHIVED (archive/<name> branch), never deleted.
```

### Browser verification

```
Any change to a frontend screen is verified with Playwright, headless
Chromium ONLY, against http://localhost:3000 — never Claude in Chrome and
never the user's own browser (those are for the user's own driving, not
automated verification). If headless Chromium will not launch, STOP and
report the error — never silently skip the browser check or substitute curl.

Screenshots go to frontend/test-results/screens/<step>/ — gitignored, never
committed. Cover both English and Amharic (switch locale via
localStorage.setItem("locale","am") + reload, or the in-app language
switcher) for any screen whose text changed.

Collect console errors on every page the spec visits
(page.on("console", ...) filtered to type "error", plus page.on("pageerror"))
and print them raw at the end of the run — a step fails if an error appears
that the change under test introduced. The post-login 401 race (login()
patching the JWT into the session without the first API call waiting for
it) is fixed as of S10: demo-auth.ts's login() tracks the in-flight exchange
via getPendingJWTExchange(), api.ts's request() awaits it before reading the
session, and the login page awaits it before navigating — so a fresh login
no longer races its first authenticated call. frontend/tests/s9-sa-tenant.
spec.ts's loginAs() still contains the old wait-for-token workaround as
defensive redundancy; it is harmless and not required by new specs.
```

### Permanent E2E TA test account

```
frontend/tests/helpers/e2e-ta.ts exports E2E_TA_EMAIL ("e2e-ta@probe.local")
and e2eTaPasswordOrSkip(test) — every spec that needs a real TA login must
use these, never a hardcoded credential. The password is read ONLY from the
E2E_TA_PASSWORD environment variable (never committed); a test that needs a
TA session calls e2eTaPasswordOrSkip(test) at its top, which calls
test.skip() with a clear message when the env var is unset, so the suite
still runs (skipping just that test) for anyone without the password.

The account itself is tenant slug zz-e2e-ta ("E2E TA Test", STARTER,
MONTHLY), created once via the public sign-up endpoint. Unlike every other
z-prefixed probe tenant (all DEACTIVATED after their test run), zz-e2e-ta
stays ACTIVE always — it exists specifically so tests always have a known,
working TA login available without needing to create one ad hoc.
```

### Known gaps

```
§5's "pytest backend/ -v -m 'unit'" (local, no-DB unit run) silently SKIPS
every test file that has no explicit @pytest.mark.unit marker or pytestmark —
this includes all of backend/shared/billing/tests/ (test_payments.py,
test_addons.py, test_providers.py, test_subscriptions.py) and others. The
real CI test-backend job runs the FULL unfiltered suite ("pytest backend/
-v --tb=short --cov=backend", no -m filter) and does catch them. Don't trust
a green "-m unit" run alone as proof nothing broke — run the full unfiltered
suite (discovered 2026-10-07 during S10: two billing-test regressions from
an entitlements signature change were invisible under -m unit and only
surfaced on the full run). Fix pending: either mark every test file
consistently or stop filtering locally and just run the full suite.
```

