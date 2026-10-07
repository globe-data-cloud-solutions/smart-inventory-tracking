## 4. GitHub Workflow & Branch Strategy

### Branches

```
main          production-ready. Direct pushes ARE allowed — see below.
develop       integration branch — features may target here
feature/<ticket>-<slug>   e.g. feature/SMART-42-fefo-dispatch
fix/<ticket>-<slug>       e.g. fix/SMART-88-rls-context
chore/<slug>              e.g. chore/add-oromifa-locale
```

### Branch protection rules

> **Current reality (2026-08):** the repositories are private on a free GitHub
> plan, where server-side branch protection / rulesets are unavailable. There is
> **no enforced protection on `main`** in either repo
> (`abiygit/smart-inventory-tracking` and
> `globe-data-cloud-solutions/smart-inventory-tracking`).

- **Direct pushes to `main` are allowed** in both repos. A PR is not always
  required — small, low-risk, or infra/CI changes may be committed to a branch
  and pushed, or pushed straight to `main`, at the author's discretion.
- Opening a PR remains the **preferred** path for non-trivial or reviewable
  changes, but it is a convention, not a hard gate.
- The reviewer/CI expectations below are **aspirational policy** to re-enable if
  the repos move to a plan that supports protection (GitHub Pro or public):
  - `main` and `develop`: 1 reviewer minimum, all CI checks pass
  - `CODEOWNERS` second reviewer for `backend/shared/permissions/` and `backend/migrations/`
- Note: `ci.yml` no longer auto-runs on pull requests (trigger is
  `workflow_dispatch`); run it manually from the Actions tab when verification
  is wanted.

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

# ── Gateway ──────────────────────────────────────────────────────────────────
TRUSTED_PROXY_HOPS=0           # 0 (default/local) = direct connection; set to 1 behind the ALB so
                                # X-Real-IP is read from the right end of X-Forwarded-For, not the ALB's own IP

# ── Billing (S5) ─────────────────────────────────────────────────────────────
STUB_WEBHOOK_SECRET            # HMAC-SHA256 secret for the STUB payment provider's webhook — from Secrets Manager

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


## 22. CI/CD — GitHub Actions

> **Three workflows only, all manually triggered (`workflow_dispatch`):**
> `ci.yml` (quality gate), `infrastructure.yml` (Terraform), `deploy.yml` (app rollout).
> During the bootstrap phase they authenticate to AWS with access-key **secrets**
> (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) plus repo **vars** `AWS_REGION` and
> `AWS_ACCOUNT_ID`. Migrating to GitHub OIDC (below) is the target once the
> `smart-github-actions-*` IAM roles exist. No PR auto-runs; no inline service containers.

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
  # Manual only — PR auto-runs are disabled. Trigger from the Actions tab.
  workflow_dispatch:

permissions:
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
```

> Note: the `test-backend` and `migration-round-trip` jobs above are shown with the
> **target** OIDC `role-to-assume` form. The live jobs currently use access-key
> secrets and fetch `smart/dev/*` from Secrets Manager. The `id-token: write`
> permission and OIDC role are added when the IAM role is provisioned.

### `.github/workflows/infrastructure.yml` — one Terraform pipeline for all environments

Manually triggered. Two parameters:

```
environment:  dev | stg | prd     # mapped to envs/dev | envs/stage | envs/prod
stage:        validate | plan | apply | delete
```

```yaml
on:
  workflow_dispatch:
    inputs:
      environment: { type: choice, options: [dev, stg, prd] }
      stage:       { type: choice, options: [validate, plan, apply, delete] }
```

Behaviour per `stage`:

```
validate → terraform init -backend=false && terraform validate   (offline; no AWS creds)
plan     → terraform init (static S3 backend) && terraform plan
apply    → terraform init && terraform apply -auto-approve
delete   → terraform init && terraform destroy -auto-approve
```

- A `setup` job maps `dev/stg/prd` → the `envs/<dir>` directory name (`dev/stage/prod`).
- `plan/apply/delete` configure AWS creds and use the **static** S3 backend baked into
  each `envs/<env>/main.tf` (no `-backend-config`). `validate` runs fully offline.
- The job is gated by the GitHub Environment `infra-<env>` — add reviewers on
  `infra-stage` / `infra-prod` to require approval before `apply`/`delete`.
- Assumes the S3 state bucket (`gdc-smart-terraform-state`) and DynamoDB lock table
  (`smart-terraform-locks`) already exist.

### `.github/workflows/deploy.yml` — one application deployment pipeline

Manually triggered. One parameter:

```
environment:  dev | stg | prd     # mapped to the smart-<env> ECS cluster
```

Jobs:

```
setup       → resolve dev/stg/prd → dev/stage/prod
build-push  → matrix over all 10 services: docker build backend/services/<svc>,
              push to ECR repo smart-<svc>, tags <env>-<sha> and <env>-latest
deploy      → run Alembic migrations via one-off ECS task (smart-<env>-migration),
              then `aws ecs update-service --force-new-deployment` for each
              smart-<env>-<svc>. Gated by GitHub Environment deploy-<env>.
```

- ECR repos are `smart-<service>` (NOT env-prefixed — created by the `ecs` Terraform
  module; images are differentiated by the `<env>-<sha>` tag).
- **Known gap:** the `ecs` module does not yet define `aws_ecs_service` or task
  definitions. Until it does, the migration + rollout steps **warn and skip** rather
  than fail. Image build/push works today; rollout becomes effective once those
  resources exist in Terraform.

### Pipeline summary

```
Quality gate   → run CI manually (Actions tab): lint, tests, permission-drift,
                 migration round-trip, locale-check.
Infrastructure → run infrastructure.yml with (environment, stage).
                 validate is safe anytime; apply/delete gated by infra-<env> reviewers.
Deploy app     → run deploy.yml with (environment): build+push images, migrate, roll out.

Auth:     access-key secrets during bootstrap (target: GitHub OIDC per environment).
Secrets:  AWS Secrets Manager — never in GitHub Secrets or workflow files.
Backend:  static S3 (gdc-smart-terraform-state) + DynamoDB (smart-terraform-locks),
          state key smart-inventory-platform/<env>/terraform.tfstate.
```

