# SMART Inventory Management Platform — CLAUDE.md
> Claude Code implementation prompt file — derived from PRD v4.0.
> This is the slim index. Full detail (code samples, SQL, workflows) lives in `docs/claude/*.md` — see INDEX at the bottom. Nothing in the original file was deleted, only relocated.

---

## 1. Project Identity & Absolute Constraints

**SMART** is a multi-tenant SaaS inventory management platform. One codebase serves two personas —
**Producers/Importers** and **Retailers/Distributors** — differentiated entirely by `organisation_type`
on the tenant record. Initial target: **~12 mid-size companies**. Producers onboard in Phase 1,
Retailers in Phase 2.

### Never violate these rules — PRs that do are rejected

```
NEVER build separate codebases for producers vs retailers.
NEVER update stock balances directly — all mutations INSERT into inventory_transactions.
NEVER write directly to warehouse_stock — it is a computed read model maintained by ledger
  triggers. Application code never issues UPDATE warehouse_stock SET on_hand = … under any
  circumstances. Direct writes here bypass the immutable ledger and break balance integrity.
NEVER ship a new API endpoint without registering its action in permissions/registry.py.
NEVER run analytics or report queries on the primary database — read replicas only.
NEVER allow AI recommendations to auto-execute — status must be PENDING_APPROVAL first.
NEVER remove the parent_tenant_id column from the tenants table.
NEVER allow users to assign roles equal to or above their own level.
NEVER delete or update audit_log records — append-only enforced by PostgreSQL RULE.
NEVER use Apache Kafka, RabbitMQ, or aiokafka — async processing uses the Outbox Pattern.
NEVER reference external ERP systems — PostgreSQL is the system of record for everything.
NEVER write to the outbox table outside of the same DB transaction as the primary record.
NEVER hardcode English text in JSX/HTML — all UI strings must use i18n keys.
NEVER implement DIRPUSH as a named transaction type. Direct push from MWH to Sub-WH is
  handled by the existing PUSH state machine with a SUPPLY_FROM relationship bypassing
  intermediate nodes. No separate DIRPUSH code, endpoint, or permission entry exists.
NEVER call get_authority_scope() — it is archived dead code (only present in
  _ARCHIVED_personnel_pre031.py) and was never wired into the live check_permission()
  in backend/shared/permissions/middleware.py. Do not reintroduce calls to it.
NEVER implement a new facility-scoped feature with a raw warehouse_id equality check —
  node+descendant traversal is live (Phase 2). Any new ABAC check for a
  FACILITY_SCOPED_ROLE must go through get_descendant_node_ids() in
  hierarchy_service.py and resolve scope via check_permission() in middleware.py.
  See Rule 25 in docs/claude/business-rules.md for the full traversal contract.
```

---

## 2. Tech Stack (condensed — full detail: docs/claude/stack-and-repo.md)

- **Frontend**: React 18 + Next.js 14 (App Router), TypeScript 5 strict, Tailwind 3, PWA
  (service worker + offline queue), @zxing/browser scanning, idb, Zod, TanStack Query,
  Zustand, React Hook Form, cva, Playwright (e2e).
- **Backend**: Python 3.12 (Docker/ECS target); local dev currently runs 3.14 — code must
  stay 3.12-compatible (no 3.13+ only syntax/stdlib). FastAPI, SQLAlchemy 2 (async) + asyncpg,
  Alembic, Pydantic v2, python-casbin (RBAC+ABAC), python-jose (JWT), Celery, ruff, mypy, pytest.
- **Database**: Amazon RDS PostgreSQL 16 primary + read replica (ledger, RLS, outbox,
  JSONB, pg_trgm). Amazon ElastiCache for Redis (Celery broker, sessions, AI cache).
- **Async**: Transactional Outbox Pattern replaces Kafka — outbox table + pg_notify +
  Celery workers + beat fallback polling.
