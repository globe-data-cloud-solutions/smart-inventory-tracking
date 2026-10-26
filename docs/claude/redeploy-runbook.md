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

**Stage/prod SA bootstrap: not yet available (P0 item 4); do not run this step.**

**Clean cycle, 2026-10-26 (from scratch, all from `main`, no failures):** apply 10m18s, then deploy ~11m (image builds ~3m, bootstrap/migrate/seed/rollout ~8m), then delete 6m50s. No state-lock problem on the delete this time, and no manual environment approval was needed for `infra-dev` / `deploy-dev`. Dispatching from `main` works, so a feature branch isn't required once merged.
- **Expected deploy warnings:** the rollout step logs `not found or inactive — skipped` for sync, notification, analytics, logistics and order. Dev only enables `api-gateway`, `auth-service`, `tenant-service`, `product-service`, `inventory-service` (`enabled_services` in `envs/dev/main.tf`). Not a failure.
- **Verify without `aws`/`terraform`:** public HTTP is enough: `/` = 200 and the unknown-email login = 401 `INVALID_CREDENTIALS`. After a delete, `https://smart.hplink.io/` gives no connection (curl code 000).
- **Waiting on runs:** `gh run watch` gets killed by the 10-minute tool limit (exit 143) and a leading `sleep` is blocked. Use a foreground poll loop on `gh run view <id> --json status,conclusion` (`sleep 20` between checks, under ~570s per call) and repeat the call until `completed`.
- Before "go", read-only prep is enough: `git rev-list --left-right --count main...<remote>/main` on both remotes, `gh variable list` / `gh secret list -R globe...` (names only), `gh run list` for active runs. The `hplink.io` hosted zone can't be checked without `aws`; the apply's ACM step surfaces it.

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
