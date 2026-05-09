## Summary

<!-- What does this PR do? Why? -->

## Checklist

### Permissions
- [ ] New routes have `@require_permission` applied
- [ ] New actions added to `backend/shared/permissions/registry.py`
- [ ] CI permission drift check passes (`python scripts/ci_drift_check.py`)

### Database
- [ ] Alembic migration created with descriptive name
- [ ] Tested: `alembic upgrade head → downgrade -1 → upgrade head`
- [ ] All new tables have `tenant_id` as leading index column
- [ ] RLS policy added for every new tenant-scoped table

### Outbox
- [ ] State-changing services write to outbox in the **SAME** DB transaction
- [ ] Celery task handlers are idempotent (check status before processing)

### Inventory integrity
- [ ] No direct `UPDATE inventory_balances` — ledger `INSERT` only
- [ ] Idempotency key used for every new transaction type

### Frontend
- [ ] TypeScript strict — no `any` introduced
- [ ] Tailwind only — no `style=` inline attributes
- [ ] All UI strings use `t()` i18n keys — no hardcoded English text in JSX

### Testing
- [ ] 15 permission test cases for any new action
- [ ] Outbox pattern tests updated if new event types added

### CI
- [ ] All CI jobs green (lint, typecheck, test, drift-check, migration round-trip, locale-check)