- **Infra**: GitHub + GitHub Actions, AWS ECS Fargate (all envs), Terraform (S3+DynamoDB
  remote state), S3, Secrets Manager (all secrets), CloudWatch. Cognito: archived
  (infra/terraform/_archived/cognito) — login is SMART-owned via POST /auth/token (Option B).
- **Observability**: Amazon Managed Prometheus/Grafana, OpenTelemetry → X-Ray (ADOT).
- **Search**: pg_trgm by default; Amazon OpenSearch only on explicit tenant request.
- **NOT in stack**: Kafka, RabbitMQ, Zookeeper, ERP systems, Docker Compose, self-hosted
  Redis/Prometheus/Grafana/Elasticsearch, AWS EKS.

## 3. Repository Structure (condensed — full layout: docs/claude/stack-and-repo.md)

```
frontend/src/{app,components,hooks,lib,store,types}       # Next.js App Router, PWA
backend/shared/{permissions,db,outbox,utils}               # registry.py = single source of truth
backend/services/<service>/{routers,services,repositories,schemas,tests}
backend/migrations/versions/                                # Alembic — one shared DB
locales/{en,am,or}.json                                      # language packs
infra/terraform/{modules,envs/{dev,stage,prod}}              # all infra as code
scripts/{seed_permissions,ci_drift_check,create_partitions}.py
docs/claude/*.md    docs/prompts/*.md    CLAUDE.md            # this file
```
No `.env.example` committed — secrets via AWS Secrets Manager (local-dev exception: see §8).

---

## 4. Core Conventions (full detail in the linked doc per topic)

- **RLS + indexing** (docs/claude/schema.md): every tenant-scoped table gets `ENABLE ROW LEVEL
  SECURITY` + a `tenant_isolation` policy in the SAME migration that creates it; every composite
  index leads with `tenant_id`. `set_rls_context()` must run before every query.
- **Alembic** (docs/claude/guardrails.md): exactly one head at all times (`alembic heads` →
  1 line); next revision number = highest existing + 1; every migration tests
  `upgrade head → downgrade -1 → upgrade head`; RLS policy included for new tenant tables.
- **Outbox** (docs/claude/outbox.md): `write_to_outbox()` is called inside the SAME DB
  transaction as the primary ledger INSERT — never after commit. Celery handlers are
  idempotent (check PENDING/PROCESSING/PROCESSED before acting).
- **Permissions** (docs/claude/backend-patterns.md): every route needs `@require_permission`
  with an action registered in `backend/shared/permissions/registry.py` — unregistered
  actions fail `scripts/ci_drift_check.py` in CI. Three enforcement layers are all mandatory:
  gateway JWT/role → service RBAC+ABAC+audit → PostgreSQL RLS. UI hiding is never a security
  layer by itself.
- **Ledger / warehouse_stock** (docs/claude/backend-patterns.md, docs/claude/schema.md):
  every stock mutation is an INSERT into `inventory_transactions`, never a direct balance
  UPDATE. `warehouse_stock` is a computed read model — the only permitted writer is
  `update_running_balance()` inside `ledger_repo.py`, in the same transaction as the ledger
  INSERT; a PostgreSQL RULE blocks direct UPDATEs as defence in depth.
- **i18n**: three locales — `en` (default), `am` (Amharic, required Phase 1), `or` (Oromifa,
  **deferred** — `or.json` is an English-value scaffold copied from `en.json` key-for-key
  until a native-speaker review is staffed). Loader/order: user locale → tenant default → `en`.

---

## 5. UI/UX Rules (one-liners — full rationale + regression tests: docs/claude/frontend-patterns.md)

