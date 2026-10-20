# AWS Dev Redeploy Runbook

> Copied from Claude Code memory on 2026-10-18.
> AWS workflows run only on `globe-data-cloud-solutions/smart-inventory-tracking`.
> Never dispatch unless Alex instructs in that session (CLAUDE.md §8).
> No secret values appear below — only secret names/paths, per CLAUDE.md §8.

Dev stack: `smart-dev` cluster, `https://smart.hplink.io`, Terraform in `infra/terraform/envs/dev`. All runs go to `globe-data-cloud-solutions/smart-inventory-tracking` (see [[project-pipelines-run-from-globe]]).

**Reprovision, in order** (each step waits for the previous to succeed):
1. Push the branch to both remotes (see [[project-dual-remote]]).
2. Infrastructure apply, from the branch:
   `gh workflow run infrastructure.yml -R globe-data-cloud-solutions/smart-inventory-tracking --ref <branch> -f environment=dev -f stage=apply`
   Needs repo variable `DEV_ALLOWED_CIDRS` (set to `[]` for open access) and the AWS secrets in the globe repo.
3. Deploy, from the branch, normal (no rotation):
   `gh workflow run deploy.yml -R globe-data-cloud-solutions/smart-inventory-tracking --ref <branch> -f environment=dev`
   The deploy runs db-bootstrap, then migrations, then the dev seed, then rolls out the services.
4. Check: all `smart-dev` services at running = desired; `https://smart.hplink.io/` returns 200. Probe login with an unknown email at `POST /api/v1/auth/token` and expect 401 `INVALID_CREDENTIALS`.

**Teardown:** `gh workflow run infrastructure.yml ... -f stage=delete`. It drains ECS services, deletes the ECR repos, then runs `terraform destroy`. The dev RDS and secrets are destroyed too (dev has no final snapshot, and secrets have no recovery window).

**Teardown gotchas (2026-10-17):** the first destroy stopped partway (`Terraform Destroy` with no result), leaving the state half-destroyed. A re-run then failed with `Error acquiring the state lock`. The lock was held by the stopped run's runner, with no active runs. Fix: check no run is active (`gh run list -R globe-data-cloud-solutions/smart-inventory-tracking`), then `terraform force-unlock -force <lock-id>` using the ID the lock error prints. Then re-dispatch `stage=delete`. Verify afterwards: `terraform state list` is empty, no `smart-dev` cluster/RDS/CloudFront, no `smart/dev` secrets, no `smart-*` ECR repos.

**Lifecycle workflow:** `lifecycle.yml` runs apply then deploy (or destroy) in one dispatch, but GitHub only dispatches workflows on the default branch, so merge it to `main` first.

**SA rotation:** bump `seed_sa_rotation` in `envs/dev/main.tf`, apply, then deploy with `-f rotate_seed_sa=true`. That deletes and re-creates the SA account from the new secret. Run it without the flag afterwards. The seed is first-creation-only otherwise.

**SA password:** read `smart/dev/seed/sa-password` in your own terminal. Never paste it into a chat.

**stage/prod SA bootstrap (no dev seed there):** `seed_enabled` is `false` in stage and prod (CLAUDE.md §8, 2026-10-17 decision), so `seed_dev_sample.py` never runs there and a fresh RDS has no SA account at all — nothing else creates one. `backend/migrations/bootstrap_sa_account.py` fills that gap: it creates **only** the SA user row (no tenants, no sample data), reading the SA email and password from Secrets Manager at runtime via `boto3`, using secret *names* passed in — never the values themselves, and never printed or logged. Run it as a one-off override of the existing migration task, after migrations have applied:

```
aws ecs run-task \
  --cluster smart-<env> \
  --task-definition smart-<env>-migrate \
  --overrides '{"containerOverrides": [{
    "name": "migrate",
    "command": ["python", "/app/backend/migrations/bootstrap_sa_account.py",
                 "--email-secret-name", "smart/<env>/sa/email",
                 "--password-secret-name", "smart/<env>/sa/password"]
  }]}'
```

Idempotent: it checks whether a user with that email already exists before writing anything, and never overwrites an existing SA's password — safe to re-run on every redeploy, same first-creation-only spirit as the dev seed. It does **not** need its own ECS service or task definition — it reuses the migration image/task definition that already exists, only overriding the container command.

**Terraform this would need (not added by this change):** the migration task's execution/task role needs `secretsmanager:GetSecretValue` on the two new SA secret ARNs (`smart/<env>/sa/email`, `smart/<env>/sa/password`), and those two secrets themselves need to exist in `infra/terraform/modules/app-secrets` for stage/prod. Neither was added here.

**Failure modes hit and their fixes:**
- Private subnets had no route to the NAT: networking module needed route tables.
- ECS secrets given as bare names resolved as SSM: use full Secrets Manager ARNs (`app-secrets` outputs).
- Runtime DB role needed `CREATE` on the database for `pg_trgm`, and the bootstrap must not `ALTER` SUPERUSER/BYPASSRLS on the RDS master (not a superuser).
- `aws_vpc_security_group_ingress_rule` conflicts with inline rules, and `ingress = []` makes the SG own every rule. Leave `ingress` unset on RDS/Redis SGs.
- `rediss://` URLs need `ssl_cert_reqs`, and the spelling differs by client: redis-py takes `required`, Celery takes `CERT_REQUIRED`.
- asyncpg rejects `?ssl=` inside a DSN: pass `ssl="require"` as a keyword.
- The migration image needs `bcrypt` installed in its own `RUN` line (the shared package doesn't depend on it).
- `package_prices` ids differ between databases: the seed resolves subscription prices by tier, billing period and currency.
- Dev fixture is exported from the local DB with `scripts/export_dev_sample_fixture.py` (read-only). It excludes transactional history and password hashes.
