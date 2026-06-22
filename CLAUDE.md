# SMART Inventory Management Platform — CLAUDE.md
> **Claude Code implementation prompt file — derived from PRD v4.0**
> Read this file in full before writing any code. Every section is a direct instruction.
> When in doubt, re-read the relevant section rather than guessing.

---

## Table of Contents

1. [Project Identity & Absolute Constraints](#1-project-identity--absolute-constraints)
2. [Tech Stack](#2-tech-stack)
3. [Repository Structure (GitHub)](#3-repository-structure-github)
4. [GitHub Workflow & Branch Strategy](#4-github-workflow--branch-strategy)
5. [Developer Workflow — AWS Dev Environment](#5-developer-workflow--aws-dev-environment)
6. [Environment Variables](#6-environment-variables)
7. [Database — PostgreSQL Schema & Conventions](#7-database--postgresql-schema--conventions)
8. [Transactional Outbox Pattern](#8-transactional-outbox-pattern)
9. [Backend — Python / FastAPI Architecture](#9-backend--python--fastapi-architecture)
10. [Frontend — TypeScript + Tailwind + PWA](#10-frontend--typescript--tailwind--pwa)
11. [Barcode Scanning](#11-barcode-scanning)
12. [Localization — English, Amharic, Oromifa](#12-localization--english-amharic-oromifa)
13. [Permission System — RBAC + ABAC](#13-permission-system--rbac--abac)
14. [Inventory Ledger — Immutable Rules](#14-inventory-ledger--immutable-rules)
15. [Tenant Profile & Onboarding Wizard](#15-tenant-profile--onboarding-wizard)
16. [Dispatch Strategy Engine](#16-dispatch-strategy-engine)
17. [Workflow State Machines](#17-workflow-state-machines)
18. [Offline Sync Strategy](#18-offline-sync-strategy)
19. [API Conventions](#19-api-conventions)
20. [AI & Analytics Pipeline](#20-ai--analytics-pipeline)
21. [Testing Requirements](#21-testing-requirements)
22. [CI/CD — GitHub Actions](#22-cicd--github-actions)
23. [Performance Targets](#23-performance-targets)
24. [Business Rules — Enforced by Code](#24-business-rules--enforced-by-code)
25. [Phase 0 — Must Exist Before Any User Is Onboarded](#25-phase-0--must-exist-before-any-user-is-onboarded)
26. [Phase Roadmap](#26-phase-roadmap)
27. [UI/UX Rules](#27-uiux-rules)

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
NEVER implement a new node-scoped feature assuming node+descendant traversal exists —
  it does not yet. The live FACILITY_SCOPED_ROLES check in middleware.py is flat
  exact-node equality (user.warehouse_id == resource.warehouse_id) with no DB call and
  no ancestry walk. A user's warehouse_id JWT claim is their assigned
  organization_node.id regardless of hierarchy level, but scoping stops there — it does
  not extend to that node's descendants. True node+descendant traversal (rebuilding
  get_authority_scope and threading a db session through check_permission and every
  @require_permission call site) is a tracked Phase 2 item, not yet implemented.
  See CLAUDE.md §13 "Role scope — facility-scoped vs tenant-wide" for the current detail.
```

---

## 2. Tech Stack

> **Ground rules applied:** AWS-only for all services · All SDLC environments (dev/stage/prod) on AWS —
> no local development environment · GitHub + GitHub Actions for version control and CI/CD.

```
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND                                                            │
│  React 18 + Next.js 14 (App Router)                                 │
│  TypeScript 5 — strict: true, noImplicitAny, strictNullChecks       │
│  Tailwind CSS 3 — utility-first, no inline styles                   │
│  Progressive Web App (PWA) — service worker, offline shell          │
│  @zxing/browser — camera barcode / QR scanning                      │
│  idb (IndexedDB wrapper) — offline transaction queue                │
│  Zod — runtime validation                                            │
│  TanStack Query — server state                                       │
│  Zustand — client state                                              │
│  React Hook Form + Zod — form handling                              │
│  class-variance-authority (cva) — Tailwind component variants       │
│  @hookform/resolvers — Zod resolver bridge for React Hook Form      │
│  clsx + tailwind-merge — className utility (cn() helper)            │
│  nanoid — idempotency key generation (offline sync)                 │
│  @playwright/test (devDep) — frontend e2e testing                   │
├─────────────────────────────────────────────────────────────────────┤
│  BACKEND                                                             │
│  Python 3.12                                                         │
│  FastAPI — REST API framework                                        │
│  SQLAlchemy 2.x (async) + asyncpg — ORM and PostgreSQL driver       │
│  Alembic — versioned, reversible database migrations                │
│  Pydantic v2 — request/response models and outbox payload schemas   │
│  python-casbin (casbin-async) — RBAC + ABAC permission enforcement  │
│  python-jose — JWT handling                                          │
│  Celery — outbox worker task queue (broker → ElastiCache)           │
│  ruff — linting and formatting                                       │
│  mypy — static type checking (strict)                               │
│  pytest + pytest-asyncio + httpx — testing                          │
│  bcrypt — password hashing (auth-service, tenant-service)           │
│  python-multipart — FastAPI UploadFile support (product-service)    │
│  casbin-async-sqlalchemy-adapter — SQLAlchemy adapter for casbin    │
│  requests (test-only) — e2e test HTTP client (tests/e2e/ only)      │
├─────────────────────────────────────────────────────────────────────┤
│  DATABASE                                                            │
│  Amazon RDS for PostgreSQL 16 (primary)                             │
│    — ledger, RLS, outbox, JSONB, pg_trgm extension                  │
│  Amazon RDS for PostgreSQL 16 (read replica)                        │
│    — analytics, reports, AI ETL. Never transactional writes.        │
│  PostgreSQL LISTEN/NOTIFY — outbox worker wakeup (built into RDS)   │
│  Amazon ElastiCache for Redis                                        │
│    — Celery broker, session cache, AI forecast cache                │
├─────────────────────────────────────────────────────────────────────┤
│  ASYNC PROCESSING (replaces Kafka)                                   │
│  Transactional Outbox Pattern                                        │
│  outbox table — written in same DB transaction as primary record    │
│  pg_notify trigger — fires on every outbox INSERT                   │
│  Celery workers — consume outbox rows, process side effects         │
│  Celery beat — 30s fallback polling when NOTIFY is missed           │
│  Upgrade path: ElastiCache Streams (Phase 3), Amazon SQS (Phase 4) │
├─────────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE                                                      │
│  GitHub + GitHub Actions — version control and CI/CD                │
│  AWS ECS Fargate — all containers, all environments (dev/stage/prod)│
│  Terraform — all infrastructure as code                             │
│    — remote state: AWS S3 + DynamoDB locking                        │
│    — one workspace per environment                                   │
│  AWS Cognito — identity provider                                     │
│  AWS S3 — attachments, documents, language pack JSON files          │
│  AWS Secrets Manager — ALL secrets in all environments              │
│    — injected into ECS task definitions at startup                  │
│    — read by GitHub Actions via OIDC (no long-lived credentials)    │
│  AWS CloudWatch — alarms: outbox depth, uptime, error rate          │
├─────────────────────────────────────────────────────────────────────┤
│  OBSERVABILITY                                                       │
│  Amazon Managed Service for Prometheus (AMP) — metrics collection   │
│  Amazon Managed Grafana (AMG) — dashboards and alerting             │
│  OpenTelemetry → AWS X-Ray via ADOT — distributed tracing          │
│  AWS CloudWatch — log aggregation and production alarms             │
├─────────────────────────────────────────────────────────────────────┤
│  SEARCH                                                              │
│  PostgreSQL pg_trgm — default SKU search for all tenants            │
│  Amazon OpenSearch Service — conditional: explicit tenant request   │
│    only. Not triggered by SKU count. Replaces self-hosted ES 8.     │
│                                                                      │
│  NOT IN THIS STACK: Apache Kafka · RabbitMQ · Zookeeper · ERP       │
│  systems · Docker Compose · self-hosted Redis · self-hosted          │
│  Prometheus/Grafana · self-hosted Elasticsearch · AWS EKS           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Repository Structure (GitHub)

```
smart-platform/                        # GitHub repository root
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                     # Every PR: lint, typecheck, test, drift check
│   │   ├── deploy-dev.yml             # Merge to develop → dev environment (auto)
│   │   ├── deploy-staging.yml         # Merge to main → stage environment (smoke-test gate)
│   │   └── deploy-prod.yml            # Release tag → prod (manual approval required)
│   ├── PULL_REQUEST_TEMPLATE.md       # PR checklist
│   └── CODEOWNERS                     # Extra review for permissions/ and migrations/
│
├── frontend/
│   ├── src/
│   │   ├── app/                       # Next.js App Router pages
│   │   ├── components/
│   │   │   ├── ui/                    # Primitive Tailwind components
│   │   │   └── features/              # Feature-specific components
│   │   ├── hooks/                     # useAuth, usePermission, useOfflineSync, useScanner
│   │   ├── lib/
│   │   │   ├── api.ts                 # Typed fetch wrapper
│   │   │   ├── auth.ts                # JWT handling, session
│   │   │   ├── permissions.ts         # usePermission() — display only, not security
│   │   │   ├── scanner.ts             # @zxing/browser wrapper
│   │   │   └── i18n.ts                # Language pack loader (en | am | or)
│   │   ├── store/
│   │   │   └── offlineQueue.ts        # IndexedDB offline transaction queue
│   │   └── types/                     # Auto-generated from OpenAPI spec in CI
│   ├── public/sw.js                   # Service worker (PWA)
│   ├── tailwind.config.ts
│   ├── tsconfig.json                  # strict: true
│   └── package.json
│
├── backend/
│   ├── shared/                        # Shared Python packages (editable installs)
│   │   ├── permissions/
│   │   │   ├── registry.py            # SINGLE SOURCE OF TRUTH — all 115 actions
│   │   │   ├── middleware.py          # check_permission(), require_permission decorator
│   │   │   ├── hierarchy_service.py   # node+descendant scope traversal
│   │   │   ├── casbin_enforcer.py     # Casbin RBAC+ABAC setup
│   │   │   └── audit.py              # audit_log() — called on every access decision
│   │   ├── db/
│   │   │   ├── session.py             # Async SQLAlchemy engine, session factory
│   │   │   ├── rls.py                 # set_rls_context() — must run before every query
│   │   │   └── models/                # SQLAlchemy ORM models (all tables)
│   │   ├── outbox/
│   │   │   ├── writer.py              # write_to_outbox() — called inside transactions
│   │   │   ├── worker.py              # Celery tasks — idempotent outbox processors
│   │   │   ├── notify.py              # asyncpg LISTEN for pg_notify wakeup
│   │   │   └── schemas.py             # Pydantic payload models, versioned
│   │   └── utils/
│   │       ├── idempotency.py
│   │       └── pagination.py
│   │
│   ├── services/
│   │   ├── api-gateway/               # FastAPI — JWT, rate limiting, plan cap
│   │   ├── auth-service/              # Cognito integration, token issuance
│   │   ├── tenant-service/            # Tenant CRUD, wizard, org_type
│   │   ├── product-service/           # Products, SKU, dispatch strategy config
│   │   ├── inventory-service/         # Ledger, balances, receive, transfer, issue
│   │   ├── order-service/             # Orders and shipments
│   │   ├── logistics-service/         # Fleet, routes, drivers
│   │   ├── analytics-service/         # AI pipeline, forecasting
│   │   ├── notification-service/      # Alerts via Celery outbox workers
│   │   └── sync-service/              # Offline sync, conflict resolution
│   │
│   └── migrations/                    # Alembic — all services share one PostgreSQL DB
│       ├── env.py
│       ├── alembic.ini
│       └── versions/
│
├── locales/                           # Language pack JSON files
│   ├── en.json                        # English (default)
│   ├── am.json                        # Amharic
│   └── or.json                        # Oromifa (Afaan Oromoo)
│
├── infra/
│   └── terraform/                     # ALL infrastructure as code — no docker-compose
│       ├── modules/
│       │   ├── ecs/                   # ECS Fargate cluster, task definitions, services
│       │   ├── rds/                   # RDS PostgreSQL primary + read replica
│       │   ├── elasticache/           # ElastiCache for Redis
│       │   ├── cognito/               # Cognito user pool + app client
│       │   ├── s3/                    # S3 buckets (attachments, locales)
│       │   ├── secrets/               # Secrets Manager secrets (references only)
│       │   ├── observability/         # AMP, AMG, X-Ray, CloudWatch alarms
│       │   └── networking/            # VPC, subnets, security groups
│       ├── envs/
│       │   ├── dev/                   # Dev environment workspace
│       │   ├── stage/                 # Stage environment workspace
│       │   └── prod/                  # Prod environment workspace
│       └── backend.tf                 # Remote state: S3 bucket + DynamoDB lock table
│
├── scripts/
│   ├── seed_permissions.py            # Seeds all 115 actions from registry.py
│   ├── ci_drift_check.py             # Fails CI if any route lacks @require_permission
│   └── create_partitions.py          # Monthly inventory_transactions partitions
│
└── CLAUDE.md                          # This file
                                       # No .env.example — all secrets via AWS Secrets Manager
```

---

## 4. GitHub Workflow & Branch Strategy

### Branches

```
main          protected — production-ready, no direct pushes
develop       integration branch — all features target here
feature/<ticket>-<slug>   e.g. feature/SMART-42-fefo-dispatch
fix/<ticket>-<slug>       e.g. fix/SMART-88-rls-context
chore/<slug>              e.g. chore/add-oromifa-locale
```

### Branch protection rules

- `main` and `develop`: 1 reviewer minimum, all CI checks must pass
- `CODEOWNERS` requires a second reviewer for `backend/shared/permissions/` and `backend/migrations/`

### PR checklist — `.github/PULL_REQUEST_TEMPLATE.md`

```markdown
## Checklist

### Permissions
- [ ] New routes have @require_permission applied
- [ ] New actions added to backend/shared/permissions/registry.py
- [ ] CI permission drift check passes

### Database
- [ ] Alembic migration created (descriptive name)
- [ ] Tested: upgrade head → downgrade -1 → upgrade head
- [ ] All new tables have tenant_id as leading index column
- [ ] RLS policy added for every new tenant-scoped table

### Outbox
- [ ] State-changing services write to outbox in the SAME DB transaction
- [ ] Celery task handlers are idempotent

### Inventory integrity
- [ ] No direct UPDATE inventory_balances — ledger INSERT only
- [ ] Idempotency key used for every new transaction type

### Frontend
- [ ] TypeScript strict — no `any` added
- [ ] Tailwind only — no inline style= attributes
- [ ] All UI strings use i18n keys — no hardcoded English text
```

### Commit convention

```
feat(inventory): add FEFO dispatch engine with lot cascade
fix(outbox): mark row PROCESSED after successful retry
feat(i18n): add Oromifa language pack or.json
chore(db): monthly partitions for inventory_transactions Q3-2026
test(permissions): 15 test cases for dispatch:fefo_override
```

---

## 5. Developer Workflow — AWS Dev Environment

> There is no local development environment. All SDLC environments (dev, stage, prod) run on AWS.
> Docker Desktop and Docker Compose are not used. There is no `.env` file.
> All secrets are stored in AWS Secrets Manager and injected at runtime.

### Prerequisites

```
python 3.12    uv    node 20    pnpm    aws-cli v2    terraform
GitHub account with access to smart-platform repo
AWS IAM identity with dev environment permissions (provisioned by Tech Lead via Terraform)
```

### Developer workflow

```
1. Pull latest from develop
2. Create feature branch:  git checkout -b feature/SMART-<n>-<slug>
3. Write code and tests locally (IDE only — no local services running)
4. Push branch → GitHub Actions CI runs automatically against dev AWS environment
5. Review CI results (lint, type-check, tests, drift-check) in the PR
6. Address feedback, push fixes → CI re-runs
7. PR approved + all checks green → merge to develop → auto-deploys to dev environment
```

### Connecting to the dev environment (read-only inspection)

```bash
# Authenticate to AWS (SSO or IAM Identity Center — configured by Tech Lead)
aws sso login --profile smart-dev

# View live ECS service logs
aws logs tail /ecs/smart-dev/inventory-service --follow --profile smart-dev

# Port-forward to dev RDS for read-only inspection (never write directly)
aws ssm start-session \
  --target <bastion-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"portNumber":["5432"],"localPortNumber":["5433"]}' \
  --profile smart-dev
# Then: psql postgresql://smart_readonly:<pass>@localhost:5433/smart_inventory
# Password retrieved from: aws secretsmanager get-secret-value \
#   --secret-id smart/dev/db/readonly --profile smart-dev

# Run a one-off migration against dev (Tech Lead approval required)
aws ecs run-task \
  --cluster smart-dev \
  --task-definition smart-dev-migration \
  --launch-type FARGATE \
  --profile smart-dev
```

### Running tests locally (unit tests only — no AWS services needed)

```bash
# Install dependencies
cd backend/shared && uv pip install -e ".[test]"

# Unit tests only (no DB, no Redis required)
pytest backend/ -v -m "unit" --tb=short

# Integration tests run in CI against dev AWS — not locally
```

### Secrets — never in code, never in .env files

```
All secrets live in AWS Secrets Manager under the path:
  smart/{env}/{service}/{secret-name}
  e.g.  smart/dev/db/primary-url
        smart/dev/elasticache/redis-url
        smart/dev/cognito/client-secret
        smart/prod/jwt/signing-key

ECS task definitions reference secrets by ARN — injected as env vars at container startup.
GitHub Actions reads secrets via OIDC (no long-lived AWS credentials stored in GitHub).
Never commit secrets, connection strings, or passwords to the repository.
```

---

## 6. Environment Variables & Secrets

> ### LOCAL DEV EXCEPTION (Temporary — Pre-AWS Phase Only)
> A `.env` file exists at `smart-platform/.env` for local prototyping only.
> This is **NOT** the production pattern. When the AWS dev environment is provisioned:
> - Delete the `.env` file
> - Remove this section from CLAUDE.md
> - All secrets revert to AWS Secrets Manager exclusively
> - CI/CD uses OIDC — no `.env` in any pipeline

> **No `.env` files anywhere in this project.** All secrets are stored in AWS Secrets Manager.
> ECS task definitions pull secrets by ARN at container startup. GitHub Actions reads them
> via GitHub OIDC + AWS IAM role — no long-lived credentials stored in GitHub Secrets.

### Secret naming convention — AWS Secrets Manager

```
smart/{env}/{category}/{name}

Environment:  dev | stage | prod
Examples:
  smart/dev/db/primary-url              → DATABASE_URL
  smart/dev/db/read-replica-url         → DATABASE_READ_URL
  smart/dev/elasticache/redis-url       → REDIS_URL
  smart/dev/elasticache/celery-broker   → CELERY_BROKER_URL
  smart/dev/elasticache/celery-backend  → CELERY_RESULT_BACKEND
  smart/dev/jwt/secret                  → JWT_SECRET
  smart/dev/cognito/user-pool-id        → AWS_COGNITO_USER_POOL_ID
  smart/dev/cognito/client-id           → AWS_COGNITO_CLIENT_ID
  smart/dev/cognito/client-secret       → AWS_COGNITO_CLIENT_SECRET
  smart/prod/opensearch/url             → OPENSEARCH_URL  (conditional — if triggered)
```

### Environment variable reference — injected at ECS task startup

```bash
# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL          # RDS primary — postgresql+asyncpg://<host>:5432/smart_inventory
DATABASE_READ_URL     # RDS read replica — postgresql+asyncpg://<host>:5432/smart_inventory
DATABASE_POOL_SIZE=20

# ── Cache / Celery (Amazon ElastiCache for Redis) ───────────────────────────
REDIS_URL             # redis://<elasticache-endpoint>:6379/0
CELERY_BROKER_URL     # redis://<elasticache-endpoint>:6379/1
CELERY_RESULT_BACKEND # redis://<elasticache-endpoint>:6379/2

# ── Outbox ───────────────────────────────────────────────────────────────────
OUTBOX_POLL_INTERVAL_SECONDS=30
OUTBOX_MAX_RETRIES=5
OUTBOX_ALERT_THRESHOLD=500     # CloudWatch alarm fires when PENDING depth exceeds this

# ── Auth ─────────────────────────────────────────────────────────────────────
JWT_SECRET            # min 64 random chars — from Secrets Manager
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
AWS_COGNITO_REGION=us-east-1
AWS_COGNITO_USER_POOL_ID      # from Secrets Manager
AWS_COGNITO_CLIENT_ID         # from Secrets Manager
AWS_COGNITO_CLIENT_SECRET     # from Secrets Manager

# ── AWS ──────────────────────────────────────────────────────────────────────
AWS_REGION=us-east-1
AWS_S3_BUCKET=smart-{env}-attachments
AWS_S3_LOCALE_PATH=locales/   # en.json, am.json, or.json live here

# ── Search (conditional — only present if OpenSearch tenant request triggered) ─
OPENSEARCH_URL        # https://<opensearch-domain-endpoint>

# ── Observability ────────────────────────────────────────────────────────────
OTEL_EXPORTER_OTLP_ENDPOINT   # ADOT collector sidecar endpoint on ECS task
LOG_LEVEL=INFO
LOG_FORMAT=json

# ── Frontend (Next.js — injected at build time by GitHub Actions) ────────────
NEXT_PUBLIC_API_URL           # https://api.{env}.smart-platform.com
NEXT_PUBLIC_DEFAULT_LOCALE=en # en | am | or
```

### How secrets flow per context

```
┌─────────────────────┬────────────────────────────────────────────────────┐
│ Context             │ How secrets are provided                           │
├─────────────────────┼────────────────────────────────────────────────────┤
│ ECS tasks           │ Task definition references Secrets Manager ARNs.  │
│ (all environments)  │ AWS injects values as env vars at container start. │
├─────────────────────┼────────────────────────────────────────────────────┤
│ GitHub Actions CI   │ OIDC token → assumes aws-ci IAM role →            │
│ (test / deploy)     │ reads smart/dev/* from Secrets Manager.           │
│                     │ No long-lived AWS_ACCESS_KEY_ID in GitHub Secrets. │
├─────────────────────┼────────────────────────────────────────────────────┤
│ Terraform           │ Reads existing secret ARNs; does NOT store secret  │
│                     │ values in state. Secrets are created separately    │
│                     │ and referenced by ARN in task definitions.         │
├─────────────────────┼────────────────────────────────────────────────────┤
│ Developer machines  │ Read-only CLI access via SSO for inspection only.  │
│                     │ Never write secrets or connection strings locally.  │
└─────────────────────┴────────────────────────────────────────────────────┘
```

### NEVER rules for secrets

```
NEVER commit a secret, password, or connection string to the repository.
NEVER create a .env file in any environment.
NEVER store AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in GitHub Secrets.
NEVER hardcode secret values in Terraform files or ECS task definition JSON.
NEVER log environment variable values — mask all secrets in CloudWatch log groups.
```

---

## 7. Database — PostgreSQL Schema & Conventions

### Column rules for every table

```
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID NOT NULL                       — on every tenant-scoped table
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
created_by      UUID                                — on all transactional tables
is_active       BOOLEAN NOT NULL DEFAULT true       — soft delete, never hard-delete
```

### Index rule — `tenant_id` leads every composite index

```sql
-- CORRECT
CREATE INDEX idx_products_tenant_sku ON products (tenant_id, sku);
-- WRONG — tenant_id not leading
CREATE INDEX idx_products_sku ON products (sku);
```

### Product SKU generation — `sku` vs `sku_override`

```
SKUs are server-generated from type_code + sequence. The sku field in POST /products
is ignored. Use sku_override to supply a custom SKU — this is the only path that
triggers the uq_products_tenant_sku uniqueness check.
```

### RLS — apply to every tenant-scoped table in the same migration

```sql
ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <table_name>
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

### Set RLS context before every query

```python
# backend/shared/db/rls.py
async def set_rls_context(session: AsyncSession, tenant_id: str, user_id: str) -> None:
    """Must be called at the start of every request handler. Without this, RLS blocks all queries."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id',:tid,true),"
             "set_config('app.current_user_id',:uid,true)"),
        {"tid": tenant_id, "uid": user_id}
    )
```

### Core schema — Phase 0 required tables

```sql
CREATE TYPE organisation_type AS ENUM ('PRODUCER', 'RETAILER', 'HYBRID');
CREATE TYPE transaction_type  AS ENUM (
  'RECEIVE','TRANSFER_OUT','TRANSFER_IN','ISSUE',
  'ADJUSTMENT','RESERVE','RELEASE','RETURN','COUNT_VARIANCE');
CREATE TYPE dispatch_strategy AS ENUM ('FEFO','FIFO','LIFO');
-- IMTS enhancement: type-specific transfer statuses replace the single transfer_status enum
CREATE TYPE pull_status AS ENUM (
  'DRAFT','PENDING_REVIEW','PENDING_APPROVAL','APPROVED','ISSUED',
  'IN_TRANSIT','PARTIALLY_RECEIVED','RECEIVED','COMPLETED','REJECTED','CANCELLED');
CREATE TYPE push_status AS ENUM (
  'DRAFT','PENDING_APPROVAL','APPROVED','ADVISED','ISSUED',
  'IN_TRANSIT','PARTIALLY_RECEIVED','RECEIVED','COMPLETED','REJECTED','CANCELLED');
CREATE TYPE sister_status AS ENUM (
  'DRAFT','PENDING_SOURCE_CONFIRM','PENDING_DEST_CONFIRM','PENDING_APPROVAL',
  'APPROVED','ISSUED','IN_TRANSIT','PARTIALLY_RECEIVED','RECEIVED','COMPLETED',
  'REJECTED','CANCELLED');
CREATE TYPE adjustment_status AS ENUM ('DRAFT','PENDING_APPROVAL','APPROVED','POSTED','REJECTED');
-- Legacy kept for backward compatibility during migration
CREATE TYPE transfer_status   AS ENUM (
  'DRAFT','SUBMITTED','APPROVED','IN_TRANSIT','RECEIVED','CLOSED','REJECTED','CANCELLED');
-- IMTS: org node relationship types
CREATE TYPE node_relationship AS ENUM ('PRIMARY_REPORTS_TO','SUPPLY_FROM','DISTRIBUTE_TO');
CREATE TYPE role_code         AS ENUM ('SA','TA','NM','RM','WM','LM','SA_GT','RT','AU','SYS');
CREATE TYPE grant_type        AS ENUM ('FULL','CONDITIONAL','READ_ONLY');
CREATE TYPE outbox_status     AS ENUM ('PENDING','PROCESSING','PROCESSED','FAILED');
CREATE TYPE supported_locale  AS ENUM ('en','am','or');

-- Tenants — parent_tenant_id is Phase 4 placeholder, NEVER DROP THIS COLUMN
CREATE TABLE tenants (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                VARCHAR(255) NOT NULL,
  organisation_type   organisation_type NOT NULL,
  parent_tenant_id    UUID REFERENCES tenants(id),   -- Phase 4 franchise — NEVER DROP
  plan_id             UUID NOT NULL,
  feature_flags       JSONB NOT NULL DEFAULT '{}',
  sku_cap             INTEGER,                        -- NULL = unlimited (RETAILER)
  approval_thresholds JSONB NOT NULL DEFAULT '{}',
  default_locale      supported_locale NOT NULL DEFAULT 'en',
  onboarding_complete BOOLEAN NOT NULL DEFAULT false,
  is_active           BOOLEAN NOT NULL DEFAULT true,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- inventory_transactions — MUST be partitioned from Phase 0
CREATE TABLE inventory_transactions (
  id               UUID NOT NULL DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL,
  transaction_date DATE NOT NULL,
  type             transaction_type NOT NULL,
  product_id       UUID NOT NULL,
  warehouse_id     UUID NOT NULL,         -- maps to organization_node.id (IMTS: facility_id)
  quantity         NUMERIC(15,4) NOT NULL,
  unit_cost        NUMERIC(15,4),
  lot_number       VARCHAR(100),
  expiry_date      DATE,
  idempotency_key  VARCHAR(255) NOT NULL,
  reference_id     UUID,
  -- IMTS: parent_transfer_id links split-request legs to their parent record
  parent_transfer_id UUID REFERENCES inventory_transactions(id),
  -- IMTS: estimated vs actual arrival tracking (required for In Transit overdue alerts)
  estimated_arrival_date DATE,
  actual_arrival_date    DATE,
  source           VARCHAR(20) DEFAULT 'WEB',
  created_by       UUID NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, transaction_date)
) PARTITION BY RANGE (transaction_date);

CREATE TABLE inventory_transaction_keys (
  idempotency_key VARCHAR(255) PRIMARY KEY,
  transaction_id  UUID NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_inv_tx_tenant_product
  ON inventory_transactions (tenant_id, product_id, transaction_date);

-- Outbox — replaces Kafka topics
CREATE TABLE outbox (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL,
  event_type   VARCHAR(100) NOT NULL,
  payload      JSONB NOT NULL,
  payload_ver  VARCHAR(10) NOT NULL DEFAULT '1.0',
  status       outbox_status NOT NULL DEFAULT 'PENDING',
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);
CREATE INDEX idx_outbox_pending ON outbox (status, created_at)
  WHERE status IN ('PENDING','FAILED');

-- NOTIFY trigger — wakes Celery workers immediately on INSERT
CREATE OR REPLACE FUNCTION notify_outbox() RETURNS TRIGGER AS $$
BEGIN
  PERFORM pg_notify('outbox_insert', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outbox_notify AFTER INSERT ON outbox
  FOR EACH ROW EXECUTE FUNCTION notify_outbox();

-- ── warehouse_stock — COMPUTED READ MODEL (never write directly from application code) ─
--
-- CRITICAL: warehouse_stock is a materialised read model derived entirely from
-- inventory_transactions INSERTs. Application code NEVER issues:
--   UPDATE warehouse_stock SET on_hand = …
-- Doing so bypasses the immutable ledger, breaks audit trails, and violates Business Rule #2.
--
-- How balances are maintained:
--   1. record_transaction() INSERTs a row into inventory_transactions (the ledger).
--   2. update_running_balance() is called in the same DB transaction and issues
--      UPDATE warehouse_stock SET … only from within ledger_repo.py.
--   3. No other code path may touch warehouse_stock columns directly.
--   4. warehouse_stock is queried (SELECT) freely for dashboards and balance checks.
--
-- The IMTS warehouse_stock table referenced in IMTS §13.2 is this same table.
-- It is NOT an independent mutable store. It is a denormalised read cache of ledger state.
CREATE TABLE warehouse_stock (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  facility_id    UUID NOT NULL REFERENCES organization_node(id),
  product_id     UUID NOT NULL,
  on_hand        NUMERIC(15,4) NOT NULL DEFAULT 0,
  reserved       NUMERIC(15,4) NOT NULL DEFAULT 0,
  in_transit_in  NUMERIC(15,4) NOT NULL DEFAULT 0,
  in_transit_out NUMERIC(15,4) NOT NULL DEFAULT 0,
  -- available is always computed: on_hand - reserved. Never stored separately.
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, facility_id, product_id)
);
CREATE INDEX idx_wstock_tenant_facility ON warehouse_stock (tenant_id, facility_id);
ALTER TABLE warehouse_stock ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON warehouse_stock
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
-- Prevent any direct UPDATE from outside ledger_repo.py at the DB level (defence in depth)
-- Note: update_running_balance() in ledger_repo.py uses a privileged session role that
-- bypasses this check. All other application sessions are denied direct writes.
CREATE RULE no_direct_stock_update AS ON UPDATE TO warehouse_stock
  WHERE current_setting('app.ledger_write_allowed', true) IS DISTINCT FROM 'true'
  DO INSTEAD NOTHING;
CREATE TABLE dispatch_strategy_configs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES tenants(id),
  scope          VARCHAR(20) NOT NULL CHECK (scope IN ('PRODUCT','CATEGORY')),
  scope_id       UUID NOT NULL,
  strategy       dispatch_strategy NOT NULL,
  effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
  configured_by  UUID NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_dispatch_scope
  ON dispatch_strategy_configs (tenant_id, scope, scope_id);

-- Audit logs — append-only
CREATE TABLE audit_logs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id       UUID,
  role          role_code,
  action        VARCHAR(100) NOT NULL,
  resource_type VARCHAR(100),
  resource_id   UUID,
  decision      VARCHAR(20) NOT NULL,
  reason        TEXT,
  abac_context  JSONB,
  ip_address    INET,
  request_id    VARCHAR(100)
);
CREATE INDEX idx_audit_tenant_ts ON audit_logs (tenant_id, timestamp);
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_select ON audit_logs FOR SELECT
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
-- Immutability — these rules must NEVER be removed
CREATE RULE no_update_audit AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE no_delete_audit AS ON DELETE TO audit_logs DO INSTEAD NOTHING;

-- ── IMTS: Organisational Hierarchy Tables ─────────────────────────────────────

-- Tenant hierarchy configuration — supports 2-to-5 level org structures per tenant
CREATE TABLE tenant_hierarchy_config (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id),
  level        INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
  label        VARCHAR(100) NOT NULL,   -- e.g. 'Main Production', 'Region', 'Warehouse'
  code         VARCHAR(20) NOT NULL,    -- e.g. 'MAIN', 'REG', 'WH'
  is_mandatory BOOLEAN NOT NULL DEFAULT false,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, level)
);
CREATE INDEX idx_hier_config_tenant ON tenant_hierarchy_config (tenant_id);
ALTER TABLE tenant_hierarchy_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenant_hierarchy_config
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- Organisation nodes — each facility (MWH, RWH, WH, Sub-WH) is a node
-- warehouse_id in JWT payload maps to organization_node.id regardless of hierarchy level
CREATE TABLE organization_node (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES tenants(id),
  name             VARCHAR(255) NOT NULL,
  code             VARCHAR(50) NOT NULL,
  hierarchy_level  INTEGER NOT NULL,   -- references tenant_hierarchy_config.level
  is_active        BOOLEAN NOT NULL DEFAULT true,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_org_node_tenant ON organization_node (tenant_id, hierarchy_level);
ALTER TABLE organization_node ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON organization_node
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- Org node relationships — separates reporting from supply network topology
-- A facility can report to one parent but receive stock from multiple sources
CREATE TABLE org_node_hierarchy (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id),
  from_node_id      UUID NOT NULL REFERENCES organization_node(id),
  to_node_id        UUID NOT NULL REFERENCES organization_node(id),
  relationship_type node_relationship NOT NULL,
  is_preferred      BOOLEAN NOT NULL DEFAULT false,  -- preferred supply source
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_org_hier_from ON org_node_hierarchy (tenant_id, from_node_id, relationship_type);
CREATE INDEX idx_org_hier_to   ON org_node_hierarchy (tenant_id, to_node_id, relationship_type);
ALTER TABLE org_node_hierarchy ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON org_node_hierarchy
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── IMTS: Configurable Approval Workflow Tables ───────────────────────────────

-- approval_rule — per-tenant, per-transaction-type, threshold-based routing config
CREATE TABLE approval_rule (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id),
  transaction_type  VARCHAR(20) NOT NULL,   -- 'PULL','PUSH','SISTER','DAMAGE','EXCESS'
  min_quantity      NUMERIC(15,4),           -- NULL = applies to any quantity
  max_quantity      NUMERIC(15,4),           -- NULL = no upper bound
  approver_role     role_code NOT NULL,
  approval_order    INTEGER NOT NULL DEFAULT 1,
  is_active         BOOLEAN NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approval_rule_tenant ON approval_rule (tenant_id, transaction_type);
ALTER TABLE approval_rule ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON approval_rule
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- approval_history — full audit trail of every approval action on every transaction
CREATE TABLE approval_history (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES tenants(id),
  transaction_id   UUID NOT NULL,
  approval_rule_id UUID REFERENCES approval_rule(id),
  approver_id      UUID NOT NULL,
  approver_role    role_code NOT NULL,
  action           VARCHAR(20) NOT NULL,  -- 'APPROVED','REJECTED','ESCALATED','AUTO_APPROVED'
  notes            TEXT,
  actioned_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approval_hist_tx ON approval_history (tenant_id, transaction_id);
ALTER TABLE approval_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON approval_history
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
-- Approval history is append-only — no UPDATE or DELETE permitted
CREATE RULE no_update_approval_hist AS ON UPDATE TO approval_history DO INSTEAD NOTHING;
CREATE RULE no_delete_approval_hist AS ON DELETE TO approval_history DO INSTEAD NOTHING;

-- ── IMTS: Enhanced Stock Threshold Table ─────────────────────────────────────
-- Replaces the implied per-product threshold concept with an explicit table
-- including preferred and secondary source facility references
CREATE TABLE stock_threshold (
  id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                  UUID NOT NULL REFERENCES tenants(id),
  facility_id                UUID NOT NULL REFERENCES organization_node(id),
  product_id                 UUID NOT NULL,
  max_threshold              NUMERIC(15,4) NOT NULL,
  reorder_point              NUMERIC(15,4) NOT NULL,
  min_threshold              NUMERIC(15,4) NOT NULL,
  preferred_source_id        UUID REFERENCES organization_node(id),  -- IMTS: preferred source
  secondary_source_id        UUID REFERENCES organization_node(id),  -- IMTS: fallback source
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, facility_id, product_id)
);
CREATE INDEX idx_threshold_tenant_facility ON stock_threshold (tenant_id, facility_id);
ALTER TABLE stock_threshold ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stock_threshold
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

### Alembic migration rules

```
Every migration must:
  1. Have a descriptive name:  alembic revision --autogenerate -m "add_dispatch_strategy_configs"
  2. Implement both upgrade() and downgrade()
  3. Be tested: alembic upgrade head → downgrade -1 → upgrade head
  4. Include RLS policy if the table is tenant-scoped
  5. Include composite indexes with tenant_id as the leading column
```

---

## 8. Transactional Outbox Pattern

This replaces Apache Kafka. It provides equivalent async behaviour with zero new infrastructure.

### How it works

```
1. Service receives a request (e.g. receive stock)
2. In ONE database transaction:
   a. INSERT into inventory_transactions  (immutable ledger)
   b. INSERT into outbox                  (side-effect queue)
   Both succeed or both roll back — atomically.
3. PostgreSQL NOTIFY fires on outbox INSERT → Celery worker wakes immediately
   Celery beat polls every 30 seconds as fallback (missed NOTIFY recovery)
4. Celery worker reads PENDING outbox row:
   - Marks it PROCESSING (with SELECT FOR UPDATE SKIP LOCKED)
   - Executes side effect: send notification / trigger analytics ETL / update read model
   - Marks it PROCESSED
   - On failure: marks FAILED, increments attempts, Celery retries with backoff
```

### `write_to_outbox()` — call inside every state-changing transaction

```python
# backend/shared/outbox/writer.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def write_to_outbox(
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    payload: "BasePayload",
) -> None:
    """
    MUST be called inside the same DB transaction as the primary record.
    Writing to the outbox AFTER the transaction commits breaks atomicity.
    """
    await session.execute(
        text("INSERT INTO outbox (tenant_id, event_type, payload, payload_ver) "
             "VALUES (:tid, :etype, :payload::jsonb, :ver)"),
        {"tid": tenant_id, "etype": event_type,
         "payload": payload.model_dump_json(), "ver": payload.version}
    )
    # The NOTIFY trigger fires automatically on INSERT — no extra code needed here.
```

### Celery worker — idempotent handler

```python
# backend/shared/outbox/worker.py
from celery import Celery

app = Celery("smart", broker=settings.CELERY_BROKER_URL)

@app.task(bind=True, max_retries=5)
def process_outbox_row(self, row_id: str) -> None:
    """Always check status before processing — tasks must be idempotent."""
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text("SELECT * FROM outbox WHERE id=:id FOR UPDATE SKIP LOCKED"),
            {"id": row_id}
        )
        row = row.fetchone()
        if not row or row.status not in ("PENDING",):
            return  # already processed or locked by another worker

        await session.execute(
            text("UPDATE outbox SET status='PROCESSING' WHERE id=:id"), {"id": row_id})
        await session.commit()

    try:
        handler = OUTBOX_HANDLERS.get(row.event_type)
        if handler:
            await handler(row.payload, row.tenant_id)
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE outbox SET status='PROCESSED',processed_at=now() WHERE id=:id"),
                {"id": row_id})
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE outbox SET status='FAILED',attempts=attempts+1,last_error=:e WHERE id=:id"),
                {"e": str(exc), "id": row_id})
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
```

### Supported event types

```python
# backend/shared/outbox/schemas.py
class InventoryUpdatedPayload(BasePayload):
    event_type: Literal["InventoryUpdated"] = "InventoryUpdated"
    product_id: str; warehouse_id: str; delta: float; transaction_id: str

class StockTransferredPayload(BasePayload):
    event_type: Literal["StockTransferred"] = "StockTransferred"
    from_warehouse_id: str; to_warehouse_id: str; product_id: str; quantity: float

class TenantOrgTypeChangedPayload(BasePayload):
    event_type: Literal["TenantOrgTypeChanged"] = "TenantOrgTypeChanged"
    from_type: str | None; to_type: str; changed_by: str

class FefoOverrideAppliedPayload(BasePayload):
    event_type: Literal["FefoOverrideApplied"] = "FefoOverrideApplied"
    override_log_id: str

# All event types: InventoryUpdated, StockTransferred, OrderCreated, ShipmentDispatched,
#                  AdjustmentApplied, StockCountCompleted, TenantOrgTypeChanged, FefoOverrideApplied
```

### Alerting thresholds

Set CloudWatch alarms when:
- Outbox PENDING row count > 500 (worker lag)
- Any row has `attempts >= 4` (approaching max retries)
- Any row has been PENDING for > 5 minutes

---

## 9. Backend — Python / FastAPI Architecture

### Service directory structure

```
backend/services/<service>/
├── main.py                     # FastAPI app factory, lifespan, middleware
├── routers/<resource>.py       # One router file per resource
├── services/<resource>_service.py    # Business logic only
├── repositories/<resource>_repo.py   # SQLAlchemy queries only
├── schemas/<resource>.py       # Pydantic v2 request/response models
├── tests/
│   ├── conftest.py             # fixtures: test DB, mock user contexts
│   ├── test_<resource>_routes.py
│   └── test_permissions.py    # All 15 cases per action (required)
├── Dockerfile
└── pyproject.toml
```

### Every protected route requires `@require_permission`

```python
# backend/services/inventory-service/routers/receive.py
from fastapi import APIRouter, Depends
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS

router = APIRouter()

@router.post("/", status_code=201)
@require_permission(PERMISSIONS.INVENTORY_RECEIVE)
async def receive_stock(
    body: ReceiveStockRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession  = Depends(get_db_session),
) -> SuccessResponse[ReceiveStockResponse]:
    result = await inventory_service.receive(db, user, body)
    return SuccessResponse(data=result)

# Routes without @require_permission fail the CI drift check — PRs blocked.
```

### Dependency injection — JWT + DB + RLS

```python
# backend/shared/db/dependencies.py
async def get_db_session(user: UserContext = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        await set_rls_context(session, user.tenant_id, user.user_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Standard response envelope

```python
class SuccessResponse[T](BaseModel):
    success: bool = True
    data: T
    request_id: str
    timestamp: str

class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail   # code: RBAC_DENIED | ABAC_DENIED | INVALID_STATE | etc.
    request_id: str
    timestamp: str
```

---

## 10. Frontend — TypeScript + Tailwind + PWA

### TypeScript — strict mode mandatory

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noUncheckedIndexedAccess": true
  }
}
```

### Tailwind — always use `cva` for component variants, never inline styles

```typescript
// frontend/src/components/ui/Button.tsx
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:opacity-50',
  {
    variants: {
      variant: {
        default:     'bg-blue-600 text-white hover:bg-blue-700',
        destructive: 'bg-red-500 text-white hover:bg-red-600',
        outline:     'border border-gray-300 bg-white hover:bg-gray-50',
        ghost:       'hover:bg-gray-100 text-gray-700',
      },
      size: { sm: 'h-8 px-3 text-xs', md: 'h-10 px-4', lg: 'h-12 px-6 text-base' },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  }
);
```

### PWA — service worker and offline queue

```typescript
// frontend/public/sw.js
// Responsibilities:
// 1. Cache app shell (HTML, CSS, JS bundles) for offline access
// 2. Cache language pack JSON files from S3
// 3. Queue failed POST/PATCH requests in IndexedDB for later sync

const CACHE = 'smart-v4';
const SHELL  = ['/', '/inventory', '/products', '/reports'];
const LOCALES= ['/api/locales/en', '/api/locales/am', '/api/locales/or'];

self.addEventListener('install', e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([...SHELL, ...LOCALES])))
);
```

```typescript
// frontend/src/store/offlineQueue.ts
import { openDB } from 'idb';

export async function enqueueOfflineTransaction(tx: OfflineTransaction) {
  const db = await openDB('smart-offline', 1, {
    upgrade(db) { db.createObjectStore('queue', { keyPath: 'idempotencyKey' }); }
  });
  await db.put('queue', { ...tx, status: 'PENDING', createdAt: new Date().toISOString() });
}
```

### Form factors and OS targets

| Form factor | OS / Browser | Primary users |
|---|---|---|
| Mobile phone | Android 10+ Chrome, iOS 15+ Safari | Warehouse staff, field agents |
| Tablet | Android 10+ Chrome, iPadOS 15+ Safari | Warehouse Managers (scan + dashboard) |
| Desktop | Windows 10/11, macOS, Linux (Chrome, Firefox, Edge, Safari) | NM, RM, TA, Finance, Auditor |

Single PWA serves all three. Tailwind breakpoints: `sm:` = mobile, `md:` = tablet, `lg:` = desktop.

### Permission hook — display only, never a security gate

```typescript
// WARNING: controls UI visibility only. Backend enforces all permissions independently.
export function usePermission(actionId: string): boolean {
  const { user } = useAuth();
  if (!user) return false;
  return (ROLE_PERMISSIONS[user.role] ?? []).includes(actionId);
}
```

---

## 11. Barcode Scanning

```typescript
// frontend/src/lib/scanner.ts
import { BrowserMultiFormatReader, NotFoundException } from '@zxing/browser';

export class BarcodeScanner {
  private reader = new BrowserMultiFormatReader();
  private stream: MediaStream | null = null;

  async start(videoEl: HTMLVideoElement, onResult: (code: string) => void): Promise<void> {
    // HTTPS is required — iOS Safari blocks camera access on HTTP
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }  // rear camera
    });
    await this.reader.decodeFromStream(this.stream, videoEl, (result, error) => {
      if (result) onResult(result.getText());
      if (error && !(error instanceof NotFoundException)) console.error(error);
    });
  }

  stop(): void {
    this.stream?.getTracks().forEach(t => t.stop());
    this.reader.reset();
  }
}
// Supported: Code128, Code39, EAN-13, EAN-8, QR Code, DataMatrix
// Target: < 1 second P90 scan recognition on mid-range Android
// Phase 3 option: Flutter native app with MLKit for high-volume Retailer scanning hardware
```

---

## 12. Localization — English, Amharic, Oromifa

### Three supported languages from Phase 1

| Code | Language | Notes |
|---|---|---|
| `en` | English | Default — loaded when no preference is set |
| `am` | Amharic (አማርኛ) | Required from Phase 1 |
| `or` | Oromifa (Afaan Oromoo) | Added in v4.0 — required from Phase 1 |

### Language selection priority

1. User preference (`users.locale` column)
2. Tenant default (`tenants.default_locale` column)
3. System default: `en`

### i18n loader

```typescript
// frontend/src/lib/i18n.ts
type Locale = 'en' | 'am' | 'or';
let translations: Record<string, unknown> = {};

export async function loadLocale(locale: Locale): Promise<void> {
  // Language packs served from S3 via CDN, cached by service worker
  const res = await fetch(`/api/locales/${locale}`);
  translations = await res.json();
}

export function t(key: string): string {
  // Dot-notation: 'nav.inventory', 'alerts.low_stock'
  return key.split('.').reduce(
    (obj: unknown, k) => (obj as Record<string, unknown>)?.[k],
    translations
  ) as string ?? key;
}
```

### Language pack rules

- JSON files stored in S3: `s3://smart-attachments/locales/{en|am|or}.json`
- Loaded at app startup and cached by the service worker
- Adding a new language = upload a new JSON file to S3 + add enum value via Alembic migration
- No rebuild or redeployment required
- **Oromifa pack must be reviewed by a native Afaan Oromoo-speaking domain expert before Phase 1 go-live**

---

## 13. Permission System — RBAC + ABAC

### Registry — single source of truth

```python
# backend/shared/permissions/registry.py
# Every action MUST be here before it can be used in any route.
# Seeded into the DB by scripts/seed_permissions.py.

from dataclasses import dataclass, field
from typing import List

@dataclass(frozen=True)
class Permission:
    id:   str
    abac: List[str] = field(default_factory=list)

class PERMISSIONS:
    # Domain 1 — Tenant & System
    TENANT_CREATE          = Permission("tenant:create",          ["platform_only"])
    TENANT_CONFIGURE       = Permission("tenant:configure",       ["tenant_id"])
    TENANT_SET_ORG_TYPE    = Permission("tenant:set_org_type",    ["tenant_id","audit_required"])

    # Domain 4 — Inventory
    INVENTORY_RECEIVE      = Permission("inventory:receive",      ["tenant_id","warehouse_id"])
    INVENTORY_ADJUST       = Permission("inventory:adjust",       ["tenant_id","warehouse_id","approval_threshold"])
    INVENTORY_TRANSFER     = Permission("inventory:transfer",     ["tenant_id","scope"])
    INVENTORY_CYCLE_COUNT  = Permission("inventory:cycle_count",  ["tenant_id","warehouse_id"])
    # IMTS: new inventory permissions
    INVENTORY_VIEW_DISTRIBUTION = Permission("inventory:view_distribution", ["tenant_id","facility_id"])
    INVENTORY_VIEW_SOURCES      = Permission("inventory:view_suggested_sources", ["tenant_id","warehouse_id"])

    # Domain 7 — AI
    AI_FORECAST_VIEW       = Permission("ai:forecast_view",       ["tenant_id"])
    AI_MODEL_RUN           = Permission("ai:model_run",           ["system_only"])  # SYS ONLY

    # Domain 9 — Dispatch (v3.0+)
    DISPATCH_CONFIGURE     = Permission("dispatch:configure",     ["tenant_id"])
    DISPATCH_FEFO_OVERRIDE = Permission("dispatch:fefo_override", ["tenant_id","override_permission","reason_required"])

    # ... all 115 entries
```

### Three-layer enforcement — all three layers are mandatory

```
Layer 1 — API Gateway:  JWT valid? Coarse role check. Rejects unauthenticated requests.
Layer 2 — Service Layer: RBAC check → ABAC attribute check → Conditional routing. Writes audit log.
Layer 3 — PostgreSQL RLS: tenant_id == session context. Cannot be bypassed by app code.

UI-level hiding is NOT a security layer. Never rely on it alone.
```

### `check_permission()` implementation

```python
# backend/shared/permissions/middleware.py
async def check_permission(
    user: UserContext,
    action: Permission,
    resource: dict | None = None,
    db: AsyncSession | None = None,
    scope_cache: dict[str, set[str]] | None = None,
) -> PermissionResult:
    # 1. RBAC check
    grant = await permission_store.get_role_permission(user.role, action.id)
    if not grant:
        await audit_log(user, action.id, resource, "DENIED", "RBAC_DENIED")
        return PermissionResult(allowed=False, reason="RBAC_DENIED")

    # 2. Tenant isolation — always checked
    if resource.get("tenant_id") and resource["tenant_id"] != user.tenant_id:
        await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: tenant mismatch")
        return PermissionResult(allowed=False, reason="ABAC_DENIED: tenant mismatch")

    # 3. Region scope
    if "region_id" in action.abac and user.region_id:
        if resource.get("region_id") and resource["region_id"] != user.region_id:
            await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: region scope")
            return PermissionResult(allowed=False, reason="ABAC_DENIED: region scope")

    # 4. Warehouse scope — node + descendant traversal
    FACILITY_SCOPED_ROLES = {"WM", "LM", "SA_GT", "RT"}
    if user.role in FACILITY_SCOPED_ROLES and user.warehouse_id:
        resource_wh = resource.get("warehouse_id")
        if resource_wh and "warehouse_id" in action.abac:
            # Descendant set cached per-request in scope_cache
            # Falls back to exact-match if db is None
            if resource_wh_str not in scope_cache[user_wh_str]:
                return PermissionResult(
                    allowed=False,
                    reason="ABAC_DENIED: warehouse scope"
                )

    # 5. Conditional — route to approval workflow
    if grant.grant_type == "CONDITIONAL":
        await audit_log(user, action.id, resource, "CONDITIONAL", "APPROVAL_REQUIRED")
        return PermissionResult(allowed=True, condition="APPROVAL_REQUIRED")

    await audit_log(user, action.id, resource, "GRANTED")
    return PermissionResult(allowed=True)
```

### Role hierarchy (highest → lowest privilege)

```
SA (10) > TA (9) > NM (8) > RM (7) > WM (6) = LM (6) > SA_GT (4) > RT (3) > AU (2) > SYS (1)
```

Users may not assign roles at or above their own level.

### Role scope — facility-scoped vs tenant-wide

`FACILITY_SCOPED_ROLES` in `backend/shared/permissions/middleware.py` determines which
roles are restricted to their own assigned node for `warehouse_id`-scoped actions:

```
FACILITY_SCOPED_ROLES = {"WM", "LM", "SA_GT", "RT"}
```

```
WM:    node-scoped. Scope = the position's assigned node (exact match only).
LM:    node-scoped. Scope = the position's assigned node (exact match only).
       A tenant-wide LM account (system_role="LM", created without a position)
       has warehouse_id=None in its JWT and is NOT subject to this check at all
       — it keeps unrestricted tenant-wide read access. Node-scoping only
       applies once an LM is assigned a position at a specific node.
SA_GT, RT: node-scoped. Scope = the position's assigned node (exact match only).
TA, NM, RM, AU, SA: NOT facility-scoped — operate across all warehouses within
       their tenant. Their warehouse_id JWT claim (if present) is a home
       facility, not a cage.
```

> **Known gap — exact node match only, no descendant traversal.** Despite the
> "enterprise WMS" expectation that an LM/WM at a higher hierarchy level (e.g. L1)
> should see all descendant nodes beneath it, the live ABAC check in
> `check_permission()` is a flat string comparison (`user.warehouse_id ==
> resource.warehouse_id`) — it does **not** walk `org_node_hierarchy` to resolve
> a node's descendant subtree. A `get_authority_scope()`-style function that does
> this exists only in archived dead code
> (`backend/services/tenant-service/routers/_ARCHIVED_personnel_pre031.py`) and
> was never revived. `check_permission()` has no `db` parameter, so implementing
> true descendant-scoping would require threading a db session through every
> `@require_permission`-decorated route in every service — tracked as a follow-up,
> not yet implemented. This applies equally to WM, LM, SA_GT, and RT today.

### JWT payload — required fields

```python
class JWTPayload(BaseModel):
    sub:          str            # user UUID
    role:         str            # role_code
    tenant_id:    str
    region_id:    str | None
    warehouse_id: str | None     # maps to organization_node.id (facility_id) regardless of hierarchy level
                                 # IMTS: authority over child nodes resolved via get_authority_scope()
                                 # against org_node_hierarchy — never assumed from role alone
    iat:          int
    exp:          int            # max JWT_EXPIRE_MINUTES (60 min)
```

---

## 14. Inventory Ledger — Immutable Rules

### warehouse_stock is a computed read model — never write to it directly

```
warehouse_stock holds pre-computed balance columns (on_hand, reserved, in_transit_in,
in_transit_out) for fast dashboard queries. It is NOT a source of truth.

The ONLY permitted writer:   update_running_balance() in ledger_repo.py
The ONLY permitted caller:   record_transaction() in ledger_repo.py
Both run in the SAME database transaction as the inventory_transactions INSERT.

Every other code path that touches warehouse_stock is READ ONLY (SELECT).

The database enforces this via a PostgreSQL RULE on warehouse_stock that rejects
any UPDATE issued outside the privileged ledger session role. This is defence in depth
on top of the application-level rule above.

IMTS §13.2 describes warehouse_stock as an inventory table. That description is accurate —
it is a table. What IMTS does not make explicit is that it is a derived/read table, not
a directly-writable one. PRD v4 §11.4 PR-NEW-9 is the authoritative rule: no direct
balance updates. This section operationalises that rule.
```

```python
# backend/services/inventory-service/repositories/ledger_repo.py
async def record_transaction(db: AsyncSession, tx: NewTransaction) -> InventoryTransaction:
    # 1. Idempotency — reject duplicate with 409
    await check_and_register_idempotency_key(db, tx.idempotency_key)

    # 2. Concurrency lock — prevent race conditions
    await db.execute(
        text("SELECT id FROM inventory_balances "
             "WHERE tenant_id=:tid AND product_id=:pid AND warehouse_id=:wid FOR UPDATE"),
        {"tid": tx.tenant_id, "pid": tx.product_id, "wid": tx.warehouse_id}
    )

    # 3. Stock floor — cannot go below zero without override
    if tx.quantity < 0:
        await validate_stock_available(db, tx.tenant_id, tx.product_id,
                                       tx.warehouse_id, abs(tx.quantity))

    # 4. INSERT ledger record (never UPDATE)
    new_tx = InventoryTransaction(**tx.model_dump())
    db.add(new_tx)
    await update_running_balance(db, tx)

    # 5. Write to outbox IN THE SAME TRANSACTION
    await write_to_outbox(db, tx.tenant_id, "InventoryUpdated",
        InventoryUpdatedPayload(product_id=str(tx.product_id),
                                warehouse_id=str(tx.warehouse_id),
                                delta=float(tx.quantity),
                                transaction_id=str(new_tx.id)))
    return new_tx

# WRONG — this bypasses the ledger entirely
async def set_balance(db, product_id, qty):
    await db.execute(text("UPDATE inventory_balances SET quantity=:q WHERE ..."), ...)
    # ← FORBIDDEN. Will fail CI review.
```

### IMTS: Authority scope resolution

```python
# backend/services/inventory-service/services/hierarchy_service.py
async def get_authority_scope(db: AsyncSession, tenant_id: str,
                              facility_id: str) -> list[str]:
    """
    Returns all organization_node IDs that the given facility has PRIMARY_REPORTS_TO
    authority over. Used by ABAC checks to determine if a user at facility_id
    can act on resources belonging to child facilities.
    Never infer authority from role alone — always call this function.
    """
    rows = await db.execute(
        text("""
            WITH RECURSIVE authority_tree AS (
                SELECT from_node_id AS node_id
                FROM org_node_hierarchy
                WHERE tenant_id = :tid
                  AND to_node_id = :fid
                  AND relationship_type = 'PRIMARY_REPORTS_TO'
                UNION ALL
                SELECT h.from_node_id
                FROM org_node_hierarchy h
                INNER JOIN authority_tree a ON h.to_node_id = a.node_id
                WHERE h.tenant_id = :tid
                  AND h.relationship_type = 'PRIMARY_REPORTS_TO'
            )
            SELECT node_id FROM authority_tree
        """),
        {"tid": tenant_id, "fid": facility_id}
    )
    return [str(r[0]) for r in rows.fetchall()]

async def get_suggested_sources(db: AsyncSession, tenant_id: str,
                                facility_id: str, product_id: str) -> list[dict]:
    """
    IMTS §10.1 source suggestion algorithm.
    Retrieves all SUPPLY_FROM sources for the facility, checks available stock,
    and ranks by: preferred source first, then stock availability, then proximity.
    Used by GET /api/v1/{tenant}/warehouses/{wh_id}/suggested-sources
    All queries run on DATABASE_READ_URL (read replica).
    """
    sources = await db.execute(
        text("""
            SELECT h.to_node_id AS source_id,
                   h.is_preferred,
                   ws.available,
                   n.name AS source_name
            FROM org_node_hierarchy h
            JOIN organization_node n ON n.id = h.to_node_id
            LEFT JOIN warehouse_stock ws ON ws.facility_id = h.to_node_id
                                        AND ws.product_id = :pid
                                        AND ws.tenant_id = :tid
            WHERE h.tenant_id = :tid
              AND h.from_node_id = :fid
              AND h.relationship_type = 'SUPPLY_FROM'
            ORDER BY h.is_preferred DESC, ws.available DESC NULLS LAST
        """),
        {"tid": tenant_id, "fid": facility_id, "pid": product_id}
    )
    return [dict(r) for r in sources.fetchall()]
```

### IMTS: New API endpoints

```
# Dashboard Service — IMTS distribution view (NM/LM role, read replica)
GET  /api/v1/{tenant}/facilities/{facility_id}/distribution-view
     @require_permission(PERMISSIONS.INVENTORY_VIEW_DISTRIBUTION)
     Returns: hierarchical stock tree from facility_id down, with threshold color status

# Multi-source suggestion (WM/RM role, read replica)
GET  /api/v1/{tenant}/warehouses/{wh_id}/suggested-sources?product_id={pid}
     @require_permission(PERMISSIONS.INVENTORY_VIEW_SOURCES)
     Returns: ranked list of SUPPLY_FROM sources with available stock

# IMTS: Transfer endpoints extended with type parameter
POST /api/v1/{tenant}/transfers/pull     # Pull request — uses PULL_TRANSITIONS
POST /api/v1/{tenant}/transfers/push     # Push issue — uses PUSH_TRANSITIONS
POST /api/v1/{tenant}/transfers/sister   # Sister transfer — uses SISTER_TRANSITIONS
# All existing PUT /{id}/submit|review|approve|dispatch|receive remain valid
# validate_transition() now requires transaction_type alongside current/next_state
```

---

## 15. Tenant Profile & Onboarding Wizard

```python
# backend/services/tenant-service/services/wizard_service.py

FEATURE_FLAG_DEFAULTS = {
    "PRODUCER": {"LOGISTICS":False,"AI_ANALYTICS":False,"ADVANCED_BATCH_TRACKING":True,"FLEET_MANAGEMENT":False},
    "RETAILER": {"LOGISTICS":True, "AI_ANALYTICS":True, "ADVANCED_BATCH_TRACKING":False,"FLEET_MANAGEMENT":True},
    "HYBRID":   {"LOGISTICS":True, "AI_ANALYTICS":True, "ADVANCED_BATCH_TRACKING":True, "FLEET_MANAGEMENT":True},
}
APPROVAL_DEFAULTS = {
    "PRODUCER": {"inventory:adjust": {"low":100, "medium":500}},
    "RETAILER": {"inventory:adjust": {"low":500, "medium":5000}},
    "HYBRID":   {"inventory:adjust": {"low":250, "medium":2000}},
}

async def complete_wizard(db: AsyncSession, tenant_id: str, data: WizardData) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    tenant.organisation_type   = data.org_type
    tenant.feature_flags       = FEATURE_FLAG_DEFAULTS[data.org_type]
    tenant.approval_thresholds = APPROVAL_DEFAULTS[data.org_type]
    tenant.default_locale      = data.default_locale   # 'en' | 'am' | 'or'
    tenant.onboarding_complete = True
    if data.org_type == "PRODUCER":
        plan = await get_plan(db, tenant.plan_id)
        tenant.sku_cap = plan.sku_limit

    # Outbox in SAME transaction
    await write_to_outbox(db, tenant_id, "TenantOrgTypeChanged",
        TenantOrgTypeChangedPayload(from_type=None, to_type=data.org_type, changed_by="WIZARD"))
    return tenant
```

---

## 16. Dispatch Strategy Engine

```python
# backend/services/inventory-service/services/dispatch_service.py
async def resolve_strategy(db, tenant_id, product_id, category_id,
                           batch_tracking: bool, expiry_tracking: bool) -> str:
    # Auto-FEFO when both batch tracking AND expiry date are active
    if batch_tracking and expiry_tracking:
        return "FEFO"
    cfg = await get_dispatch_config(db, tenant_id, "PRODUCT", product_id)
    if cfg: return cfg.strategy
    cfg = await get_dispatch_config(db, tenant_id, "CATEGORY", category_id)
    if cfg: return cfg.strategy
    return "FIFO"   # system default

async def select_lots(db, tenant_id, product_id, warehouse_id,
                      required_qty: Decimal, strategy: str) -> list:
    lots = await get_available_lots(db, tenant_id, product_id, warehouse_id)
    if   strategy == "FEFO": lots.sort(key=lambda l: l.expiry_date)
    elif strategy == "FIFO": lots.sort(key=lambda l: l.received_at)
    else:                    lots.sort(key=lambda l: l.received_at, reverse=True)

    selections, remaining = [], required_qty
    for lot in lots:
        if remaining <= 0: break
        take = min(lot.available_quantity, remaining)
        selections.append(LotSelection(lot_id=lot.id, lot_number=lot.lot_number,
                                       quantity=take, strategy_applied=strategy))
        remaining -= take
    if remaining > 0:
        raise InsufficientStockError(product_id, required_qty, required_qty - remaining)
    return selections
```

---

## 17. Workflow State Machines

```python
# backend/services/inventory-service/services/state_machine.py
#
# IMTS enhancement: type-specific machines replace the single TRANSFER_TRANSITIONS dict.
# Each transaction type has genuinely different states — a single dict cannot enforce
# the PENDING_REVIEW step that PULL requires but PUSH does not, or the dual-confirm
# steps that SISTER requires and PULL does not.

PULL_TRANSITIONS = {
    # WH requests stock from RWH or MWH — has a review step before approval
    "DRAFT":              ["PENDING_REVIEW", "CANCELLED"],
    "PENDING_REVIEW":     ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
    "PENDING_APPROVAL":   ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":           ["ISSUED", "CANCELLED"],
    "ISSUED":             ["IN_TRANSIT"],
    "IN_TRANSIT":         ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED": ["RECEIVED"],
    "RECEIVED":           ["COMPLETED"],
    "COMPLETED": [], "REJECTED": [], "CANCELLED": [],
}

PUSH_TRANSITIONS = {
    # MWH or RWH proactively sends stock down — no review step; ADVISED precedes ISSUED
    "DRAFT":              ["PENDING_APPROVAL", "CANCELLED"],
    "PENDING_APPROVAL":   ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":           ["ADVISED", "ISSUED", "CANCELLED"],
    # ADVISED: destination notified, can flag overstock/space issues to pause dispatch
    "ADVISED":            ["ISSUED", "CANCELLED"],
    "ISSUED":             ["IN_TRANSIT"],
    "IN_TRANSIT":         ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED": ["RECEIVED"],
    "RECEIVED":           ["COMPLETED"],
    "COMPLETED": [], "REJECTED": [], "CANCELLED": [],
}

SISTER_TRANSITIONS = {
    # WH ↔ WH same level — both managers must explicitly agree before any approval above
    "DRAFT":                   ["PENDING_SOURCE_CONFIRM", "CANCELLED"],
    "PENDING_SOURCE_CONFIRM":  ["PENDING_DEST_CONFIRM", "CANCELLED"],
    "PENDING_DEST_CONFIRM":    ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
    "PENDING_APPROVAL":        ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":                ["ISSUED", "CANCELLED"],
    "ISSUED":                  ["IN_TRANSIT"],
    "IN_TRANSIT":              ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED":      ["RECEIVED"],
    "RECEIVED":                ["COMPLETED"],
    "COMPLETED": [], "REJECTED": [], "CANCELLED": [],
}

ADJUSTMENT_TRANSITIONS = {
    # DAMAGE and EXCESS adjustments — no transit states; ends at POSTED
    "DRAFT":            ["PENDING_APPROVAL", "CANCELLED"],
    "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
    "APPROVED":         ["POSTED"],
    "POSTED": [], "REJECTED": [], "CANCELLED": [],
}

# Machine registry — keyed by transaction type code
TRANSFER_MACHINES = {
    "PULL":   PULL_TRANSITIONS,
    "PUSH":   PUSH_TRANSITIONS,
    "SISTER": SISTER_TRANSITIONS,
}

def get_machine(transaction_type: str) -> dict:
    """Returns the correct state machine for the given transaction type."""
    if transaction_type in ("DAMAGE", "EXCESS", "COUNT"):
        return ADJUSTMENT_TRANSITIONS
    machine = TRANSFER_MACHINES.get(transaction_type)
    if not machine:
        raise ValueError(f"Unknown transaction type: {transaction_type}")
    return machine

def validate_transition(transaction_type: str, current: str, next_state: str) -> None:
    """Raises InvalidStateTransitionError → HTTP 422 for any invalid transition."""
    machine = get_machine(transaction_type)
    if next_state not in machine.get(current, []):
        raise InvalidStateTransitionError(current=current, attempted=next_state,
                                          transaction_type=transaction_type)
```

---

## 18. Offline Sync Strategy

```typescript
// Idempotency key — generated client-side before any network call
export function generateIdempotencyKey(userId: string, action: string, productId: string): string {
  return `${userId}:${action}:${productId}:${Date.now()}:${nanoid(8)}`;
}
```

```python
# Conflict resolution (server-side)
async def resolve_sync_item(db: AsyncSession, item: OfflineSyncQueueItem) -> SyncResult:
    # Rule 1: duplicate idempotency key → already processed
    if await idempotency_key_exists(db, item.idempotency_key):
        return SyncResult(status="SYNCED", message="Already processed")
    # Rule 2: quantity mismatch → mark CONFLICT for human review
    try:
        result = await process_transaction(db, item)
        return SyncResult(status="SYNCED", transaction_id=result.id)
    except QuantityMismatchError as e:
        await mark_conflict(db, item, conflict_data=e.detail)
        return SyncResult(status="CONFLICT", detail=e.detail)
    # Rule 3: concurrent update → last-write-wins, both values in audit log
```

---

## 19. API Conventions

```
URL structure:
  /api/v1/{resource}              GET list, POST create
  /api/v1/{resource}/{id}         GET, PATCH, DELETE
  /api/v1/{resource}/{id}/{sub}   nested resource

Authentication:
  All requests:     Authorization: Bearer <jwt>  (max 60 min)
  SYS integrations: X-API-Key: <key>

HTTP status codes:
  201  Created
  200  OK
  400  Validation error (malformed request body)
  401  Unauthenticated or expired JWT
  403  Permission denied — RBAC_DENIED or ABAC_DENIED
  404  Not found
  409  Idempotency key conflict — duplicate transaction
  422  Invalid state transition | Insufficient stock
  429  Plan limit exceeded (SKU cap, rate limit)

Standard envelope:
  { "success":true,  "data":{...},                          "request_id":"...", "timestamp":"..." }
  { "success":false, "error":{"code":"RBAC_DENIED","message":"..."}, "request_id":"...", "timestamp":"..." }
```

---

## 20. AI & Analytics Pipeline

```python
# Separate model cohorts — never train on mixed data
def get_model_cohort(org_type: str) -> str:
    return "PRODUCER" if org_type == "PRODUCER" else "RETAILER"
# PRODUCER cohort: production demand signals, lead times, batch cycle data
# RETAILER cohort: SKU-level sales velocity, reorder frequency, stockout patterns

# AI recommendations: always PENDING_APPROVAL, never auto-execute
class RecommendationStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"  # default — human must act before anything executes
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"

# ai:model_run (Action 91) is SYS role ONLY — user call returns HTTP 403
# Analytics ETL: triggered by Celery outbox worker consuming InventoryUpdated events
# All analytics queries use DATABASE_READ_URL (read replica) — never the primary

# Large Retailer catalogue batch forecasting
@celery_app.task
def generate_retailer_forecasts(tenant_id: str) -> None:
    """Runs off-peak. Pre-computes and caches to Redis before dashboard load."""
    if get_sku_count(tenant_id) <= 5000:
        return  # on-demand is acceptable for small catalogues
    forecasts = run_inference(tenant_id)
    cache_forecasts(tenant_id, forecasts, ttl_hours=24)
```

---

## 21. Testing Requirements

### 15 required permission test cases per action

```python
class TestInventoryReceivePermissions:
    async def test_01_rbac_happy_path(self):       ...  # WM + valid context → 201
    async def test_02_rbac_deny_wrong_role(self):  ...  # AU → 403 RBAC_DENIED
    async def test_03_abac_wrong_tenant(self):     ...  # Correct role, wrong tenant → 403
    async def test_04_abac_wrong_region(self):     ...  # Correct role, wrong region → 403
    async def test_05_abac_wrong_warehouse(self):  ...  # Correct role, wrong warehouse → 403
    async def test_06_abac_ownership(self):        ...  # Wrong owner_id → 403
    async def test_07_conditional_below(self):     ...  # WM below threshold → 200 auto-approved
    async def test_08_conditional_above(self):     ...  # WM above threshold → 202 pending RM
    async def test_09_auditor_read_only(self):     ...  # AU write attempt → 403
    async def test_10_read_only_grant(self):       ...  # R-grant write attempt → 403
    async def test_11_audit_log_allow(self):       ...  # Success → GRANTED in audit_logs
    async def test_12_audit_log_deny(self):        ...  # Failure → DENIED in audit_logs
    async def test_13_rls_cross_tenant(self):      ...  # Tenant A cannot read Tenant B → empty
    async def test_14_jwt_expired(self):           ...  # Expired token → 401
    async def test_15_sys_only_action(self):       ...  # User calls ai:model_run → 403
```

### Additional required test suites

```python
class TestOutboxPattern:
    async def test_outbox_written_in_same_transaction(self): ...
    async def test_worker_idempotent_on_already_processed(self): ...
    async def test_failed_row_retried_with_backoff(self): ...

class TestDispatch:
    async def test_fefo_nearest_expiry_selected(self): ...
    async def test_fefo_cascades_across_lots(self): ...
    async def test_fefo_auto_enforced_when_expiry_tracking_active(self): ...
    async def test_fefo_override_requires_permission_and_reason(self): ...
    async def test_override_written_to_dispatch_override_logs(self): ...

class TestLocalization:
    async def test_oromifa_pack_loads_without_error(self): ...
    async def test_user_locale_overrides_tenant_default(self): ...
    async def test_missing_key_returns_key_not_empty_string(self): ...

class TestApprovalWorkflows:
    """IMTS §6 approval matrices translated to test cases — one test per scenario row."""
    # Pull request routing
    async def test_pull_wh_to_rwh_sufficient_stock(self):       ...  # WM initiates → RM approves → APPROVED
    async def test_pull_wh_to_rwh_insufficient_escalates(self): ...  # RM escalates to LM; GM if > threshold
    async def test_pull_wh_to_mwh_direct_no_rwh(self):         ...  # WM → LM → GM if large qty
    # Push routing
    async def test_push_mwh_to_rwh_proactive(self):             ...  # LM initiates → NM approves → ADVISED to RWH
    async def test_push_mwh_to_wh_direct(self):                 ...  # LM initiates → NM approves → ADVISED to WH
    async def test_push_rwh_to_wh_regional(self):               ...  # RM initiates → LM advisory → ADVISED to WH
    async def test_push_recipient_flag_pauses_dispatch(self):   ...  # Destination flags → status returns to APPROVED
    # Sister transfer routing
    async def test_sister_same_region_both_agree(self):         ...  # WM(src) → WM(dst) agree → RM notified
    async def test_sister_cross_region_both_agree(self):        ...  # WM(src) → WM(dst) agree → both RMs + LM notified
    async def test_sister_rwh_cross_region(self):               ...  # RM(src) → RM(dst) agree → LM notified
    async def test_sister_rejected_by_destination(self):        ...  # Destination WM declines → REJECTED
    # Damage / write-off routing
    async def test_damage_within_wm_limit_auto_approved(self):  ...  # Auto-approved; audit log created
    async def test_damage_exceeds_wm_limit_routes_to_rm(self):  ...  # RM first approval required
    async def test_damage_exceeds_limit_final_ta(self):         ...  # TA (CEO) final approval
    async def test_mwh_damage_exceeds_limit_to_ta(self):        ...  # LM initiates → NM → TA if exceeds

class TestIMTSStateMachines:
    """Type-specific state machine enforcement — PULL, PUSH, SISTER, DAMAGE."""
    async def test_pull_cannot_skip_pending_review(self):       ...  # DRAFT → PENDING_APPROVAL raises 422
    async def test_push_has_no_pending_review_state(self):      ...  # PUSH DRAFT → PENDING_APPROVAL valid
    async def test_push_advised_state_reachable(self):          ...  # APPROVED → ADVISED valid for PUSH
    async def test_sister_requires_source_confirm_first(self):  ...  # DRAFT → PENDING_DEST_CONFIRM raises 422
    async def test_partial_receipt_intermediate_state(self):    ...  # IN_TRANSIT → PARTIALLY_RECEIVED valid
    async def test_adjustment_ends_at_posted_not_received(self):...  # APPROVED → POSTED; POSTED is terminal

class TestMultiSourceSplitRequest:
    """IMTS split request — each leg is an independent transaction with own idempotency key."""
    async def test_split_legs_have_unique_idempotency_keys(self): ...
    async def test_split_legs_share_parent_transfer_id(self):     ...
    async def test_parent_status_derived_from_legs(self):         ...  # parent not directly settable
    async def test_one_leg_received_other_in_transit(self):       ...  # PARTIALLY_RECEIVED state correct

class TestIMTSAlerts:
    """IMTS threshold alert types beyond basic low-stock."""
    async def test_24h_escalation_fires_if_no_action(self):      ...  # Celery beat task fires to RM + LM
    async def test_multiple_whs_below_min_aggregate_alert(self):  ...  # Regional aggregate fires to RM
    async def test_in_transit_overdue_alert_fires(self):          ...  # estimated_arrival_date past X days
```

---

## 22. CI/CD — GitHub Actions

> All CI jobs authenticate to AWS via **GitHub OIDC** — no `AWS_ACCESS_KEY_ID` stored in
> GitHub Secrets. Test jobs connect to the **dev AWS environment** (RDS + ElastiCache).
> There are no inline `postgres` or `redis` service containers.

### OIDC trust — required GitHub Actions setup

```yaml
# IAM role: arn:aws:iam::<account>:role/smart-github-actions-ci
# Trust policy allows: token.actions.githubusercontent.com
#   StringLike condition: repo:smart-org/smart-platform:*
# Permissions: SecretsManagerReadWrite (smart/dev/*), ECR push, ECS deploy (stage/prod scoped)
```

### `.github/workflows/ci.yml`

```yaml
name: CI
on:
  pull_request:
    branches: [develop, main]

permissions:
  id-token: write   # required for OIDC
  contents: read

jobs:
  lint-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install ruff mypy && ruff check backend/ && mypy backend/shared/ --strict

  lint-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd frontend && pnpm install --frozen-lockfile && pnpm tsc --noEmit && pnpm lint

  permission-drift-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e backend/shared && python scripts/ci_drift_check.py
        # Fails if: any route missing @require_permission
        #           any action used in a route not in registry.py

  test-backend:
    runs-on: ubuntu-latest
    # No service containers — tests run against dev AWS RDS + ElastiCache via OIDC
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/smart-github-actions-ci
          aws-region: us-east-1
      - name: Fetch dev secrets
        run: |
          echo "DATABASE_URL=$(aws secretsmanager get-secret-value \
            --secret-id smart/dev/db/primary-url --query SecretString --output text)" >> $GITHUB_ENV
          echo "DATABASE_READ_URL=$(aws secretsmanager get-secret-value \
            --secret-id smart/dev/db/read-replica-url --query SecretString --output text)" >> $GITHUB_ENV
          echo "REDIS_URL=$(aws secretsmanager get-secret-value \
            --secret-id smart/dev/elasticache/redis-url --query SecretString --output text)" >> $GITHUB_ENV
          echo "CELERY_BROKER_URL=$(aws secretsmanager get-secret-value \
            --secret-id smart/dev/elasticache/celery-broker --query SecretString --output text)" >> $GITHUB_ENV
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: |
          pip install -e backend/shared pytest pytest-asyncio httpx celery
          alembic upgrade head
          python scripts/seed_permissions.py
          python scripts/create_partitions.py --months 3
          pytest backend/ -v --tb=short --cov=backend

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd frontend && pnpm install --frozen-lockfile && pnpm test -- --coverage

  migration-round-trip:
    runs-on: ubuntu-latest
    # Runs against dev RDS — validates upgrade/downgrade cycle on real PostgreSQL 16
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/smart-github-actions-ci
          aws-region: us-east-1
      - name: Fetch dev DB URL
        run: |
          echo "DATABASE_URL=$(aws secretsmanager get-secret-value \
            --secret-id smart/dev/db/primary-url --query SecretString --output text)" >> $GITHUB_ENV
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: |
          alembic upgrade head
          alembic downgrade -1
          alembic upgrade head
          echo "Round-trip passed"

  locale-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          python -c "
          import json
          for l in ['en','am','or']:
              with open(f'locales/{l}.json') as f: data=json.load(f)
              print(f'{l}: {len(data)} top-level keys — OK')
          "

  openapi-types:
    runs-on: ubuntu-latest
    needs: [test-backend]
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/smart-github-actions-ci
          aws-region: us-east-1
      - run: npx openapi-typescript https://api.dev.smart-platform.com/openapi.json \
               -o frontend/src/types/api.ts
      - run: cd frontend && pnpm tsc --noEmit
```

### `.github/workflows/deploy-dev.yml`

```yaml
name: Deploy — Dev
on:
  push:
    branches: [develop]

permissions:
  id-token: write
  contents: read

jobs:
  deploy-dev:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/smart-github-actions-ci
          aws-region: us-east-1
      - name: Build and push image to ECR
        run: |
          aws ecr get-login-password | docker login --username AWS \
            --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
          docker build -t smart-backend .
          docker tag smart-backend:latest \
            <account>.dkr.ecr.us-east-1.amazonaws.com/smart-backend:dev-${{ github.sha }}
          docker push <account>.dkr.ecr.us-east-1.amazonaws.com/smart-backend:dev-${{ github.sha }}
      - name: Run Alembic migrations on dev
        run: |
          aws ecs run-task --cluster smart-dev \
            --task-definition smart-dev-migration \
            --overrides '{"containerOverrides":[{"name":"migration",
              "command":["alembic","upgrade","head"]}]}' \
            --launch-type FARGATE --wait
      - name: Update ECS services on dev
        run: |
          for svc in api-gateway tenant inventory order logistics analytics notification sync; do
            aws ecs update-service --cluster smart-dev \
              --service smart-dev-$svc \
              --force-new-deployment
          done
```

### `.github/workflows/deploy-staging.yml`

```yaml
name: Deploy — Stage
on:
  push:
    branches: [main]

permissions:
  id-token: write
  contents: read

jobs:
  deploy-stage:
    runs-on: ubuntu-latest
    environment: stage          # GitHub environment — requires reviewer approval
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/smart-github-actions-deploy-stage
          aws-region: us-east-1
      - name: Build, push, migrate, deploy (stage)
        run: |
          # Same pattern as deploy-dev — targets smart-stage cluster
          # Smoke tests run automatically after deploy via ECS health checks
```

### `.github/workflows/deploy-prod.yml`

```yaml
name: Deploy — Prod
on:
  push:
    tags: ['v*']               # Release tag triggers prod deploy

permissions:
  id-token: write
  contents: read

jobs:
  deploy-prod:
    runs-on: ubuntu-latest
    environment: prod           # GitHub environment — requires named approver sign-off
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<account>:role/smart-github-actions-deploy-prod
          aws-region: us-east-1
      - name: Build, push, migrate, deploy (prod)
        run: |
          # Same pattern — targets smart-prod cluster
          # Terraform plan is run first; apply only if plan shows no destructive changes
```

### Deploy pipeline summary

```
PR opened          → CI runs (lint, test, drift-check, migration round-trip)
Merge to develop   → Auto-deploy to dev environment
Merge to main      → Deploy to stage (GitHub environment approval gate)
Release tag vX.Y.Z → Deploy to prod (named approver required in GitHub environment)

All deployments:   Terraform plan → ECR push → Alembic migrate → ECS rolling update
All auth:          GitHub OIDC → scoped IAM role per environment
All secrets:       AWS Secrets Manager — never in GitHub Secrets or workflow files
```

---

## 23. Performance Targets

These are pass/fail acceptance criteria, not aspirational goals.

| ID | Target | Test method |
|---|---|---|
| NFR-1 | Dashboard load < 2s P95 | Lighthouse CI |
| NFR-2 | API response < 500ms P95 | Locust load test |
| NFR-3 | Transaction processing < 300ms | pytest timing |
| NFR-4 | Uptime 99.9% monthly | CloudWatch alarm |
| NFR-SA-1 | SKU search < 200ms P95 @ 50k+ SKUs | Locust + 50k fixture |
| NFR-SA-2 | Ledger query < 500ms P95 @ 50M+ rows | pytest partition fixture |
| NFR-SA-3 | Dispatch lot selection < 300ms | pytest timing |
| NFR-SA-4 | Offline sync < 500ms P95 @ 200 devices | Locust concurrent |
| NFR-SA-5 | Onboarding wizard < 10 minutes | Playwright E2E |
| NFR-V4-1 | Outbox side effects < 5s P95 after transaction commit | Celery task timing |
| NFR-V4-2 | Outbox PENDING depth alert trigger | > 500 rows |
| NFR-V4-3 | Barcode scan recognition < 1s P90 (mid-range Android) | Manual device test |
| NFR-V4-4 | Language pack load < 200ms additional | Lighthouse |
| NFR-V4-5 | en/am/or character sets render on all targets without extra fonts | Manual cross-device test |

---

## 24. Business Rules — Enforced by Code

PRs that violate these rules do not merge.

```
1.  Stock balance never goes below zero without override permission + audit log entry.
2.  Every stock mutation is an INSERT into inventory_transactions — never a direct balance UPDATE.
3.  Every ledger transaction has a unique idempotency key.
4.  FEFO is automatically enforced when batch_tracking=True AND expiry_date is populated on the product.
5.  FEFO override requires: dispatch:fefo_override permission + reason_code + DispatchOverrideLog INSERT.
6.  Outbox row is written in the SAME database transaction as the primary ledger record.
7.  Celery task handlers check whether the outbox row is PROCESSING or PROCESSED before doing any work.
8.  AI recommendations always start with status=PENDING_APPROVAL and never auto-execute.
9.  ai:model_run (Action 91) is SYS role only — any user role call returns HTTP 403.
10. State machine raises InvalidStateTransitionError (HTTP 422) on any invalid transition.
11. Users cannot assign roles at or above their own level in the hierarchy.
12. Cross-tenant data access is blocked by PostgreSQL RLS for all roles except SA in support context.
13. audit_logs table has CREATE RULE preventing UPDATE or DELETE — these rules must never be removed.
14. Permission enforcement runs at all three layers: gateway + service + PostgreSQL RLS.
15. organisation_type changes are audit-logged with before-value, after-value, user, and timestamp.
16. SKU plan caps are enforced at the API gateway — never inside service business logic.
17. Analytics queries use DATABASE_READ_URL (read replica) — never the primary DATABASE_URL.
18. parent_tenant_id column exists on the tenants table — never drop this column.
19. Every new route has @require_permission — enforced by scripts/ci_drift_check.py in CI.
20. All UI strings use i18n keys — no hardcoded English text in JSX or HTML templates.
21. The site is served over HTTPS — required for iOS camera access for barcode scanning.
22. Apache Kafka, RabbitMQ, and aiokafka are not used anywhere in this codebase.
23. No external ERP system integration is implemented or referenced in code.
24. Split-request legs (parent_transfer_id IS NOT NULL) each carry their own idempotency key
    and run their own type-specific state machine. The parent record status is read-only —
    it is derived from the aggregate state of all legs and never set directly by application code.
25. A user's warehouse_id JWT claim maps to organization_node.id regardless of hierarchy level.
    For roles in FACILITY_SCOPED_ROLES (WM, LM, SA_GT, RT), warehouse-scope ABAC checks grant
    access to the assigned node AND all active descendant nodes, resolved via recursive CTE on
    organization_node.parent_node_id. This traversal is implemented in
    backend/shared/permissions/hierarchy_service.py (get_descendant_node_ids()) and wired into
    check_permission() in middleware.py. Authority is never inferred from role alone and never
    assumed from org_node_hierarchy (that table is used for supply network topology, not scope
    resolution). LM Track B (no node assigned, warehouse_id=None in JWT) bypasses this check
    entirely and has tenant-wide visibility.
26. warehouse_stock is a computed read model. Application code never issues
    UPDATE warehouse_stock SET … directly. The only permitted writer is update_running_balance()
    inside ledger_repo.py, called within the same DB transaction as the ledger INSERT.
    The PostgreSQL RULE on warehouse_stock enforces this at the database level.
27. DIRPUSH does not exist as a named transaction type, endpoint, or permission registry entry.
    Direct push from a higher facility to a sub-facility bypassing intermediate levels is
    modelled as a standard PUSH transaction whose SUPPLY_FROM relationship in org_node_hierarchy
    spans non-adjacent hierarchy levels. No separate code path exists or is permitted.
```

### IMTS role mapping — canonical codes used in all code and permission checks

The IMTS design document uses different role labels from the canonical role codes in the permission registry. Developers must use canonical codes in all code; IMTS labels appear only in external documentation.

| IMTS label | Canonical code | Privilege level | Notes |
|---|---|---|---|
| Warehouse Manager (WH-M) | `WM` | 6 | Direct match |
| Regional Manager (RM) | `RM` | 7 | Direct match |
| Logistics Manager (LM) | `LM` | 6 | Direct match — same level as WM |
| General Manager (GM) | `NM` | 8 | NM (National Manager) is the correct code |
| CEO / Director | `TA` | 9 | Tenant Admin is the highest tenant-scoped role; CEO-level write-off approvals use TA |
| System Admin | `SA` or `TA` | 10 / 9 | Platform config = `SA`; tenant config = `TA` |

IMTS roles not present in IMTS but required by PRD v4: Sales Agent (`SA_GT`), Retailer (`RT`), Auditor (`AU`), SYS — these are absent from IMTS approval matrices because IMTS covers the transfer workflow domain only. Their absence in IMTS is correct and intentional.

---

## 25. Phase 0 — Must Exist Before Any User Is Onboarded

These cannot be retrofitted after production data exists without significant downtime.

| Item | Why it cannot be deferred |
|---|---|
| `inventory_transactions` partitioned by `transaction_date` | Retrofitting partitioning on a large live table requires downtime and is very costly |
| `parent_tenant_id` column on tenants (nullable, unused) | Phase 4 franchise model needs this; adding it post-launch = live production migration |
| `outbox` table + NOTIFY trigger | Without the outbox table, async side effects cannot be processed |
| `dispatch_strategy_configs` table | FEFO cannot be enforced at transaction level without this table |
| PostgreSQL RLS on every tenant-scoped table | Added in same migration that creates each table — cannot add RLS to a table after it contains data without a rewrite |
| Tenant onboarding wizard | Without it: wrong feature flags, wrong approval thresholds, wrong role sets, no SKU caps |
| Three language packs (en.json, am.json, or.json) in S3 | Must exist before Phase 1 go-live. Oromifa pack requires native-speaker review |
| `warehouse_stock` table with `no_direct_stock_update` RULE | The computed read model and its write-protection rule must exist from Phase 0. Adding the RULE to a table with existing rows works but requires a brief lock; doing it after go-live is a production risk |
| Composite indexes with `tenant_id` leading | Tech lead reviews every new table's index strategy before it reaches production |
| `organization_node` + `org_node_hierarchy` tables | IMTS hierarchy is the foundation of all facility scoping, ABAC authority resolution, and multi-source supply logic — cannot be added after transfer data exists without a full migration |
| `tenant_hierarchy_config` table | Without it, the system assumes a fixed 3-tier structure; adding configurable levels post-launch requires rewriting all facility-scoped queries |
| `approval_rule` + `approval_history` tables | Approval routing and its audit trail must be configurable from the first transaction — hardcoded approval logic cannot be retrofitted |
| `stock_threshold` table with `preferred_source_id` and `secondary_source_id` | Multi-source suggestion algorithm requires preferred/secondary source references on the threshold record; adding columns after threshold data exists requires backfill |
| `parent_transfer_id` column on `inventory_transactions` | Split-request leg linking cannot be added post-launch without live ledger migration |
| `estimated_arrival_date` + `actual_arrival_date` on `inventory_transactions` | In Transit overdue alert logic requires these columns from the first ISSUED transaction |

---

## 26. Phase Roadmap

| Phase | Duration | Producer / Importer | Retailer / Distributor |
|---|---|---|---|
| **Phase 0 — Foundation** | Months 1–3 | Infrastructure only — no user onboarding. Multi-tenant core, RBAC+ABAC (115 actions), immutable ledger (partitioned), RLS, Transactional Outbox + Celery, onboarding wizard, dispatch config tables, PWA + service worker + IndexedDB, language packs (en/am/or), parent_tenant_id placeholder, GitHub Actions CI/CD, permission drift check. Terraform provisions all three AWS environments (dev/stage/prod). | Same foundation. Retailer profile: unlimited SKU flag, full role set, logistics module, Amazon OpenSearch (conditional) implemented. |
| **Phase 1 — Producer MVP** | Months 4–7 | Onboard first **4–6 Producer/Importer companies**. Receiving, transfer, issue, adjustment, stock count, batch/lot traceability, FEFO/FIFO dispatch engine, approval workflows (WM→RM→NM), state machines, low-stock + expiry alerts, role-scoped dashboards, offline (camera scanning, IndexedDB sync, conflict resolution), English + Amharic + Oromifa, full audit trail. | No Retailer tenants onboarded. Retailer features tested internally. |
| **Phase 2 — Retailer Onboarding** | Months 7–11 | Remaining Producer tenants settled. Supplier delivery analytics. Read replica routing validated. Additional language packs. | Onboard first **4–6 Retailer/Distributor companies**. Unlimited SKU + pg_trgm at scale, multi-branch dispatch, cycle count scheduling, SKU bulk import, Retailer dashboards, logistics module. Load test: 200-device concurrent offline sync. |
| **Phase 3 — AI & Scale** | Months 11–16 | Production Demand Forecast AI (PRODUCER cohort — needs 3–4 months history from Phase 1). Route optimisation. POS integration if grocery segment acceleration warranted. ElastiCache Streams evaluation if Celery fan-out shows limits. | Replenishment Recommendations AI (RETAILER cohort). Dead-stock detection. SKU-level forecast caching. POS integration. Flutter native app if scan reliability issues reported. |
| **Phase 4 — Expansion** | Month 16+ | Beyond founding 12 companies. Multi-currency valuation. Supplier EDI/ASN. Franchise umbrella model (parent_tenant_id activated). Advanced AI. | Buying-group umbrella model. Full EDI. Advanced BI. AI explainability. Amazon SQS evaluation for high-volume async if ElastiCache Streams shows limits. Additional language packs. |

---

## 27. UI/UX Rules

These rules were derived from bugs discovered during Session 5 manual testing (2026-05-23).
Each rule is backed by a regression test. PRs that violate these rules do not merge.

```
NEVER remove a product from the Inventory page because its On Hand balance is zero.
  A product that has ever had stock at a warehouse must remain visible with an
  "Out of Stock" badge (red) and be sorted to the bottom of the list.
  Filtering or hiding zero-balance products causes operators to lose track of
  stockouts and prevents replenishment. The filter condition is: show the product
  if (warehouseId in product.stock) OR getOnHand(...) > 0 OR any pending transfers
  or adjustments exist for this product at this warehouse.
  Regression test: test_zero_stock_product_remains_in_inventory

NEVER display a warehouse dropdown on the Receive Stock or Issue Stock forms.
  Both panels must auto-populate the warehouse from the authenticated user's JWT
  session (getSession().warehouseId) and display it as a read-only field.
  Allowing operators to select an arbitrary warehouse lets them record transactions
  against a facility they are not assigned to, bypassing warehouse-scope ABAC.
  The warehouse_id in the request body must always equal the user's JWT warehouseId.
  Regression tests: test_receive_stock_warehouse_from_jwt_not_input,
                    test_issue_stock_warehouse_from_jwt_not_input

NEVER put a direct Issue Stock transaction in the Reserved column.
  ISSUE is a direct On Hand deduction with no approval or reservation step.
  An ISSUE transaction writes a single ledger entry with transaction_type="ISSUE"
  and a negative quantity. It must never create a RESERVE transaction, a DRAFT
  transfer_orders row, or an adjustment_orders row. The Reserved column shows only
  outbound transfers in DRAFT/PENDING_x status. On Hand must decrease immediately
  when an ISSUE is posted; Reserved must not change.
  Regression tests: test_issue_stock_quantity_is_negative_deduction,
                    test_issue_stock_does_not_call_reserve_transaction

NEVER show the same action buttons to source and destination warehouse managers.
  At each transfer status, only the party responsible for the next action sees an
  active button. Source WM sees Dispatch at APPROVED; destination WM sees Receive
  at IN_TRANSIT. Showing both buttons to both parties causes confusion and allows
  the wrong party to advance a transfer they do not own.
  Use user.warehouse_id compared against transfer.from_warehouse_id (source actions)
  or transfer.to_warehouse_id (destination actions) to determine button visibility.
  The backend dispatch_transfer() and receive_transfer() enforce this as ABAC
  (HTTP 403 for the wrong warehouse) — the frontend must mirror this logic visually.
  Regression test: test_source_wm_sees_issue_button_at_approved

NEVER calculate the Products page stock total with a per-warehouse filter.
  The Products page shows the tenant-wide On Hand total for each product (sum across
  all warehouses the product is stocked in). It must not filter by the viewing user's
  warehouse_id. Filtering by warehouse means different users see different totals for
  the same product — a WH-A user sees 100 while a WH-B user sees 200 when the true
  tenant total is 300. Per-warehouse views belong on the Inventory page, not the
  Products page.
  Regression test: test_products_page_shows_same_total_all_wh_users

NEVER compare warehouse UUIDs without .toLowerCase() on both sides.
  JWT warehouseId claims and DB from_warehouse_id / to_warehouse_id values may
  differ in casing depending on how the JWT was issued vs how PostgreSQL serialises
  UUIDs. Strict equality (===) silently fails the comparison and hides action
  buttons (e.g. Issue, Dispatch, Receive) from the correct warehouse manager.
  Always normalise both operands: uWH === fromWH?.toLowerCase() where
  uWH = userWH?.toLowerCase(). This applies everywhere a facility-scoped identity
  check is performed in the frontend — getAvailableActions(), scopeTransfers(),
  ABAC attribute checks, and any new warehouse-scoped conditional.
  Root cause: BUG_REPORT.md §15 Bug 4 — isSrcWM UUID case mismatch.

NEVER leave a state machine missing transitions that the UI exposes as buttons.
  Every action button shown by getAvailableActions() must have a corresponding
  entry in the backend state machine (PULL_TRANSITIONS, PUSH_TRANSITIONS,
  SISTER_TRANSITIONS, ADJUSTMENT_TRANSITIONS). A button whose target status is
  absent from the machine always returns HTTP 422 INVALID_STATE_TRANSITION.
  This produces a spurious "Invalid transition" toast that masks unrelated errors
  and causes intermittent first-click failures when a concurrent session triggered
  the missing transition just before the current click.
  Specifically: REJECTED must be present in PENDING_REVIEW and PENDING_APPROVAL
  for all transfer types where the UI shows a Reject button (PULL, PUSH, SISTER).
  When adding new action buttons, update both getAvailableActions() in
  transfers/page.tsx AND the corresponding machine dict in state_machine.py
  in the same PR.
  Root cause: BUG_REPORT.md §15 Bug 3 — missing REJECTED in state machines.

NEVER render a raw i18n key as visible JSX text.
  Every string the user sees must be wrapped in t('key.name').
  If the key is missing from locales/en.json — add it first, then use t().
  After adding a key to en.json, run:
    python3 -c "..." to sync the same key to am.json and or.json.
  Prevention: bash scripts/check_i18n.sh must pass before git commit.

NEVER render a UUID directly in JSX text content.
  Warehouse/node IDs → resolve to name via API or ?? t('common.unknown')
  Tenant/org IDs → use useTenantName(org) hook
  User IDs → resolve to user.name before rendering
  Product IDs → resolve to product.name or SKU before rendering
  Fallback pattern: {value ?? t('common.unknown')} — never {value ?? rawId}

NEVER commit frontend changes without running both:
  npx tsc --noEmit          → must show 0 errors
  bash scripts/check_i18n.sh → must show PASS
```

---

## 28. Org Hierarchy Configuration

Full design: PRD-APPENDIX.md §B. This section states the rules that apply to all code in the hierarchy domain.

### Hierarchy Rules

```
Maximum 5 levels per tenant (Level 0–4 in tenant_hierarchy_config).
Level names, role mappings, and display labels are tenant-configurable
  — stored in tenant_hierarchy_config, not hardcoded.
Multiple root nodes are allowed (e.g. two separate factories under one tenant).
Every organization_node has is_stock_holding BOOLEAN.
  is_stock_holding=false nodes participate in the approval chain only —
  they hold no inventory, appear in no balance queries, and cannot be a
  PULL/PUSH source or destination.
Authority scope is always resolved via get_authority_scope() querying
  org_node_hierarchy — never inferred from role code alone (see §14, Rule 25).
```

### Product Scoping Rules

```
Standard products (source_factory_id IS NULL):
  Pullable from any node in the tenant that has available stock.
  No source restriction applies.

Factory-specific products (source_factory_id IS NOT NULL):
  Pullable only from nodes within the home factory's subtree.
  Backend validates source on every PULL creation.
  Invalid source raises HTTP 422 with code INVALID_SOURCE_FACTORY.
  Frontend filters source dropdown to nodes within the factory subtree.
  Product card displays badge: "Source: [Factory Name] only".

NEVER allow a factory-specific product to be pulled from outside its
  home factory subtree. This applies to all three transfer types
  (PULL, PUSH, SISTER) and to the dispatch engine's lot selection.
```

### Personnel Assignment Rules

```
Every user has exactly ONE PRIMARY facility assignment (permanent).
ACTING assignments are time-bounded (valid_from / valid_until).
  Any manager may create ACTING for any user within their authority scope.
  No higher-level approval is required.
DELEGATE assignments are time-bounded and permission-scoped.
  Scope is explicitly defined per assignment, not inherited from role.

JWT warehouse_id always equals the user's PRIMARY facility.
  ACTING/DELEGATE facilities do not appear in the JWT.
  ABAC permission checks union all currently-active assignments.
  Expired assignments (valid_until in the past) are ignored by all checks.

User deactivation sets is_active=false on the users table and closes
  all active ACTING/DELEGATE assignments.
NEVER hard-delete a user record. Deactivation is always reversible.
NEVER allow a manager to assign a role at or above their own level.
  This rule applies to PRIMARY, ACTING, and DELEGATE assignment types.
```

### NEVER Rules (addendum to §1)

```
NEVER delete a user record — set is_active=false. Reactivation restores
  the account. Deletion would break foreign key references in audit_logs,
  inventory_transactions, and approval_history.

NEVER allow a factory-specific product's PULL to source stock from outside
  its home factory subtree. The constraint must be enforced at the service
  layer on every transfer creation — it cannot be a frontend-only guard.

NEVER hardcode level names, role display labels, or level-to-role mappings
  in application code. All such labels must be read from
  tenant_hierarchy_config at runtime and included in API responses.
  Hardcoded labels produce incorrect UX for every tenant that uses
  non-default naming (e.g. "General Manager" vs "National Manager").
```

---

# SMART Inventory — Claude Prompts for Initial Stock Entry
## Option A: RECEIPT Workflow | Option C: Bulk Import (Structured Import)

---

## OPTION A — Opening Balance via RECEIPT Transaction

### Purpose
Use when a **single product** is being added to a warehouse for the first time and stock needs to be initialized through the ledger-compliant RECEIPT workflow.

**Who uses this:** Warehouse Manager, Tenant Admin
**When:** During product onboarding or go-live setup for individual SKUs

---

### System Prompt (Option A)

```
You are an inventory transaction assistant for the SMART Inventory Management System.
Your role is to guide a Warehouse Manager or Tenant Admin through recording an **Opening Balance Receipt** for a newly added product.

## Context
- All stock mutations must flow through the immutable inventory ledger.
- Opening stock is treated as a RECEIPT transaction with source type = "Opening Balance".
- This creates a ledger entry and updates On Hand at the target warehouse.
- The transaction follows the state machine: DRAFT → PENDING_REVIEW → PENDING_APPROVAL → APPROVED → POSTED.
- No Purchase Order is required; manual entry is allowed per PR-24.

## Your responsibilities
1. Collect all required fields from the user (listed below).
2. Validate inputs: quantities must be positive integers; dates must be valid; SKU must exist in the product catalog.
3. Confirm the transaction summary with the user before submission.
4. Generate the structured JSON payload for the API call to POST /api/v1/{tenant}/receipts/opening-balance.
5. Inform the user of the next step: the transaction will move to PENDING_APPROVAL and require a Warehouse Manager or National Manager to approve based on configured thresholds.

## Required Fields to Collect
- Warehouse / Facility (wh_id)
- Product name or SKU (product_id)
- Opening quantity (on_hand_quantity)
- Unit of measure (uom)
- Batch / Lot number (if batch tracking is enabled for this product)
- Manufacture date (if applicable)
- Expiry date (if applicable)
- Reason code: must always be "OPENING_BALANCE"
- Notes / remarks (free text, optional but recommended for audit)
- Reference document (e.g., physical count sheet, signed form — attachment optional)

## Validation Rules
- Quantity must be > 0.
- If batch tracking is enabled for the product (feature flag: batch_tracking = true), batch number and manufacture date are mandatory.
- If expiry rules are configured for the product, expiry date is mandatory.
- Duplicate opening balance receipts for the same product + warehouse combination must be flagged with a warning and require explicit user confirmation to proceed.
- SKU must exist in the tenant's product catalog before a receipt can be created.

## Output Format
After collecting and confirming all fields, output:
1. A plain-language transaction summary the user can review.
2. A JSON payload in this structure:

{
  "transaction_type": "RECEIPT",
  "source_type": "OPENING_BALANCE",
  "tenant_id": "<tenant_id>",
  "warehouse_id": "<wh_id>",
  "product_id": "<product_id>",
  "quantity": <integer>,
  "uom": "<unit>",
  "batch_number": "<batch or null>",
  "manufacture_date": "<YYYY-MM-DD or null>",
  "expiry_date": "<YYYY-MM-DD or null>",
  "reason_code": "OPENING_BALANCE",
  "notes": "<free text>",
  "reference_document": "<filename or null>",
  "idempotency_key": "<UUID — system generated>",
  "created_by": "<user_id>"
}

3. A clear next-step message: "This transaction is now in DRAFT. Submit it for approval to proceed."

## Tone and behavior
- Be concise and professional.
- Ask for one missing field at a time; do not overwhelm the user with all fields at once.
- If the user is unclear, ask a clarifying question before proceeding.
- Never modify the reason_code — it must always be OPENING_BALANCE for this workflow.
- Never skip the confirmation step before generating the payload.
```

---

## OPTION C — Bulk Import (Structured Opening Balance Import)

### Purpose
Use when **multiple products across one or more warehouses** need their opening stock set at system go-live or during a new product catalog rollout.

**Who uses this:** Tenant Admin, Super Admin
**When:** Initial tenant onboarding, warehouse commissioning, or batch product launches

---

### System Prompt (Option C)

```
You are a bulk stock import assistant for the SMART Inventory Management System.
Your role is to help a Tenant Admin or Super Admin prepare, validate, and submit a structured opening balance import for multiple products across one or more warehouses.

## Context
- This import creates RECEIPT ledger transactions of source_type = "OPENING_BALANCE" for each row.
- No direct balance updates are permitted — every row generates an immutable ledger entry.
- The import is a Tenant Admin function (Action 30: Bulk Import Products scope extends to opening stock import).
- A balance verification step is required before any product goes live in operational use.
- Import processes in batches; each row is assigned a unique idempotency_key to prevent duplicate processing on retry.
- All rows follow the RECEIPT state machine: rows are submitted in bulk → each enters PENDING_APPROVAL → approved by National Manager or Warehouse Manager per configured thresholds → POSTED to On Hand.

## Your responsibilities
1. Provide the user with the correct CSV/Excel import template structure.
2. Validate an uploaded or pasted dataset against all rules below.
3. Report validation errors clearly: row number, field name, error description.
4. Generate a pre-submission summary: total rows, total SKUs, total warehouses, flagged rows.
5. On user confirmation, generate the structured batch payload for the API call to POST /api/v1/{tenant}/imports/opening-balance.
6. After submission, explain the approval workflow the user should expect.

## Import Template Structure
The import file must be a CSV or Excel (.xlsx) with these exact column headers:

| Column Header        | Required | Description                                           |
|----------------------|----------|-------------------------------------------------------|
| warehouse_code       | Yes      | Unique code for the target warehouse (wh_id)          |
| sku_code             | Yes      | Product SKU — must exist in the product catalog       |
| opening_quantity     | Yes      | Integer > 0                                           |
| uom                  | Yes      | Unit of measure (must match product's configured UOM) |
| batch_number         | Cond.    | Required if batch tracking is enabled for the SKU     |
| manufacture_date     | Cond.    | Required if batch tracking is enabled (YYYY-MM-DD)    |
| expiry_date          | Cond.    | Required if expiry rules are set for the SKU          |
| notes                | No       | Free text remarks for audit trail                     |
| reference_document   | No       | Physical count sheet ID or document reference         |

## Validation Rules (apply to every row)
- opening_quantity must be a positive integer (> 0). Zero or negative values are rejected.
- sku_code must exist in the tenant's product catalog. Unknown SKUs are flagged as errors, not warnings.
- warehouse_code must be a valid, active warehouse for this tenant.
- uom must match the unit of measure configured on the product record.
- If batch_tracking = true for the SKU: batch_number and manufacture_date are mandatory.
- If expiry rules are configured for the SKU: expiry_date is mandatory.
- Duplicate rows (same sku_code + warehouse_code combination) within the same import are flagged as warnings; the user must explicitly confirm which row to keep.
- Existing opening balance entries for the same product + warehouse combination are flagged — re-import requires an override confirmation and reason.

## Validation Output Format
For each error or warning, report:

ROW [n] | FIELD: <field_name> | SEVERITY: ERROR / WARNING | MESSAGE: <description>

Example:
ROW 4  | FIELD: expiry_date      | SEVERITY: ERROR   | Expiry date is required for SKU "MED-004" (expiry rules enabled).
ROW 7  | FIELD: sku_code         | SEVERITY: ERROR   | SKU "RAW-999" not found in the product catalog.
ROW 12 | FIELD: warehouse_code   | SEVERITY: WARNING | Duplicate entry for SKU "CEM-001" at warehouse "WH-JIMMA". Confirm which row to keep.

## Pre-Submission Summary Format
Before generating the payload, output:

---
IMPORT SUMMARY — Opening Balance
---
Total rows:              [n]
Valid rows:              [n]
Error rows (blocked):    [n]
Warning rows (review):   [n]
Unique SKUs:             [n]
Unique warehouses:       [n]
---
⚠️  Rows with errors must be corrected before submission.
⚠️  Rows with warnings require your confirmation to proceed.
---

## Batch Payload Output
After user confirmation, generate:

{
  "import_type": "OPENING_BALANCE",
  "tenant_id": "<tenant_id>",
  "submitted_by": "<user_id>",
  "import_reference": "<import batch ID — system generated>",
  "rows": [
    {
      "warehouse_id": "<wh_id>",
      "product_id": "<product_id>",
      "quantity": <integer>,
      "uom": "<unit>",
      "batch_number": "<batch or null>",
      "manufacture_date": "<YYYY-MM-DD or null>",
      "expiry_date": "<YYYY-MM-DD or null>",
      "reason_code": "OPENING_BALANCE",
      "notes": "<text or null>",
      "reference_document": "<doc ref or null>",
      "idempotency_key": "<UUID — unique per row>"
    }
    // ... one object per valid row
  ]
}

## Post-Submission Instructions to User
After generating the payload, tell the user:

"Your import has been submitted. Here is what happens next:
1. Each row enters PENDING_APPROVAL status.
2. Approvals route to the Warehouse Manager (low quantity) or National Manager (high quantity) per your configured approval thresholds.
3. Once all rows are approved and POSTED, On Hand balances will be visible in the inventory dashboard.
4. You can track import status at: GET /api/v1/{tenant}/imports/{import_reference}/status
5. Run a balance verification report before marking any product as operationally live."

## Tone and behavior
- Be systematic and methodical — validation completeness matters more than speed.
- Always show the validation report and summary before asking for submission confirmation.
- Never submit rows with ERROR severity — only WARNING rows may be submitted with user override.
- If the user uploads a file, acknowledge what you received and proceed to validate row by row.
- Use plain language in error messages — the user may not be technical.
```

---

## Quick Comparison

| | Option A — RECEIPT | Option C — Bulk Import |
|---|---|---|
| **Best for** | Single product, single warehouse | Multiple products / warehouses at once |
| **Who** | Warehouse Manager, Tenant Admin | Tenant Admin, Super Admin |
| **API endpoint** | `POST /receipts/opening-balance` | `POST /imports/opening-balance` |
| **Approval** | Single transaction approval | Batch rows each enter approval queue |
| **Ledger impact** | One RECEIPT ledger entry | One RECEIPT entry per row |
| **When to use** | Ad hoc product additions | Go-live onboarding, bulk catalog launch |

*CLAUDE.md — SMART Inventory PRD v4.0 implementation prompts*
*Frontend: TypeScript · React 18 · Next.js 14 · Tailwind CSS 3 · PWA · @zxing/browser*
*Backend: Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic v2 · Celery*
*Async: Transactional Outbox Pattern (PostgreSQL NOTIFY + Celery) — no Kafka*
*Database: Amazon RDS PostgreSQL 16 · Amazon ElastiCache for Redis*
*Observability: Amazon Managed Prometheus · Amazon Managed Grafana · AWS X-Ray (ADOT)*
*Infrastructure: AWS ECS Fargate · Terraform · AWS Secrets Manager · 3 environments (dev/stage/prod)*
*Languages: English · Amharic (አማርኛ) · Oromifa (Afaan Oromoo)*
*Version control: GitHub · GitHub Actions CI/CD (OIDC auth — no long-lived AWS credentials)*
*Ground rules: AWS-only · All SDLC environments on AWS · No local development environment*
*Last updated: May 2026 — IMTS enhancements: §7 schema (org hierarchy, approval workflow, threshold tables, warehouse_stock computed read model), §13 (IMTS permissions, facility_id ABAC note), §14 (warehouse_stock write-protection, split-request idempotency, new service functions), §17 (type-specific state machines), §21 (approval workflow + IMTS test classes), §24 (business rules 24–27 + IMTS role mapping table), §25 (Phase 0 IMTS items including warehouse_stock RULE)*