- Never hide a zero-On-Hand product from Inventory — show it with an "Out of Stock" badge, sorted last.
- Never show a warehouse dropdown on Receive/Issue Stock — warehouse always comes from the JWT session, read-only.
- Never route an ISSUE through Reserved — it's a direct, immediate On Hand deduction with no reservation step.
- Never show the same transfer action button to both source and destination warehouse managers — only the owner of the next step sees an active button.
- Never scope the Products page stock total by viewing warehouse — it's always the tenant-wide sum.
- Always `.toLowerCase()` both sides when comparing warehouse UUIDs (JWT vs DB casing can differ).
- Never expose a UI action button whose target state is missing from the backend state machine — keep `getAvailableActions()` and `state_machine.py` in sync in the same PR.
- Never render a raw i18n key or a raw UUID as visible text — wrap in `t()` / resolve to a name first.
- Never commit frontend changes without `npx tsc --noEmit` (0 errors) and `bash scripts/check_i18n.sh` (PASS).

## 6. Org Hierarchy Rules (one-liners — full detail: docs/claude/business-rules.md)

- Max 5 levels per tenant; level names/role mappings are tenant-configurable, never hardcoded.
- Multiple root nodes allowed; `is_stock_holding=false` nodes participate only in approval chains, never hold stock.
- Authority scope always resolves via `get_descendant_node_ids()` — never inferred from role alone.
- Factory-specific products (`source_factory_id` set) are pullable only from that factory's subtree, enforced at the service layer, for PULL/PUSH/SISTER and dispatch lot selection alike.
- Every user has exactly one PRIMARY (permanent) assignment; ACTING/DELEGATE are time-bounded and don't appear in the JWT; expired assignments are ignored by all checks.
- Never hard-delete a user — deactivate (`is_active=false`) and close active ACTING/DELEGATE assignments instead.
- Never let a manager assign a role at or above their own level, for PRIMARY, ACTING, or DELEGATE.

## 7. Engineering Guardrails (condensed — incident history + exact commands: docs/claude/guardrails.md)

- Before any backend commit: the touched service must `import main` cleanly (route handlers evaluate Pydantic models at import time — models must be defined above their first route use), then restart and confirm `GET /health` = 200.
- FastAPI routers: fixed paths (`/me/...`, `/sa/...`, `/platform/...`) must be declared before any `/{tenant_id}...` parameterised path.
- Alembic: never reuse a revision ID; `alembic heads` must print exactly one head before committing.
- Diagnosing "missing data"/500s: check every service's `/health` first, read logs end-first (append-only), and never add mock/demo data or frontend fallbacks to mask a backend failure.
- Git hygiene: never `stash pop/apply` wholesale without `git stash show -p` first; never delete lockfiles; archive abandoned work, don't delete it.
- Frontend verification: Playwright, headless Chromium only, against localhost:3000 — never a live browser session for automated checks; cover en + am; collect and print console/page errors.
- Testing: the full unfiltered `pytest backend/ --cov=backend` is the real gate — `-m unit` silently skips unmarked files (e.g. all of `backend/shared/billing/tests/`) and must never be treated as sufficient proof alone.

## 8. Standing Session Rules

