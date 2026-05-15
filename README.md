# SMART Inventory Management Platform

> Multi-tenant SaaS inventory management for Producers/Importers and Retailers/Distributors.
> One codebase, two personas — differentiated entirely by `organisation_type` on the tenant record.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [System Components](#system-components)
- [Transactional Outbox Pattern](#transactional-outbox-pattern)
- [Permission System (RBAC + ABAC)](#permission-system-rbac--abac)
- [Inventory Ledger](#inventory-ledger)
- [Dispatch Strategy Engine](#dispatch-strategy-engine)
- [Workflow State Machines](#workflow-state-machines)
- [Offline Sync Strategy](#offline-sync-strategy)
- [Deployment Pipeline](#deployment-pipeline)
- [Repository Structure](#repository-structure)
- [Phase Roadmap](#phase-roadmap)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)

---

## Architecture Overview

```mermaid
graph TB
    subgraph Clients["Clients — PWA (sm: mobile | md: tablet | lg: desktop)"]
        MOB[📱 Android / iOS\nWarehouse staff]
        TAB[📟 Tablet\nWarehouse Manager]
        DSK[🖥️ Desktop\nNM / RM / Finance / Auditor]
    end

    subgraph AWS_Frontend["AWS — Frontend"]
        CF[CloudFront CDN]
        S3_LOCALES[S3 — Locale packs\nen.json / am.json / or.json]
    end

    subgraph AWS_Backend["AWS ECS Fargate — Backend Services"]
        GW[API Gateway\nJWT · Rate limit · Plan cap]

        subgraph Core["Core Services"]
            AUTH[Auth Service\nCognito integration]
            TENANT[Tenant Service\nWizard · Org type]
            PRODUCT[Product Service\npg_trgm search]
            INV[Inventory Service\nLedger · Dispatch · State machine]
            ORDER[Order Service]
            LOGI[Logistics Service\nFleet · Routes]
        end

        subgraph Async["Async / Background"]
            NOTIF[Notification Service\nCelery worker]
            SYNC[Sync Service\nOffline conflict resolution]
            ANALYTICS[Analytics Service\nAI pipeline · Read-replica only]
        end
    end

    subgraph AWS_Data["AWS — Data Layer"]
        RDS_PRIMARY[(RDS PostgreSQL 16\nPrimary — writes)]
        RDS_REPLICA[(RDS PostgreSQL 16\nRead Replica — analytics / reports)]
        REDIS[(ElastiCache Redis\nCelery broker · Session · AI cache)]
        COGNITO[AWS Cognito\nIdentity provider]
        S3_ATTACH[S3 — Attachments]
        SECRETS[Secrets Manager\nAll secrets — injected at ECS startup]
    end

    subgraph AWS_Obs["AWS — Observability"]
        AMP[Amazon Managed\nPrometheus]
        AMG[Amazon Managed\nGrafana]
        XRAY[AWS X-Ray\nvia ADOT]
        CW[CloudWatch\nAlarms · Logs]
    end

    MOB --> CF
    TAB --> CF
    DSK --> CF
    CF --> GW
    CF --> S3_LOCALES

    GW --> AUTH
    GW --> TENANT
    GW --> PRODUCT
    GW --> INV
    GW --> ORDER
    GW --> LOGI
    GW --> NOTIF
    GW --> SYNC
    GW --> ANALYTICS

    AUTH --> COGNITO
    Core --> RDS_PRIMARY
    Async --> RDS_PRIMARY
    ANALYTICS --> RDS_REPLICA

    INV -.->|outbox INSERT| RDS_PRIMARY
    RDS_PRIMARY -.->|pg_notify| REDIS
    REDIS -.->|Celery tasks| NOTIF

    Core --> REDIS
    Async --> REDIS
    Core --> S3_ATTACH

    SECRETS -.->|injected at startup| Core
    SECRETS -.->|injected at startup| Async

    Core --> AMP
    Core --> XRAY
    Core --> CW
```

---

## System Components

```mermaid
graph LR
    subgraph Backend["Backend — Python 3.12 / FastAPI"]
        direction TB
        SH[shared/\npermissions · db · outbox · utils]

        subgraph Services
            GW2[api-gateway]
            A[auth-service]
            T[tenant-service]
            P[product-service]
            I[inventory-service]
            O[order-service]
            L[logistics-service]
            AN[analytics-service]
            N[notification-service]
            SY[sync-service]
        end

        Services --> SH
    end

    subgraph Frontend["Frontend — TypeScript / Next.js 14"]
        direction TB
        APP[App Router pages]
        COMP[components/\nui · features]
        HOOKS[hooks/\nuseAuth · usePermission\nuseOfflineSync · useScanner]
        LIB[lib/\napi · auth · i18n · scanner · permissions]
        STORE[store/\nofflineQueue — IndexedDB]
        SW[public/sw.js\nService Worker — PWA]
    end

    subgraph Migrations["Database — Alembic"]
        MIG[migrations/versions/\n001_initial_schema.py\nAll Phase 0 tables]
    end

    subgraph Infra["Infrastructure — Terraform"]
        TF_M[modules/\necs · rds · elasticache\ncognito · s3 · networking\nobservability · secrets]
        TF_E[envs/\ndev · stage · prod]
    end

    subgraph Scripts["Scripts"]
        SC1[seed_permissions.py\n115 actions → DB]
        SC2[ci_drift_check.py\nroutes without @require_permission]
        SC3[create_partitions.py\nmonthly tx partitions]
    end
```

---

## Transactional Outbox Pattern

> Replaces Apache Kafka. Zero new infrastructure — atomic with every business transaction.

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI Service
    participant DB as PostgreSQL (Primary)
    participant NOTIFY as pg_notify trigger
    participant REDIS as ElastiCache Redis
    participant WORKER as Celery Worker
    participant EFFECT as Side Effect\n(Notification / Analytics / Cache)

    Client->>API: POST /inventory/receive
    API->>DB: BEGIN TRANSACTION
    API->>DB: INSERT inventory_transactions (ledger)
    API->>DB: UPDATE inventory_balances (running total)
    API->>DB: INSERT outbox (InventoryUpdated event)
    DB-->>NOTIFY: AFTER INSERT trigger fires
    NOTIFY-->>REDIS: pg_notify('outbox_insert', row_id)
    API->>DB: COMMIT (atomic — all 3 INSERTs or none)
    API-->>Client: 201 Created

    REDIS-->>WORKER: Celery task triggered immediately
    WORKER->>DB: SELECT FOR UPDATE SKIP LOCKED (idempotency check)
    WORKER->>DB: UPDATE outbox SET status='PROCESSING'
    WORKER->>EFFECT: Execute side effect
    WORKER->>DB: UPDATE outbox SET status='PROCESSED'

    Note over REDIS,WORKER: Celery beat polls every 30s as fallback\nfor any missed pg_notify events
```

---

## Permission System (RBAC + ABAC)

> Three mandatory layers — all three must pass. UI hiding is NOT a security layer.

```mermaid
flowchart TD
    REQUEST[Incoming API Request]

    L1{Layer 1\nAPI Gateway\nJWT valid?}
    L2{Layer 2\nService Layer\nRBAC check}
    L3{Layer 2b\nABAC check\ntenant · region · warehouse}
    L4{Layer 2c\nConditional?\napproval_threshold}
    L5{Layer 3\nPostgreSQL RLS\ntenant_id = session context}

    AUDIT[audit_logs INSERT\nappend-only]
    APPROVE[Route to approval workflow\nstatus = PENDING_APPROVAL]
    DENY403[HTTP 403\nRBAC_DENIED or ABAC_DENIED]
    DENY401[HTTP 401\nUnauthenticated]
    SUCCESS[✅ Execute handler]

    REQUEST --> L1
    L1 -->|invalid / expired| DENY401
    L1 -->|valid| L2
    L2 -->|no grant| DENY403
    L2 -->|grant found| L3
    L3 -->|tenant / scope mismatch| DENY403
    L3 -->|pass| L4
    L4 -->|CONDITIONAL grant| APPROVE
    L4 -->|FULL grant| L5
    L5 -->|row hidden by RLS| L5_EMPTY[empty result set]
    L5 -->|row visible| SUCCESS

    L2 --> AUDIT
    L3 --> AUDIT
    SUCCESS --> AUDIT
    APPROVE --> AUDIT
```

**Role hierarchy (highest → lowest):**

```mermaid
graph LR
    SA["SA (10)\nSystem Admin"] --> TA["TA (9)\nTenant Admin"]
    TA --> NM["NM (8)\nNational Mgr"]
    NM --> RM["RM (7)\nRegional Mgr"]
    RM --> WM["WM (6)\nWarehouse Mgr"]
    RM --> LM["LM (6)\nLogistics Mgr"]
    WM --> SA_GT["SA_GT (4)\nSales Agent"]
    SA_GT --> RT["RT (3)\nRetailer"]
    RT --> AU["AU (2)\nAuditor"]
    AU --> SYS["SYS (1)\nSystem — ai:model_run only"]
```

---

## Inventory Ledger

> Immutable by design — stock balance is always derived from the ledger, never stored directly.

```mermaid
flowchart TD
    RECEIVE[Client: Receive Stock\nPOST /inventory/receive]
    CHECK_KEY{Idempotency key\nalready exists?}
    LOCK[SELECT FOR UPDATE\ninventory_balances row]
    FLOOR{quantity delta < 0?\nCheck stock floor}
    INSERT_TX[INSERT inventory_transactions\n— IMMUTABLE LEDGER RECORD —]
    UPDATE_BAL[UPDATE inventory_balances\nrunning total only]
    OUTBOX[INSERT outbox\nInventoryUpdated event]
    COMMIT[COMMIT — atomic]
    RESP201[HTTP 201 Created]
    RESP409[HTTP 409\nDuplicate transaction]
    RESP422[HTTP 422\nInsufficient stock]

    RECEIVE --> CHECK_KEY
    CHECK_KEY -->|yes| RESP409
    CHECK_KEY -->|no| LOCK
    LOCK --> FLOOR
    FLOOR -->|insufficient| RESP422
    FLOOR -->|ok| INSERT_TX
    INSERT_TX --> UPDATE_BAL
    UPDATE_BAL --> OUTBOX
    OUTBOX --> COMMIT
    COMMIT --> RESP201

    style INSERT_TX fill:#fef3c7,stroke:#f59e0b
    style UPDATE_BAL fill:#dbeafe,stroke:#3b82f6
    style OUTBOX fill:#d1fae5,stroke:#10b981
```

---

## Dispatch Strategy Engine

```mermaid
flowchart TD
    TRIGGER[Dispatch request\nproduct_id + warehouse_id + qty]
    AUTO{batch_tracking = true\nAND expiry_tracking = true?}
    PRODUCT_CFG{Product-level\nstrategy configured?}
    CATEGORY_CFG{Category-level\nstrategy configured?}
    FEFO[Strategy: FEFO\nSort by expiry_date ASC]
    FIFO[Strategy: FIFO\nSort by received_at ASC]
    LIFO[Strategy: LIFO\nSort by received_at DESC]
    DEFAULT[Default: FIFO]

    SELECT[Select lots until qty filled\nLotSelection list]
    INSUFF[InsufficientStockError\nHTTP 422]

    TRIGGER --> AUTO
    AUTO -->|yes — auto enforce| FEFO
    AUTO -->|no| PRODUCT_CFG
    PRODUCT_CFG -->|yes| STRATEGY_P{strategy?}
    STRATEGY_P -->|FEFO| FEFO
    STRATEGY_P -->|FIFO| FIFO
    STRATEGY_P -->|LIFO| LIFO
    PRODUCT_CFG -->|no| CATEGORY_CFG
    CATEGORY_CFG -->|yes| STRATEGY_C{strategy?}
    STRATEGY_C -->|FEFO| FEFO
    STRATEGY_C -->|FIFO| FIFO
    STRATEGY_C -->|LIFO| LIFO
    CATEGORY_CFG -->|no| DEFAULT

    FEFO --> SELECT
    FIFO --> SELECT
    LIFO --> SELECT
    DEFAULT --> SELECT
    SELECT -->|remaining > 0| INSUFF
    SELECT -->|fulfilled| DONE[✅ Return LotSelection list]
```

---

## Workflow State Machines

```mermaid
stateDiagram-v2
    [*] --> DRAFT: create transfer

    DRAFT --> SUBMITTED: WM submits
    DRAFT --> CANCELLED: cancel

    SUBMITTED --> APPROVED: RM approves
    SUBMITTED --> REJECTED: RM rejects
    SUBMITTED --> CANCELLED: cancel

    APPROVED --> IN_TRANSIT: dispatch
    APPROVED --> CANCELLED: cancel

    IN_TRANSIT --> RECEIVED: destination WM receives
    IN_TRANSIT --> CANCELLED: cancel

    RECEIVED --> CLOSED: auto-close

    CLOSED --> [*]
    REJECTED --> [*]
    CANCELLED --> [*]
```

```mermaid
stateDiagram-v2
    state "Adjustment Order" as adj
    [*] --> DRAFT: create adjustment

    DRAFT --> SUBMITTED: WM submits
    DRAFT --> CANCELLED: cancel

    SUBMITTED --> APPROVED: RM approves (CONDITIONAL if above threshold)
    SUBMITTED --> REJECTED: RM rejects

    APPROVED --> APPLIED: system applies ledger INSERT

    APPLIED --> [*]
    REJECTED --> [*]
    CANCELLED --> [*]
```

---

## Offline Sync Strategy

```mermaid
sequenceDiagram
    participant User as Warehouse Staff\n(Mobile / Tablet)
    participant SW as Service Worker\n(sw.js)
    participant IDB as IndexedDB\n(offlineQueue.ts)
    participant API as /api/v1/sync/batch

    User->>SW: POST /api/v1/inventory/receive (offline)
    SW-->>SW: Network fails — 503 OFFLINE
    SW->>IDB: enqueueOfflineTransaction(idempotencyKey, action, payload)
    SW-->>User: Show "Queued for sync" indicator

    Note over User,API: Device comes back online

    SW->>SW: navigator.onLine = true event
    SW->>IDB: getPendingTransactions()
    IDB-->>SW: [tx1, tx2, tx3...]
    SW->>API: POST /api/v1/sync/batch [{idempotency_key, action, payload}]

    API->>API: Check idempotency_key EXISTS → SYNCED (already processed)
    API->>API: Process new transactions → SYNCED or CONFLICT

    API-->>SW: [{idempotency_key, status: "SYNCED"}, ...]
    SW->>IDB: updateTransactionStatus(key, "SYNCED")
    SW->>IDB: clearSyncedTransactions()
    SW-->>User: Sync complete ✅
```

---

## Deployment Pipeline

```mermaid
gitGraph
   commit id: "feature branch"
   branch feature/SMART-42-fefo-dispatch
   checkout feature/SMART-42-fefo-dispatch
   commit id: "implementation"
   commit id: "tests + permissions"
   checkout main
   branch develop
   checkout develop
   merge feature/SMART-42-fefo-dispatch id: "PR merged (CI green)"

   commit id: "auto-deploy → dev" type: HIGHLIGHT

   checkout main
   merge develop id: "merge to main"
   commit id: "deploy → stage (approval gate)" type: HIGHLIGHT

   commit id: "v1.2.0 tag"
   commit id: "deploy → prod (named approver)" type: HIGHLIGHT
```

**CI jobs on every PR:**

```mermaid
flowchart LR
    PR[PR opened] --> LINT_BE[lint-backend\nruff + mypy --strict]
    PR --> LINT_FE[lint-frontend\ntsc --noEmit + eslint]
    PR --> DRIFT[permission-drift-check\nci_drift_check.py]
    PR --> LOCALE[locale-check\nen + am + or JSON valid]
    PR --> TEST_BE[test-backend\npytest against dev AWS RDS]
    PR --> TEST_FE[test-frontend\njest --coverage]

    TEST_BE --> ROUND[migration-round-trip\nupgrade → downgrade -1 → upgrade]

    LINT_BE & LINT_FE & DRIFT & LOCALE & TEST_FE & ROUND --> GREEN{All green?}
    GREEN -->|yes| MERGE[Allow merge to develop]
    GREEN -->|no| BLOCK[❌ PR blocked]
```

---

## Repository Structure

```
smart-platform/
├── .github/
│   ├── workflows/          # ci.yml · deploy-dev · deploy-staging · deploy-prod
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS          # Extra review: permissions/ and migrations/
│
├── frontend/               # Next.js 14 App Router PWA
│   ├── src/
│   │   ├── app/            # Pages (dashboard/inventory, products, reports...)
│   │   ├── components/     # ui/ (Button, Card, Badge) · features/ (scanner, inventory)
│   │   ├── hooks/          # useAuth · usePermission · useOfflineSync · useScanner
│   │   ├── lib/            # api · auth · i18n · scanner · permissions · utils
│   │   └── store/          # offlineQueue.ts (IndexedDB)
│   └── public/sw.js        # Service worker — cache shell + locales, queue offline POSTs
│
├── backend/
│   ├── shared/             # Editable installs — all services depend on this
│   │   ├── permissions/    # registry.py (115 actions) · middleware · audit · casbin
│   │   ├── db/             # session · rls · models (Tenant, User, Product, Inventory...)
│   │   ├── outbox/         # writer · worker (Celery) · notify (pg_listen) · schemas
│   │   └── utils/          # idempotency · pagination · responses
│   │
│   ├── services/           # 10 FastAPI microservices (each with Dockerfile)
│   │   ├── api-gateway/    # JWT validation, rate limiting, proxy
│   │   ├── auth-service/   # Cognito ↔ SMART JWT exchange
│   │   ├── tenant-service/ # Tenant CRUD + onboarding wizard
│   │   ├── product-service/# Products + pg_trgm SKU search
│   │   ├── inventory-service/ # Ledger · dispatch · state machines · cycle count
│   │   ├── order-service/
│   │   ├── logistics-service/
│   │   ├── analytics-service/ # AI pipeline — READ REPLICA ONLY
│   │   ├── notification-service/ # Celery outbox handlers
│   │   └── sync-service/   # Offline conflict resolution
│   │
│   └── migrations/         # Alembic — shared across all services
│       └── versions/001_initial_schema.py  # Phase 0 — all required tables
│
├── locales/                # Language packs — uploaded to S3
│   ├── en.json             # English (default)
│   ├── am.json             # Amharic (አማርኛ)
│   └── or.json             # Oromifa (Afaan Oromoo) — needs native speaker review
│
├── infra/terraform/
│   ├── modules/            # ecs · rds · elasticache · cognito · s3 · networking · observability
│   ├── envs/dev|stage|prod/
│   └── backend.tf          # Remote state: S3 + DynamoDB locking
│
├── scripts/
│   ├── seed_permissions.py   # Seeds all 115 actions from registry.py → role_permissions table
│   ├── ci_drift_check.py     # Fails CI if any route lacks @require_permission
│   └── create_partitions.py  # Monthly inventory_transactions partitions
│
└── CLAUDE.md               # Implementation prompt — PRD v4.0
```

---

## Phase Roadmap

```mermaid
gantt
    title SMART Platform Delivery
    dateFormat  YYYY-MM
    axisFormat  %b %Y

    section Phase 0 — Foundation
    Infrastructure + core (no users) :done, p0, 2026-05, 3M

    section Phase 1 — Producer MVP
    Onboard 4-6 Producer companies   :p1, after p0, 4M

    section Phase 2 — Retailer Onboarding
    Onboard 4-6 Retailer companies   :p2, after p1, 4M

    section Phase 3 — AI & Scale
    Demand forecast + replenishment AI :p3, after p2, 5M

    section Phase 4 — Expansion
    Franchise umbrella model           :p4, after p3, 99d
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 18 · Next.js 14 (App Router) · TypeScript 5 strict · Tailwind CSS 3 · PWA |
| **Scanning** | @zxing/browser — Code128 / EAN-13 / QR / DataMatrix — < 1s P90 |
| **Offline** | Service Worker · IndexedDB (idb) · sync-service conflict resolution |
| **i18n** | English · Amharic (አማርኛ) · Oromifa (Afaan Oromoo) — S3-hosted JSON packs |
| **Backend** | Python 3.12 · FastAPI · SQLAlchemy 2.x async · Pydantic v2 · Alembic |
| **Permissions** | Casbin RBAC + ABAC · 115 actions · 3-layer enforcement |
| **Async** | Transactional Outbox (PostgreSQL NOTIFY + Celery) — **no Kafka** |
| **Database** | Amazon RDS PostgreSQL 16 (primary + read replica) · pg_trgm · RLS |
| **Cache** | Amazon ElastiCache for Redis — Celery broker · session · AI forecast cache |
| **Identity** | AWS Cognito |
| **Infrastructure** | AWS ECS Fargate · Terraform · 3 environments (dev / stage / prod) |
| **Secrets** | AWS Secrets Manager — injected at ECS startup. No `.env` files. |
| **Observability** | Amazon Managed Prometheus · Amazon Managed Grafana · AWS X-Ray (ADOT) · CloudWatch |
| **CI/CD** | GitHub Actions · OIDC auth (no long-lived credentials) |
| **Search** | pg_trgm (default) · Amazon OpenSearch (conditional — explicit tenant request only) |

---

## Demo Application

The frontend demo runs at **http://localhost:3000** (start with `cd frontend && pnpm dev`).

### Demo tenants & login credentials

#### Addis Water (Bottled Water Producer — `addis-water`)

| Email | Password | Role | Facility |
|---|---|---|---|
| admin@addis-water.com | AddisWater@2026 | TA | All |
| production@addis-water.com | AddisWater@2026 | NM | Main Production Center (MWH) |
| regional@addis-water.com | AddisWater@2026 | RM | All facilities |
| logistics@addis-water.com | AddisWater@2026 | LM | All facilities |
| north.wm@addis-water.com | AddisWater@2026 | WM | North WH (RWH) |
| northsub.wm@addis-water.com | AddisWater@2026 | WM | North-Subcenter WH |
| south.wm@addis-water.com | AddisWater@2026 | WM | South WH |
| east.wm@addis-water.com | AddisWater@2026 | WM | East WH |
| west.wm@addis-water.com | AddisWater@2026 | WM | West WH |

#### Muger Cement (Cement Manufacturer — `muger-cement`)

Org hierarchy:
```
Harar Production Center (MWH)
  └── Dire Dawa Regional WH (RWH)
        └── Hawassa WH (WH)

Ambo Production Center (MWH)
  ├── Kombolcha WH (WH)
  └── Mekele WH (WH)
```

| Email | Password | Role | Facility | Sees transfers involving |
|---|---|---|---|---|
| admin@muger-cement.com | MugerCement@2026 | TA | All | All |
| harar.pm@muger-cement.com | MugerCement@2026 | NM | Harar MWH | Harar + Dire Dawa + Hawassa |
| ambo.pm@muger-cement.com | MugerCement@2026 | NM | Ambo MWH | Ambo + Kombolcha + Mekele |
| regional@muger-cement.com | MugerCement@2026 | RM | All facilities | All |
| logistics@muger-cement.com | MugerCement@2026 | LM | All facilities | All |
| diredawa.wm@muger-cement.com | MugerCement@2026 | WM | Dire Dawa RWH | Dire Dawa + Hawassa |
| hawassa.wm@muger-cement.com | MugerCement@2026 | WM | Hawassa WH | Hawassa only |
| kombolcha.wm@muger-cement.com | MugerCement@2026 | WM | Kombolcha WH | Kombolcha only |
| mekele.wm@muger-cement.com | MugerCement@2026 | WM | Mekele WH | Mekele only |

#### System Administrator

| Email | Password | Role |
|---|---|---|
| smartadmin@smart-inventory.com | SmartAdmin@2026 | SA |

### IMTS Transfer workflow

| Transfer Type | Initiator | From field | To field |
|---|---|---|---|
| **PULL** | Any WH (requesting stock) | Selectable source (MWH/RWH) | **Auto-locked to user's WH** |
| **PUSH** | MWH / RWH only | **Auto-locked to user's facility** | Selectable destination |
| **SISTER** | Any WH (lateral) | **Auto-locked to user's WH** | Selectable same-level WH |

WM at WH/SUB_WH level: PULL and SISTER only. NM at MWH, RM, LM: all types including PUSH.

### Transfer state machines

```
PULL:   DRAFT → PENDING_REVIEW → PENDING_APPROVAL → APPROVED → ISSUED → IN_TRANSIT → [PARTIALLY_RECEIVED] → RECEIVED → COMPLETED
PUSH:   DRAFT → PENDING_APPROVAL → APPROVED → [ADVISED] → ISSUED → IN_TRANSIT → [PARTIALLY_RECEIVED] → RECEIVED → COMPLETED
SISTER: DRAFT → PENDING_SOURCE_CONFIRM → PENDING_DEST_CONFIRM → PENDING_APPROVAL → APPROVED → ISSUED → IN_TRANSIT → [PARTIALLY_RECEIVED] → RECEIVED → COMPLETED
```

### Inventory visibility (hierarchy-scoped)

| Role | Sees in Transfers page |
|---|---|
| TA / SA | All transfers |
| RM / LM | All transfers |
| NM at MWH | All transfers (apex of supply hierarchy) |
| WM at RWH | Own RWH + all descendant WHs |
| WM at WH/SUB_WH | Only transfers involving their warehouse |

Completed, Cancelled, and Rejected transfers are archived to the **Audit Log** page.

### Audit Log

Every transfer transition, stock receive, and issue is recorded in the Audit Log with separate columns for: product name, quantity/unit, From warehouse, To warehouse. Data persists to `localStorage` across refreshes and logins.

---

## Getting Started

> There is no local development environment. All SDLC environments run on AWS ECS Fargate.

### Prerequisites

```
python 3.12 · uv · node 20 · pnpm · aws-cli v2 · terraform
GitHub access to smart-platform repo
AWS IAM identity with dev environment permissions (provisioned by Tech Lead via Terraform)
```

### Developer workflow

```bash
# 1. Authenticate to AWS dev environment
aws sso login --profile smart-dev

# 2. Create a feature branch
git checkout develop
git pull
git checkout -b feature/SMART-<n>-<slug>

# 3. Write code + tests (IDE only — no local services)

# 4. Run unit tests locally (no AWS services needed)
cd backend/shared && uv pip install -e ".[test]"
pytest backend/ -v -m "unit" --tb=short

# 5. Push → GitHub Actions CI runs automatically against dev AWS
git push -u origin feature/SMART-<n>-<slug>

# 6. Open PR → review CI results → address feedback → merge to develop
# Merge to develop → auto-deploys to dev environment
```

### Key absolute constraints

- **Never** build separate codebases for producers vs retailers
- **Never** update stock balances directly — all mutations `INSERT` into `inventory_transactions`
- **Never** ship a new endpoint without `@require_permission` and `registry.py` entry
- **Never** run analytics queries on the primary database — read replicas only
- **Never** allow AI recommendations to auto-execute — status must be `PENDING_APPROVAL`
- **Never** use Kafka, RabbitMQ, or aiokafka — async uses the Outbox Pattern
- **Never** hardcode English text in JSX — all UI strings use `t()` i18n keys
- **Never** commit secrets, `.env` files, or connection strings

---

*SMART Inventory — PRD v4.0 · Python 3.12 / FastAPI · Next.js 14 / TypeScript · AWS ECS Fargate · Terraform*
*Languages: English · Amharic (አማርኛ) · Oromifa (Afaan Oromoo)*
*Last updated: May 2026 — IMTS enhancements: org hierarchy, type-specific state machines, audit log, partial receive*
