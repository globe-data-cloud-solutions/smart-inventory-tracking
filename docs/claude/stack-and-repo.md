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
28. [Org Hierarchy Configuration](#28-org-hierarchy-configuration)
29. [Engineering Guardrails — Lessons from Incidents](#29-engineering-guardrails--lessons-from-incidents)

> Note: this is the original table of contents, retained verbatim for history.
> The live document is now split — see the INDEX at the bottom of CLAUDE.md.

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
│  Python 3.12 (Docker/ECS target)                                     │
│  local dev currently runs 3.14 — code stays 3.12-compatible          │
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
│   │   │   ├── registry.py            # SINGLE SOURCE OF TRUTH — all 156 actions
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
│       └── envs/                      # Each env is its own root module with a
│           ├── dev/                   #   STATIC backend "s3" block (only the state
│           ├── stage/                 #   key differs per env). Remote state:
│           └── prod/                  #   S3 smart-terraform-state + DynamoDB smart-terraform-locks
│
├── scripts/
│   ├── seed_permissions.py            # Seeds all 156 actions from registry.py
│   ├── ci_drift_check.py             # Fails CI if any route lacks @require_permission
│   └── create_partitions.py          # Monthly inventory_transactions partitions
│
└── CLAUDE.md                          # This file
                                       # No .env.example — all secrets via AWS Secrets Manager
```