- Local commits only until a push is explicitly authorized for that session.
- Keep tool output raw and short — tails and one-line results, not full dumps.
- No direct SQL writes outside `BEGIN...ROLLBACK` unless the user explicitly asks to commit.
- Never alter a PostgreSQL `RULE` outside of an Alembic migration.
- Never reset a real user's password.
- Probe/test account passwords may be printed in plain output.
- Alex runs `pg_dump` himself before ANY migration — Claude never takes backups and never uses the postgres superuser password.
- Never add mock/demo data to a screen to make it appear to work (see §7).
- Root `.env` is local-only and untracked — never commit it; load with `set -a; source .env; set +a`. Holds E2E_TA_PASSWORD for the permanent `zz-e2e-ta` tenant.
- E2E_SA_PASSWORD is never put in `.env` and never set by Claude Code. Specs that need SA read it via `frontend/tests/helpers/sa-credentials.ts` and skip when it is unset; Alex sets it in his own terminal to run them. SA probe tenants come from `frontend/tests/helpers/sa-api.ts` (public sign-up: 5 per hour per IP).
- Never toggle FORCE ROW LEVEL SECURITY on any table outside an Alembic migration.
- Probe/test tenants are deactivated after use. Local dev only: they may be purged with scripts/delete_tenant.py (dry-run first, YES confirmation, after Alex's pg_dump). Never hard-delete tenants in staging or prod.
- Never set `ENVIRONMENT=local` anywhere but a developer machine — it enables the password-optional dev_email shortcut (auth.py). Production login is POST /auth/token {email, password}.
- Plan/package changes are SA-only (TA → 403 PLAN_CHANGE_SA_ONLY); TA can view, not change.
- Exception to the RULE policy: scripts/delete_tenant.py drops and recreates append-only RULEs inside its single purge transaction (local dev only). No other code may alter RULEs outside Alembic.
- Services refuse to start on unsafe config (weak JWT secret, RATE_LIMIT_* overrides, JWT_EXPIRE_MINUTES>60 outside local; stage/prod require EMAIL_DELIVERY_MODE=ses) — see ci-cd.md §6.
- Claude Code never uses SA credentials or an SA account — SA checks are Alex's, by hand.
- Run test suites in the foreground (background runs don't survive a pause).
- New permission → classify it for read-only (docs/claude/backend-patterns.md).

---

## INDEX — where the detail moved

| Doc | Holds | Read when |
|---|---|---|
| `docs/claude/stack-and-repo.md` | Full §2 tech stack + §3 repo tree (verbatim) | Setting up a new service/package or citing exact dependency versions |
| `docs/claude/schema.md` | Full §7 — all table DDL, RLS policies, column rules, Alembic migration rules | Writing a migration or new table |
| `docs/claude/outbox.md` | Full §8 — outbox flow, `write_to_outbox()`, Celery worker, event payload schemas, alert thresholds | Adding a new async side-effect or event type |
| `docs/claude/backend-patterns.md` | §9 service layout, §13 permission code (`check_permission`, JWT payload, role hierarchy), §14 ledger code + authority-scope history, §16 dispatch engine, §17 state machines, §18 offline sync, §19 API conventions, §20 AI pipeline | Writing any backend route, permission check, dispatch/state-machine logic, or AI/analytics task |
| `docs/claude/frontend-patterns.md` | §10 TS/Tailwind/PWA code, §11 barcode scanner, §12 i18n loader code, full §27 UI rules with regression-test names and root causes | Building a frontend screen or scanning feature |
| `docs/claude/testing.md` | Full §21 — the 15 required permission test cases per action + required suites (outbox, dispatch, localization, approval workflows, state machines, split requests, alerts) | Writing tests for a new permission or transaction type |
| `docs/claude/ci-cd.md` | §4 branch strategy/PR checklist, §5 AWS dev workflow, §6 env vars/secrets, §22 GitHub Actions workflows | Touching CI, branch policy, or secrets |
| `docs/claude/roadmap-perf.md` | §23 performance targets, §25 Phase 0 must-haves, §26 phase roadmap | Scoping new work against the roadmap or a perf target |
| `docs/claude/billing-and-tenants.md` | Full §15 — onboarding wizard, package catalog, self sign-up, billing/invoices/proration, add-ons (S4–S12 history) | Any tenant, plan, billing, or add-on work |
| `docs/claude/business-rules.md` | Full §24 business rules 1–27 + IMTS role mapping table, full §28 hierarchy/product-scoping/personnel rules | Checking whether a change violates an enforced business rule |
| `docs/claude/guardrails.md` | Full §29 — exact incident-driven commands and local-dev reality | Debugging an import/startup/migration failure |
| `docs/prompts/opening_balance.md` | Claude prompts for Option A (RECEIPT) and Option C (bulk import) opening-balance workflows | Building the initial stock entry assistant |
