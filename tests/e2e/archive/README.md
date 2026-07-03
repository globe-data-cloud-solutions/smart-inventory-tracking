# Archived E2E Tests

## test_tenant07_e2e.py

**Status: RETIRED — do not run.**

Tenant07 (T07) was retired as the primary E2E test tenant because its data became
stateful and corrupted across many mutation sessions, making test results unreliable.

**Superseded by:** `tests/e2e/test_t6p2t_group_a.py` through `_e.py`

T6P2T (Tenant 6 Purpose-to-Test) is the current authoritative E2E suite. Its Groups
10–19 map directly to former T07 groups and extend coverage T07 never had: controlled
products, cross-tenant isolation, security, and i18n.

## test_tenant07_report.txt

Stale partial run report from T07's last execution. Only 11 of 20 groups completed.
Kept alongside the test file for historical reference.

---

*Files archived: 2026-07-03. Do not restore these files to the active test directory.*
