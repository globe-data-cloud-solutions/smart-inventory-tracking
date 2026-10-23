# TenantC01–C03 walkthrough scripts

Creates three tenants through the public sign-up wizard and drives them through org setup,
products, stock, transfers (PULL, PUSH, SISTER), approvals, adjustments, a discrepancy and issues.
Results and findings: `docs/e2e/tenantc-walkthrough.md`.

**Local developer machine only.** The client refuses any host other than localhost unless
`E2E_ALLOW_REMOTE=1` is set. Test accounts use the shared password `smart1026`.

## Before you start

1. Migrate a **fresh** database to head and seed permissions:
   `cd backend/migrations && alembic upgrade head`, then `python scripts/seed_permissions.py`.
2. Create the transaction partitions: `python scripts/create_partitions.py --months 3`.
   Without this, every receipt fails (see finding 2 in the walkthrough doc).
3. Start the backend services (`scripts/start_backend.sh` on Windows) with these settings:
   - `ENVIRONMENT=local`, `FEATURE_LOT_TRACKING=true` for the inventory service.
   - `RATE_LIMIT_LOGIN=2000/900` so repeated runs do not hit HTTP 429.
4. Start the frontend: `cd frontend && pnpm dev`.

## Run

Run from this folder (`scripts/e2e`). The modules write `org_<code>.json` and `transfers_<code>.json` here.

```
# 1. Sign up through the wizard (Playwright, headless Chromium)
#    Set E2E_PLAYWRIGHT_MODULE to the playwright package path if it is not resolvable from here.
node signup.cjs .
# 2. Verify the emails from the tenant-service log (dev email mode writes the links there)
E2E_TENANT_LOG=/path/to/tenant-service.log node verify.cjs .
# 3. Everything else, through the API
python run_e2e.py tc01 tc02 tc03
# 4. Optional: check the TA can see the inventory page
node ui_inventory.cjs ./inventory-tc01.png
```

Step 3 writes `e2e_report.json` with every call and its result. It creates data, so run it once per fresh
database. Steps 1–2 create the accounts; do not repeat them without resetting the database, or the
sign-ups will fail with duplicate emails.

## Environment variables

| Name | Default | Purpose |
|---|---|---|
| `E2E_API_BASE` | `http://127.0.0.1:8000/api/v1` | Gateway base URL (localhost only unless `E2E_ALLOW_REMOTE=1`) |
| `E2E_WEB_BASE` | `http://localhost:3000` | Frontend base URL |
| `E2E_PLAYWRIGHT_MODULE` | `playwright` | Path to the Playwright package |
| `E2E_CHROMIUM` | Playwright default | Path to a Chromium binary, if needed |
| `E2E_TENANT_LOG` | `./logs/tenant-service.log` | Log the verification links are written to |
