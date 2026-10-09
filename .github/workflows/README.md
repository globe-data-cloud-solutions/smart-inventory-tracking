# GitHub Actions Workflows — SMART Platform

This directory contains the CI/CD workflows for provisioning, testing, and deploying the SMART Inventory Management Platform.

## Table of Contents

1. [Available Workflows](#available-workflows)
2. [Prerequisites](#prerequisites)
3. [Provisioning Infrastructure](#provisioning-infrastructure)
4. [Deploying Applications](#deploying-applications)
5. [Deprovisioning](#deprovisioning)
6. [Troubleshooting](#troubleshooting)

---

## Available Workflows

### 1. **CI** (`ci.yml`)
Automated quality gate that runs on manual trigger.
- Linting (ruff, TypeScript strict)
- Type checking (mypy, tsc)
- Unit tests
- Permission registry drift check
- Migration round-trip validation
- Locale file validation

**Trigger:** Manual from Actions tab
```bash
gh workflow run ci.yml
```

### 2. **Infrastructure** (`infrastructure.yml`)
Terraform-based provisioning and deprovisioning for AWS resources.

**Parameters:**
- `environment`: `dev` | `stg` | `prd`
- `stage`: `validate` | `plan` | `apply` | `delete`

**Trigger:**
```bash
gh workflow run infrastructure.yml -f environment=dev -f stage=validate
```

### 3. **Deploy Application** (`deploy.yml`)
Builds Docker images, pushes to ECR, runs migrations, and deploys to ECS.

**Parameters:**
- `environment`: `dev` | `stg` | `prd`

**Trigger:**
```bash
gh workflow run deploy.yml -f environment=dev
```

### 4. **Container Smoke Test** (`container-smoke.yml`)
Runs `scripts/docker/smoke.sh` on push to `main` and also on pull requests targeting `main`,
when backend/frontend/locales/docker-related paths change.

### 5. **Terraform Check** (`terraform-check.yml`)
PR-only offline check for `infra/terraform/**` changes: `terraform fmt -check` plus
`init -backend=false` + `validate` for dev/stage/prod. No AWS credentials, no plan/apply.

---

## Prerequisites

Before provisioning, ensure you have:

### AWS Setup
- [ ] AWS Account with access to `877573132642` (or your account ID)
- [ ] AWS IAM credentials configured locally:
  ```bash
  aws configure --profile smart-infra
  # Enter: Access Key ID, Secret Access Key, Region (us-east-1), Output (json)
  ```
- [ ] AWS credentials set as GitHub repository secrets:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`

### Repository Setup
- [ ] Repository variables configured:
  - `AWS_ACCOUNT_ID` = `877573132642`
  - `AWS_REGION` = `us-east-1`
- [ ] Docker access (if testing locally):
  ```bash
  docker --version
  ```

### Git Setup
- [ ] GitHub CLI installed:
  ```bash
  gh --version
  ```
- [ ] Authenticated to GitHub:
  ```bash
  gh auth login
  ```

---

## Provisioning Infrastructure

### Step 1: Validate Terraform Configuration

This step runs offline without needing AWS credentials. It validates syntax and structure.

```bash
gh workflow run infrastructure.yml -f environment=dev -f stage=validate
```

**Expected result:**
- ✅ Terraform validation passes
- ✅ No AWS access required
- Duration: ~30 seconds

**Monitor:**
```bash
gh run view --web  # Opens run in browser
# OR
gh run list --workflow=infrastructure.yml --limit=1
```

### Step 2: Plan Infrastructure Changes

This step connects to AWS and creates a detailed plan of what resources will be created.

```bash
gh workflow run infrastructure.yml -f environment=dev -f stage=plan
```

**Expected output:**
- Shows all 55 resources to be created
- VPC, RDS, ElastiCache, ECS, ECR, S3, Cognito, etc.
- `Plan: 55 to add, 0 to change, 0 to destroy`
- Duration: ~3-5 minutes

**Review the plan:**
```bash
gh run view <run-id> --log | tail -200
```

### Step 3: Apply Infrastructure

This actually creates all AWS resources. **This is a destructive operation in reverse (creates resources).**

```bash
gh workflow run infrastructure.yml -f environment=dev -f stage=apply
```

**Expected result:**
- ✅ All 55 resources created successfully
- ✅ RDS primary and read replica operational
- ✅ ElastiCache Redis cluster ready
- ✅ ECS Fargate cluster configured
- ✅ ECR repositories created (10 services)
- Duration: **10-15 minutes** (RDS provisioning is slow)

**Verify in AWS:**
```bash
# Check RDS
aws rds describe-db-instances --profile smart-infra \
  --query 'DBInstances[*].[DBInstanceIdentifier,DBInstanceStatus]'

# Check ElastiCache
aws elasticache describe-cache-clusters --profile smart-infra

# Check ECS
aws ecs list-clusters --profile smart-infra

# Check ECR
aws ecr describe-repositories --profile smart-infra
```

---

## Deploying Applications

### Prerequisites for App Deployment

Before deploying applications, ensure:
- [ ] Infrastructure is fully provisioned (Run infrastructure `apply`)
- [ ] AWS credentials are set as GitHub secrets (see Prerequisites)
- [ ] Code is committed and pushed to GitHub

### Step 1: Trigger Application Deployment

This workflow:
1. Builds Docker images for all 10 services
2. Pushes images to ECR with tags `dev-<commit-sha>` and `dev-latest`
3. Runs Alembic database migrations
4. Updates ECS services (force new deployment)

```bash
gh workflow run deploy.yml -f environment=dev
```

**What happens:**
- **Build & Push (5-10 minutes total)**
  - Each service builds sequentially
  - Images pushed to ECR (35-45 seconds each)
- **Migrations (2-3 minutes)**
  - One-off ECS task runs `alembic upgrade head`
  - All database migrations executed
- **ECS Rollout (1-2 minutes)**
  - Each service's deployment is updated
  - New task definitions pulled from latest images

**Total duration: 8-15 minutes**

### Step 2: Verify Deployment

```bash
# Check ECS service status
aws ecs list-services --cluster smart-dev --profile smart-infra
aws ecs describe-services --cluster smart-dev --services smart-dev-api-gateway \
  --profile smart-infra

# View ECS task logs
aws logs tail /ecs/smart-dev/api-gateway --follow --profile smart-infra

# Check container health
aws ecs list-tasks --cluster smart-dev --profile smart-infra
aws ecs describe-tasks --cluster smart-dev --tasks <task-arn> \
  --profile smart-infra
```

### Step 3: Test API

Once deployed, test the API:

```bash
# Get the API Gateway endpoint
aws ecs describe-services --cluster smart-dev --services smart-dev-api-gateway \
  --profile smart-infra --query 'services[0].loadBalancers'

# Test health endpoint (adjust URL to your ALB)
curl http://<api-gateway-alb-url>/health
```

---

## Deprovisioning

### ⚠️ WARNING: Deprovisioning Destroys All Resources

This cannot be undone. Ensure you have backups or don't need the data.

### Step 1: Delete Application Services

Before deleting infrastructure, optionally stop ECS services:

```bash
# Manually scale down services to 0 (optional)
for service in api-gateway auth-service tenant-service product-service \
               inventory-service order-service logistics-service \
               analytics-service notification-service sync-service; do
  aws ecs update-service --cluster smart-dev --service smart-dev-$service \
    --desired-count 0 --profile smart-infra
done
```

### Step 2: Destroy Infrastructure

This deletes **all AWS resources** — VPC, RDS, ElastiCache, ECS, ECR, etc.

```bash
gh workflow run infrastructure.yml -f environment=dev -f stage=delete
```

**Confirmation required:**
- Gated by GitHub Environment `infra-dev`
- You may need to add reviewers to require manual approval

**Expected result:**
- ✅ All 55 resources destroyed
- ✅ No AWS resources remain (except S3 bucket if it has data)
- Duration: **5-10 minutes**

**Verify cleanup:**
```bash
# Check RDS is gone
aws rds describe-db-instances --profile smart-infra

# Check ECS cluster is deleted
aws ecs describe-clusters --clusters smart-dev --profile smart-infra
```

---

## Environment-Specific Deployments

### Development (`dev`)
```bash
# Full provisioning cycle for dev
gh workflow run infrastructure.yml -f environment=dev -f stage=validate
gh workflow run infrastructure.yml -f environment=dev -f stage=plan
gh workflow run infrastructure.yml -f environment=dev -f stage=apply
gh workflow run deploy.yml -f environment=dev
```

### Staging (`stg`)
```bash
# Same cycle for staging
gh workflow run infrastructure.yml -f environment=stg -f stage=validate
gh workflow run infrastructure.yml -f environment=stg -f stage=plan
gh workflow run infrastructure.yml -f environment=stg -f stage=apply
gh workflow run deploy.yml -f environment=stg
```

**Note:** `stg` environment maps to `stage` directory in Terraform.

### Production (`prd`)
```bash
# Production deployments require GitHub Environment approval
gh workflow run infrastructure.yml -f environment=prd -f stage=validate
gh workflow run infrastructure.yml -f environment=prd -f stage=plan
gh workflow run infrastructure.yml -f environment=prd -f stage=apply
gh workflow run deploy.yml -f environment=prd
```

**Note:** Production requires approval from GitHub Environment `infra-prod` and `deploy-prod` reviewers.

---

## Workflow Details

### Infrastructure Workflow (`infrastructure.yml`)

**Environment mapping:**
- Input `dev` → Terraform workspace `dev`
- Input `stg` → Terraform workspace `stage`
- Input `prd` → Terraform workspace `prod`

**Stage descriptions:**

| Stage | Purpose | AWS Creds | Destructive | Duration |
|-------|---------|-----------|-------------|----------|
| `validate` | Syntax check (offline) | ❌ No | ❌ No | ~30s |
| `plan` | Show changes | ✅ Yes | ❌ No | ~3-5m |
| `apply` | Create resources | ✅ Yes | ✅ Adds | ~10-15m |
| `delete` | Destroy all | ✅ Yes | ✅ Yes | ~5-10m |

**Terraform state:**
- Location: `s3://gdc-smart-terraform-state/smart-inventory-platform/<env>/`
- Locked by: DynamoDB table `smart-terraform-locks`
- Backend: AWS S3 (static config in `infra/terraform/envs/<env>/main.tf`)

### Deploy Workflow (`deploy.yml`)

**Jobs:**

1. **Resolve environment** — Map input to directory name
2. **Build & Push** — Matrix job over 10 services
   - Builds Dockerfile from `backend/services/<service>/Dockerfile`
   - Pushes to ECR: `<account>.dkr.ecr.us-east-1.amazonaws.com/smart-<service>`
   - Tags: `dev-<commit-sha>` and `dev-latest`
3. **Migrate & Roll Out** — Gated by GitHub Environment
   - Runs Alembic migrations via ECS task
   - Updates ECS services (force new deployment)

**Image locations:**
```
877573132642.dkr.ecr.us-east-1.amazonaws.com/smart-api-gateway:dev-<sha>
877573132642.dkr.ecr.us-east-1.amazonaws.com/smart-auth-service:dev-<sha>
... (10 total)
```

---

## Troubleshooting

### Infrastructure Issues

#### Terraform Apply Hangs or Times Out
**Symptom:** RDS provisioning takes > 15 minutes

**Solution:**
- RDS provisioning can take 10-15 minutes — this is normal
- Check AWS console for instance creation progress
- If truly hung, check CloudWatch logs

#### State Lock Conflicts
**Symptom:** `Error acquiring the state lock`

**Solution:**
```bash
# View lock
aws dynamodb get-item --table-name smart-terraform-locks \
  --key '{"LockID": {"S": "gdc-smart-terraform-state/smart-inventory-platform/dev/terraform.tfstate"}}' \
  --profile smart-infra

# Force unlock (⚠️ use with caution)
aws dynamodb delete-item --table-name smart-terraform-locks \
  --key '{"LockID": {"S": "..."}}' --profile smart-infra
```

### Application Deployment Issues

#### Docker Build Fails with "COPY Backend/shared: not found"
**Symptom:** Docker build fails at COPY step

**Solution:** (Already fixed in workflow)
- Ensure Dockerfile is run with correct build context
- Build command: `docker build -f backend/services/<service>/Dockerfile .`

#### ECS Service Won't Update
**Symptom:** Service still showing old task definition

**Solution:**
```bash
# Check service status
aws ecs describe-services --cluster smart-dev --services smart-dev-api-gateway \
  --profile smart-infra --query 'services[0].[status,desiredCount,runningCount,taskDefinition]'

# Check task logs
aws ecs describe-task-definition --task-definition smart-dev-api-gateway:1 \
  --profile smart-infra
```

#### Database Migrations Fail
**Symptom:** Migration task exits with error

**Solution:**
```bash
# View migration task logs
aws logs tail /ecs/smart-dev/migrations --follow --profile smart-infra

# Check RDS connectivity
aws rds describe-db-instances --db-instance-identifier smart-dev \
  --profile smart-infra --query 'DBInstances[0].DBInstanceStatus'
```

### GitHub Actions Issues

#### Workflow Fails at "Configure AWS Credentials"
**Symptom:** `Credentials could not be loaded`

**Solution:**
1. Verify secrets are set:
   ```bash
   gh secret list
   ```
2. Verify secret values are correct (not empty or truncated)
3. Re-set secrets if needed:
   ```bash
   gh secret set AWS_ACCESS_KEY_ID --body "AKIA..."
   gh secret set AWS_SECRET_ACCESS_KEY --body "..."
   ```

#### Workflow Runs Stuck in "Queued"
**Symptom:** Run appears in queue but never starts

**Solution:**
- GitHub has limited concurrent runners
- Wait a few minutes for other runs to complete
- Or use a different runner label (if configured)

---

## Best Practices

### Infrastructure Changes

1. **Always run `validate` first**
   ```bash
   gh workflow run infrastructure.yml -f environment=dev -f stage=validate
   ```

2. **Review the `plan` output carefully**
   - Check for unexpected resource additions/deletions
   - Look for `Destroy` operations — should be rare

3. **Apply during non-critical windows**
   - Apply takes 10-15 minutes
   - Plan for maintenance window

4. **Backup before major changes**
   ```bash
   # RDS automated backups are enabled
   aws rds describe-db-snapshots --db-instance-identifier smart-dev \
     --profile smart-infra
   ```

### Application Deployments

1. **Test in dev first**
   ```bash
   gh workflow run deploy.yml -f environment=dev
   ```

2. **Run CI before deploying**
   ```bash
   gh workflow run ci.yml
   ```

3. **Monitor logs after deploy**
   ```bash
   aws logs tail /ecs/smart-dev/api-gateway --follow --profile smart-infra
   ```

4. **Rollback plan**
   - If deploy fails, re-run with previous commit
   - If services are degraded, scale down and re-deploy

---

## Useful Commands

```bash
# View all workflow runs
gh run list --workflow=infrastructure.yml --limit=10

# View latest run
gh run view --latest --workflow=infrastructure.yml --log | tail -100

# Cancel a stuck run
gh run cancel <run-id>

# Monitor workflow in real-time
watch -n 5 'gh run view <run-id> --json status -q .status'

# Deploy to all environments (dev → stg → prd)
for env in dev stg prd; do
  gh workflow run deploy.yml -f environment=$env
done
```

---

## Support & Questions

For issues or questions:
1. Check CloudWatch logs: `aws logs tail /ecs/smart-<env>/* --follow`
2. Check Terraform logs in GitHub Actions
3. Review AWS console for resource status
4. Consult CLAUDE.md for architecture details

---

**Last Updated:** September 2026
**Maintained by:** SMART Platform Team
