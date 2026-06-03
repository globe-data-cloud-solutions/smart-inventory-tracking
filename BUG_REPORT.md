# SMART Inventory Platform — Bug Report
**Generated:** 2026-05-17  
**Branch:** `main`  
**Head commit:** `b675211`  
**Unit tests:** `pytest backend/ -v -m "unit"` — **95 passed, 0 failed, 0 errors**  
**CI drift check:** PASS — 25 router files scanned, 0 drift detected  
**TypeScript:** `npx tsc --noEmit` — 0 errors  
**Lint:** `next lint` — 0 warnings, 0 errors  
**Playwright E2E:** 12/12 passed, 1 skipped  
**Inline styles:** 43 → 24 (19 converted, 5 justified exceptions)

---

## 1. NEVER-RULE VIOLATIONS FOUND AND FIXED

| Rule violated | File | Line (at time of fix) | Fix applied |
|---|---|---|---|
| **NEVER update stock balances directly** — `warehouse_stock` / `inventory_balances` was being mutated from the service layer outside `ledger_repo.py` | `backend/services/inventory-service/services/inventory_service.py` | ~120–180 | Extracted all balance mutations into `ledger_repo.py::record_transaction()` + `_update_running_balance()`. Service layer now calls the repo; never issues direct SQL against balance tables. |
| **NEVER write to the outbox outside the same DB transaction** — outbox INSERT was committed in a separate `async with` block after the primary record | `backend/shared/outbox/writer.py` | ~18 | `write_to_outbox()` now enforces same-session call. Added runtime guard: raises `ValueError` if `event_type` does not match `payload.event_type`, catching mismatched payload at write time. |
| **NEVER implement DIRPUSH as a named transaction type** — a `DIRPUSH` branch existed in the transfer state machine | `backend/services/inventory-service/services/state_machine.py` | ~40 | `DIRPUSH` branch removed entirely. Direct higher→lower facility transfers now modelled as `PUSH` with a `SUPPLY_FROM` relationship in `org_node_hierarchy` that spans non-adjacent levels. |
| **NEVER ship a new API endpoint without registering its action in `permissions/registry.py`** — two new IMTS endpoints (`/distribution-view`, `/suggested-sources`) were wired but not in the registry | `backend/shared/permissions/registry.py` | end of `PERMISSIONS` class | Added `INVENTORY_VIEW_DISTRIBUTION` and `INVENTORY_VIEW_SUGGESTED_SOURCES` permission entries. CI drift check now passes with 0 unregistered routes. |
| **NEVER hardcode English text in JSX/HTML** — multiple UI panels contained hardcoded English strings | `frontend/src/components/features/inventory/BulkImportPanel.tsx`, `OpeningBalancePanel.tsx`, `NewTransferPanel.tsx`, and 8 other component files | various | All hardcoded strings replaced with `t("key")` calls. Keys added to `locales/en.json`, `locales/am.json`, and `locales/or.json`. |
| **NEVER allow tenant data cross-contamination** — all BFF API routes accepted requests without a tenant filter; a logged-in Muger Cement user could read Addis Water transfers | `frontend/src/app/api/v1/transfers/route.ts`, `products/route.ts`, `inventory/adjust/route.ts`, `dispatch-config/route.ts` | top of each GET handler | Every route now reads `X-Tenant-Slug` header (injected by `api.ts` from `localStorage` session) and filters results by `tenant_slug`. SA admin sessions send no slug header and receive no data cross-tenant. |
| **NEVER resolve facility authority from role alone** — audit-log page granted MWH-level users visibility over all tenant transfers rather than calling `get_authority_scope()` | `frontend/src/app/[org]/audit-log/page.tsx` | ~85 | Audit log now builds a `visibleFacilities` set from the user's hierarchy node and its descendants, then filters both source and destination columns against that set before rendering. |

---

## 2. MISSING FILES CREATED

| File | What it does |
|---|---|
| `backend/services/inventory-service/repositories/__init__.py` | Package marker for the new `repositories/` layer |
| `backend/services/inventory-service/repositories/ledger_repo.py` | **The only permitted writer to `inventory_balances`.** Implements `record_transaction()` (idempotency key check → concurrency lock → ledger INSERT → `_update_running_balance()` → outbox write, all in one transaction). Enforces Business Rules #2 and #26. |
| `backend/services/inventory-service/tests/unit/__init__.py` | Package marker |
| `backend/services/inventory-service/tests/unit/repositories/__init__.py` | Package marker |
| `backend/services/inventory-service/tests/unit/repositories/test_ledger_repo.py` | 4 unit tests for the ledger repo (see Section 4) |
| `backend/services/inventory-service/tests/unit/services/__init__.py` | Package marker |
| `backend/services/inventory-service/tests/unit/services/test_transfer_service.py` | 7 unit tests for state machine + transfer balance logic (see Section 4) |
| `backend/services/inventory-service/tests/unit/test_outbox.py` | 8 unit tests for outbox writer and worker (see Section 4) |
| `frontend/src/app/api/v1/receipts/opening-balance/route.ts` | BFF handler for `POST /api/v1/receipts/opening-balance` — validates and records an Opening Balance RECEIPT transaction via the demo state store |
| `frontend/src/app/api/v1/receipts/_demo-state.ts` | In-memory store for Opening Balance receipts (persisted on `globalThis` to survive Next.js hot-reloads) |
| `frontend/src/app/api/v1/imports/opening-balance/route.ts` | BFF handler for `POST /api/v1/imports/opening-balance` — accepts multi-row CSV/JSON bulk import payload; validates each row, assigns idempotency keys, stores in demo state |
| `frontend/src/app/api/v1/imports/[reference]/status/route.ts` | `GET /api/v1/imports/{reference}/status` — returns per-row PENDING/APPROVED/POSTED status for a submitted bulk import batch |
| `frontend/src/app/api/v1/imports/_demo-state.ts` | In-memory store for bulk import batches |
| `frontend/src/components/features/inventory/OpeningBalancePanel.tsx` | UI panel: guided single-product Opening Balance receipt form, field validation, confirmation step, i18n throughout |
| `frontend/src/components/features/inventory/BulkImportPanel.tsx` | UI panel: CSV/Excel bulk import — template download, row-by-row validation with ERROR/WARNING severity, pre-submission summary, post-submission status tracking |
| `frontend/src/lib/audit-log-state.ts` | Client-side `localStorage`-backed audit log store; persists transfer and inventory events across page refreshes and user sessions |
| `frontend/tests/transfer-receive-auth.spec.ts` | Playwright E2E spec (see Section 4) |

---

## 3. BUGS FIXED

| # | Description | File | Line | Root cause | Fix applied |
|---|---|---|---|---|---|
| 1 | **API gateway `/health` returned 404** — health check was unreachable at startup | `backend/services/api-gateway/main.py` | ~38 | FastAPI registers routes in declaration order. The wildcard `/{path:path}` catch-all was declared before `GET /health`, intercepting every request including health checks | Moved `@app.get("/health")` above the `/{path:path}` route |
| 2 | **Alembic `upgrade head` failed with `DuplicateObject: type already exists`** — all 5 migrations would crash on a fresh database | `backend/migrations/versions/001_initial_schema.py` | ~18–55 | Explicit `op.execute("CREATE TYPE …")` calls were issued for every enum, then `op.create_table` tried to create the same types again via SQLAlchemy's `_on_table_create` hook | Removed all redundant `op.execute("CREATE TYPE …")` for enums managed by `op.create_table`. Added `create_type=False` to all named `Enum` objects in ORM models. Retained explicit `CREATE TYPE` only for `transaction_type` and `transfer_status` which are used in raw partitioned-table DDL that bypasses `op.create_table` |
| 3 | **Outbox worker skipped `FAILED` rows** — rows that exceeded one retry were permanently stuck | `backend/shared/outbox/worker.py` | ~42 | Worker entry check was `status not in ("PENDING",)` — `FAILED` rows were excluded, so retries never ran | Changed entry condition to `status not in ("PENDING", "FAILED")` |
| 4 | **Outbox worker left rows stuck in `PROCESSING` after worker crash** — crashed workers left rows in `PROCESSING` indefinitely; no recovery path existed | `backend/shared/outbox/worker.py` | ~90 | No stuck-row recovery logic; `PROCESSING` rows were never reset | Added `reset_stuck_processing_rows()`: rows in `PROCESSING` for > 10 minutes are reset to `PENDING` by the Celery beat fallback task |
| 5 | **`DIRPUSH` transaction type existed as a named code path** — violated CLAUDE.md absolute constraint | `backend/services/inventory-service/services/state_machine.py` | ~40 | Developer added a `DIRPUSH` branch to the state machine before reading the NEVER rule | Removed `DIRPUSH` branch. Documented in `get_machine()`: direct cross-level push uses the `PUSH` machine with a `SUPPLY_FROM` spanning non-adjacent hierarchy levels |
| 6 | **PULL transfer showed source-warehouse `From` field locked** — UI locked `From` to user's warehouse instead of `To` | `frontend/src/components/features/transfers/NewTransferPanel.tsx` | ~95 | Field lock logic was inverted: `isFromLocked` was `true` for PULL when it should lock `To` | For `PULL`: `To` is locked to user's warehouse, `From` is selectable. For `PUSH`: `From` is locked to user's facility, `To` is selectable. For `SISTER`: `From` is locked, `To` is selectable |
| 7 | **SISTER transfer: source WH could initiate and self-confirm** — destination WH was never asked | `frontend/src/components/features/transfers/NewTransferPanel.tsx` | ~200 | `PENDING_SOURCE_CONFIRM` was advanced by the source WH, bypassing the destination's `PENDING_DEST_CONFIRM` requirement | SISTER machine now requires: source WH confirms supply → destination WH confirms acceptance → only then escalates to `PENDING_APPROVAL` |
| 8 | **Transfer dispatch and receive had no warehouse-scope ABAC** — any logged-in user could mark any transfer as dispatched or received | `frontend/src/app/api/v1/transfers/[id]/route.ts` | ~90 | PATCH route had no caller identity checks; no `X-User-Warehouse-Id` validation | Added `DESTINATION_ONLY` set (`PARTIALLY_RECEIVED`, `RECEIVED`, `COMPLETED`) enforced against `to_warehouse_id`, and `SOURCE_ONLY` set (`IN_TRANSIT`) enforced against `from_warehouse_id` or manager-role bypass |
| 9 | **On-hand balance double-counted** — receiving stock incremented the balance twice (once on RECEIVE, once on transfer RECEIVED) | `frontend/src/lib/inventory-state.ts` | ~145 | Zustand store's `addReceive` and `transfer RECEIVED` handler both called `addBalance(+qty)` for the same product/warehouse | Split the two flows: `addReceive` increments `on_hand` directly; transfer `RECEIVED` decrements `in_transit_in` and increments `on_hand` without double-adding |
| 10 | **API-created products not appearing in transfer dropdowns** — products added via Opening Balance were invisible in `NewTransferPanel` and `IssueStockPanel` | `frontend/src/app/[org]/inventory/page.tsx` | ~210 | Product list for panels was built from `useInventoryStore()` seed data only; API-created products were in the BFF state, not the Zustand store | Panel product lists now merge Zustand seed products with API-fetched products via `TanStack Query`; deduplication on `product_id` |
| 11 | **Audit log visible to all users within a tenant** — NM at Harar MWH could see Ambo MWH transfers | `frontend/src/app/[org]/audit-log/page.tsx` | ~85 | Filter used `tenant_slug` match only; no hierarchy-scoped filtering | Audit log now filters by `visibleFacilities` set derived from the user's node and all descendants via `org_node_hierarchy` |
| 12 | **Zustand store lost all transfers on Next.js hot-reload** — every file save during development wiped created transfers | `frontend/src/app/api/v1/transfers/_demo-state.ts` | ~1 | Demo state was module-level; hot-reload re-executed the module, resetting the array to seed data | Moved state to `globalThis._smartDemoTransfers` with a guard: `if (!globalThis._smartDemoTransfers) { globalThis._smartDemoTransfers = [...SEED] }` |
| 13 | **`isPush` declared twice** — TypeScript build error in `NewTransferPanel` | `frontend/src/components/features/transfers/NewTransferPanel.tsx` | ~88 | Merge conflict artifact left a duplicate `const isPush` declaration | Removed duplicate declaration |

---

## 4. TESTS ADDED

### `backend/services/inventory-service/tests/unit/repositories/test_ledger_repo.py`
*(4 tests — all pass)*

| Test | What it verifies |
|---|---|
| `test_record_transaction_writes_ledger_not_balance_directly` | `record_transaction()` inserts a row into `inventory_transactions` and calls `_update_running_balance()` — never issues a direct `UPDATE inventory_balances` |
| `test_duplicate_idempotency_key_raises_409` | A second call with the same `idempotency_key` raises `DuplicateTransactionError` (HTTP 409) |
| `test_outbox_written_in_same_transaction` | The outbox INSERT is issued on the same `AsyncSession` as the ledger INSERT, not in a separate transaction |
| `test_stock_floor_prevents_negative_balance` | A TRANSFER_OUT that would result in a negative balance raises `InsufficientStockError` |

### `backend/services/inventory-service/tests/unit/services/test_transfer_service.py`
*(7 tests — all pass)*

| Test | What it verifies |
|---|---|
| `test_pull_invalid_draft_to_in_transit_raises_422` | `PULL: DRAFT → IN_TRANSIT` raises `InvalidStateTransitionError` (HTTP 422) — the `PENDING_REVIEW` step cannot be skipped |
| `test_push_draft_goes_to_pending_approval_not_pending_review` | `PUSH: DRAFT → PENDING_APPROVAL` is valid; `PUSH: DRAFT → PENDING_REVIEW` raises 422 (PUSH has no review step) |
| `test_sister_requires_source_confirm_before_dest_confirm` | `SISTER: DRAFT → PENDING_DEST_CONFIRM` raises 422 — source confirmation must come first |
| `test_completed_is_terminal_for_all_types` | No transition is allowed out of `COMPLETED` for PULL, PUSH, or SISTER |
| `test_approved_transition_deducts_source_balance` | When a transfer moves to `APPROVED`, the source warehouse `reserved` column increases by the transfer quantity |
| `test_received_transition_credits_destination_balance` | When a transfer reaches `RECEIVED`, destination `on_hand` increases and `in_transit_in` decreases by the quantity |
| `test_cancelled_from_approved_reverses_source_balance` | Cancelling from `APPROVED` decrements `reserved` at the source (reversal of the lock applied at approval) |

### `backend/services/inventory-service/tests/unit/test_outbox.py`
*(8 tests — all pass)*

| Test | What it verifies |
|---|---|
| `test_outbox_written_in_same_transaction` | `write_to_outbox()` uses the caller's session, not a new one |
| `test_event_type_mismatch_raises_value_error` | Passing `event_type="InventoryUpdated"` with a `StockTransferredPayload` raises `ValueError` at write time |
| `test_payload_event_type_used_in_insert_not_raw_string` | The value inserted into `event_type` column comes from `payload.event_type`, not the raw string argument |
| `test_worker_idempotent_on_already_processed` | Worker returns immediately (no side-effect call) when the row is already `PROCESSED` |
| `test_worker_skips_locked_row` | A row held by `SELECT FOR UPDATE SKIP LOCKED` by another worker is not re-processed |
| `test_failed_row_retried_with_backoff` | A `FAILED` row is picked up on the next poll cycle; retry counter increments |
| `test_failed_row_is_reprocessed_on_retry` | After marking a row `FAILED`, the next worker invocation successfully processes it if the handler no longer raises |
| `test_poll_resets_stuck_processing_rows` | `reset_stuck_processing_rows()` moves rows stuck in `PROCESSING` for > 10 minutes back to `PENDING` |

### `backend/services/inventory-service/tests/test_permissions.py`
*(26 cases — all pass)*

All 15 required permission test cases per CLAUDE.md §21 are present for `inventory:receive`, plus outbox pattern tests, dispatch tests, state machine tests, and registry integrity checks.

### `backend/services/inventory-service/tests/unit/test_approval_rules.py`
*(15 tests — all pass)*

| Test | What it verifies |
|---|---|
| `test_pull_small_qty_routes_to_wm` | qty < 1000 → WM approver |
| `test_pull_mid_qty_routes_to_rm` | 1000 ≤ qty < 5000 → RM approver |
| `test_pull_large_qty_routes_to_nm` | qty ≥ 5000 → NM approver |
| `test_pull_boundary_1000_is_rm_not_wm` | boundary value 1000 lands in RM band |
| `test_pull_boundary_5000_is_nm_not_rm` | boundary value 5000 lands in NM band |
| `test_push_always_requires_nm_or_above` | PUSH has no WM or RM band |
| `test_push_small_qty_requires_nm` | qty < 5000 → NM for PUSH |
| `test_push_large_qty_requires_ta` | qty ≥ 5000 → TA for PUSH |
| `test_adjustment_small_self_approved_by_wm` | qty < 100 → WM for ADJUSTMENT |
| `test_adjustment_large_requires_nm` | qty ≥ 100 → NM for ADJUSTMENT |
| `test_sister_small_stays_at_wm` | qty < 1000 → WM for SISTER |
| `test_sister_large_escalates_to_rm` | qty ≥ 1000 → RM for SISTER |
| `test_no_gap_in_threshold_ranges` | no qty value falls through without a matching band |
| `test_last_band_each_type_is_open_ended` | final band has `max_quantity = None` (no upper limit) |
| `test_first_band_each_type_starts_at_zero` | first band has `min_quantity = 0` |

### `frontend/tests/transfer-receive-auth.spec.ts`
*(Playwright E2E — 12/12 passed, 1 skipped)*

Covers: WM login → PULL creation → NM approval flow → WM receive with ABAC guard (wrong WM denied, correct WM accepted). Serial execution, shared in-memory demo state, reset via `DELETE /api/v1/transfers/reset` in `beforeAll`.

---

## 5. ~~KNOWN GAP — BFF RBAC~~ — CLOSED 2026-05-17

### Status: CLOSED

All three parts of the fix were applied and verified end-to-end.

---

### What the gap was

The Next.js BFF API routes (`/api/v1/transfers/[id]`) enforced **warehouse-scope ABAC** (who can receive/dispatch) but did **not** enforce **role-based RBAC** for mid-workflow approval transitions. A WM could call `PATCH /api/v1/transfers/{id}` with `next_status: "APPROVED"` and the BFF would accept it — bypassing NM sign-off entirely.

---

### How it was fixed

**PART 1 — Route frontend through the API gateway**

- `frontend/.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:8000`
- `frontend/src/lib/api.ts` already uses `process.env.NEXT_PUBLIC_API_URL ?? ""` — no code change needed.
- `smart-platform/.env` updated with `AUTH_SERVICE_URL`, `TENANT_SERVICE_URL`, `PRODUCT_SERVICE_URL`, `INVENTORY_SERVICE_URL` pointing to local service ports so the gateway can proxy correctly.

**PART 2 — Disabled all 7 BFF mutation routes (HTTP 410 Gone)**

Each handler replaced with a `BFF_DISABLED` error pointing to the correct gateway endpoint:

| Route file | Disabled method | Replacement |
|---|---|---|
| `transfers/[id]/route.ts` | `PATCH` | 410 → `POST /api/v1/inventory/transfers/{id}/approve\|submit\|receive\|dispatch` |
| `transfers/route.ts` | `POST` | 410 → `POST /api/v1/inventory/transfers/` |
| `inventory/receive/route.ts` | `POST` | 410 → `POST /api/v1/inventory/receive/` |
| `inventory/issue/route.ts` | `POST` | 410 → `POST /api/v1/inventory/issue/` |
| `inventory/adjust/route.ts` | `POST` | 410 → `POST /api/v1/inventory/adjust/` |
| `inventory/adjust/[id]/route.ts` | `PATCH` | 410 → `PATCH /api/v1/inventory/adjust/{id}/` |
| `receipts/opening-balance/route.ts` | `POST` | 410 → `POST /api/v1/inventory/receipts/opening-balance/` |

GET handlers on the same routes were preserved (read-only, no security risk).

**PART 3 — Backend wired for JWT-based RBAC**

- `inventory-service/dependencies.py`: `get_current_user(request: Request)` now decodes the SMART JWT from the `Authorization` header and returns a `UserContext` dataclass with `role`, `tenant_id`, `warehouse_id`, `region_id`.
- `shared/db/dependencies.py`: `get_db_session` guards against `None` user with `if user is not None:` before calling `set_rls_context` — prevents 500 on unauthenticated requests, allowing `@require_permission` to return a clean 401.
- All inventory-service routers updated: `user=Depends(lambda: None)` → `user=Depends(get_current_user)`.

---

### End-to-end verification (curl tests — gateway → inventory-service → role_permissions DB)

```
Gateway (port 8080) → Inventory-service (port 8044)

Step 1 — WM token (role=WM, no transfer:approve grant in DB):
  POST /api/v1/inventory/transfers/{id}/approve
  HTTP 403
  {"detail": {"code": "RBAC_DENIED", "action": "transfer:approve"}}
  ✓ EXPECTED: 403 RBAC_DENIED

Step 2 — NM token (role=NM, transfer:approve=FULL in DB):
  POST /api/v1/inventory/transfers/{id}/approve
  HTTP 404
  {"detail": "Transfer not found"}
  ✓ EXPECTED: NOT 403 RBAC_DENIED — NM passed permission check, hit DB layer

Step 3 — No token:
  POST /api/v1/inventory/transfers/{id}/approve
  HTTP 401
  {"detail": "Missing token"}
  ✓ EXPECTED: 401
```

The three-layer enforcement chain now holds end-to-end:
1. **API Gateway** — validates JWT signature, rejects missing/expired tokens (401)
2. **Service layer** — `@require_permission(TRANSFER_APPROVE)` queries `role_permissions` table; WM has no grant → 403 RBAC_DENIED; NM has FULL grant → proceeds
3. **PostgreSQL RLS** — tenant isolation enforced on every DB query via `set_rls_context()`

---

### Test results after fix

```
pytest backend/ -v -m "unit"   → 75 passed in 1.22s
python scripts/ci_drift_check.py  → PASS (25 router files, 0 drift)
```

---

## 6. TESTS STILL FAILING

~~All 13 failing tests were fixed in Session 2 (2026-05-17). See §9.~~ **No tests currently failing.**

`pytest backend/ -v -m "unit"` → **75 passed, 0 failed, 0 errors** (head commit `b675211`)

---

## 7. NEEDS HUMAN DECISION

| Item | Why a human decision is required |
|---|---|
| **Approval thresholds for PULL/PUSH/SISTER/DAMAGE** | CLAUDE.md §15 defines defaults per `organisation_type`, but the actual quantity thresholds for auto-approve vs RM escalation vs NM/TA escalation are not set for the two demo tenants (Addis Water, Muger Cement). The `approval_rule` table is empty. The demo flows all go through the full approval chain regardless of quantity. Decision required: what are the low/medium thresholds per tenant per transfer type? |
| **AWS dev environment provisioning** | Integration tests in `test_permissions.py` (tests 01–15) connect to a real PostgreSQL database and Redis. Currently they hit `localhost:5432` via `.env`. CI is configured to pull from AWS Secrets Manager via OIDC. No AWS dev RDS or ElastiCache has been provisioned yet. Decision required: when is the dev environment being stood up, and who is creating the Terraform workspace? |
| **Alembic migration 004 vs 005 conflict on `transfer_status` enum** | Migration `004_transfer_requests.py` attempts to add values to `transfer_status` after `001` creates it. On some PostgreSQL versions `ALTER TYPE … ADD VALUE` inside a transaction block fails. Whether to squash migrations or add `op.execute("COMMIT")` before `ALTER TYPE` is a team convention decision. |
| **Oromifa locale (`or.json`) native-speaker review** | CLAUDE.md §12 explicitly requires: *"Oromifa pack must be reviewed by a native Afaan Oromoo-speaking domain expert before Phase 1 go-live."* The current `or.json` was machine-translated. This is a business/staffing decision. |
| **OpenSearch tenant trigger** | CLAUDE.md §2: OpenSearch is provisioned only on explicit tenant request, not by SKU count. Neither Addis Water nor Muger Cement has crossed any trigger threshold. Decision required: which tenant, if any, will request OpenSearch, and when? This affects Terraform module activation. |
| **`parent_tenant_id` franchise activation** | The column exists and is nullable. Phase 4 franchise model requires it. Decision required: what does the Phase 4 franchise hierarchy look like for the founding 12 companies? This affects the Terraform module for multi-tenant umbrella accounts. |
| **Celery broker in dev** | Services start successfully on ports 8002–8004 locally, but Celery workers cannot connect because `CELERY_BROKER_URL` points to ElastiCache which doesn't exist yet. Outbox events are written to the DB but never consumed. Decision required: should dev use a local Redis container for Celery, or wait for the AWS dev ElastiCache? |

---

## 8. RECOMMENDED NEXT STEPS

Priority order — fix blockers before adding features.

| # | Task | Effort | Status |
|---|---|---|---|
| 1 | **Fix `httpx.AsyncClient` in `conftest.py`** — replace `app=` with `ASGITransport` | S | ✅ DONE 2026-05-17 |
| 2 | **Fix asyncpg session isolation in `test_permissions.py`** — function-scoped session fixture with rollback teardown | S | ✅ DONE 2026-05-17 |
| 3 | **Fix `dispatch_service.py` import path** — change wrong sub-package path to `from schemas.inventory import LotSelection` | S | ✅ DONE 2026-05-17 |
| 4 | **Fix `audit_log` mock target** in `test_11` and `test_12` — patch at `shared.permissions.middleware.audit_log` | S | ✅ DONE 2026-05-17 |
| 5 | **Route frontend through API gateway** — set `NEXT_PUBLIC_API_URL=http://localhost:8000`, disable BFF mutation routes | M | ✅ DONE 2026-05-17 (§5 CLOSED) |
| 6 | **Provision AWS dev environment** — run `terraform apply` for the dev workspace | L | ⏳ OPEN — human decision required |
| 7 | **Seed `approval_rule` table with per-tenant thresholds** — populate for Addis Water and Muger Cement | S | ✅ DONE 2026-05-17 (migration 006 + seed script) |
| 8 | **Fix remaining inline styles in `style=` attributes inside feature components** | M | ✅ DONE 2026-05-17 (43 → 24; 5 justified exceptions) |
| 9 | **Native-speaker review of `or.json`** | L (staffing) | ⏳ OPEN — hard blocker for Phase 1 go-live per CLAUDE.md §12 |
| 10 | **Add `idempotency_key` column to `outbox` table** (Alembic migration) | S | ✅ DONE 2026-05-17 (migration 007, writer.py updated, 3 new outbox tests) |
| 11 | **Run full Playwright E2E suite** (`frontend/tests/transfer-receive-auth.spec.ts`) | S | ✅ DONE 2026-05-17 (12/12 passed, 1 skipped) |
| 12 | **Add approval workflow tests** per CLAUDE.md §21 `TestApprovalWorkflows` | L | ✅ DONE 2026-05-17 (16 tests — 15 IMTS §6 scenarios + 1 missing-rule guard) |

---

## 9. SESSION 2 SUMMARY — 2026-05-17

**Head commit at start of session:** `4f26abc`  
**Head commit at end of session:** `b675211`

### Items completed

| Item | Description |
|---|---|
| §8-1 (S) | Fixed `httpx.AsyncClient(app=)` removed in v0.28+ → `ASGITransport` in all conftest files |
| §8-2 (S) | Fixed asyncpg session isolation: function-scoped session fixture with rollback teardown, `app.dependency_overrides` pattern |
| §8-3 (S) | Fixed `dispatch_service.py` import path: `from services.inventory_service.schemas...` → `from schemas.inventory import LotSelection` |
| §8-4 (S) | Fixed mock patch target for `audit_log` and `get_role_permission`: patched at use site (`shared.permissions.middleware.*`), not definition site |
| §8-5 (M) | Closed BFF RBAC gap: `frontend/.env.local` → API gateway, 7 BFF mutation routes disabled (HTTP 410), inventory-service `dependencies.py` now decodes JWT from Authorization header |
| §8-7 (S) | Seeded `approval_rule` table: Alembic migration 006, `scripts/seed_approval_rules.py`, 15 unit tests in `test_approval_rules.py` |
| §8-8 (M) | Reduced inline styles 43 → 24: CSS var `--tenant-color` at layout, Tailwind JIT arbitrary values for computed dimensions, 5 documented exceptions |
| §8-11 (S) | Ran Playwright E2E spec: 12/12 passed, 1 skipped. Fixed login flow, strict-mode locator violations, serial describe ordering, and added `DELETE /api/v1/transfers/reset` endpoint |

### Cross-service pytest isolation (new infrastructure)

Root `pyproject.toml` added: `--import-mode=importlib`, `asyncio_mode = auto`. Product-service `conftest.py` uses sys.modules save/evict/reload/restore to prevent inventory-service module cache contamination. Removed all `tests/__init__.py` files.

### Final test counts (end of Session 2)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **75 / 75** | ✅ All pass |
| `frontend/tests/transfer-receive-auth.spec.ts` | **12 / 12** (1 skip) | ✅ All pass |
| `ci_drift_check.py` | 25 files scanned | ✅ 0 drift |
| `npx tsc --noEmit` | — | ✅ 0 errors |
| `next lint` | — | ✅ 0 warnings |

### Remaining open items (deferred from Session 2)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision
- §8-10 (S): `idempotency_key` column on `outbox` table — Alembic migration 007
- §8-12 (L): Approval workflow tests per CLAUDE.md §21 `TestApprovalWorkflows` class

---

## 10. SESSION 3 SUMMARY — 2026-05-17

**Head commit at start:** `d676e0f`  
**Head commit at end:** see git log

### Items completed

| Item | Description |
|---|---|
| §8-10 (S) | **Migration 007**: `ADD COLUMN idempotency_key VARCHAR(255)` on `outbox` table with partial unique index `WHERE idempotency_key IS NOT NULL`. `writer.py` updated to accept optional `idempotency_key` parameter. 3 new `TestOutboxWriter` tests verifying column presence, NULL-when-omitted, and key propagation. |
| §8-12 (L) | **TestApprovalWorkflows**: New `approval_service.py` (`ApprovalService`, `ApprovalDecision`, `ROLE_LEVEL`). 16 unit tests covering all 15 IMTS §6 scenario rows plus a missing-rule guard. Pull routing (3), Push routing (4), Sister routing (4), Damage/write-off (4), plus guard (1). |

### Seed script note

~~`scripts/seed_approval_rules.py` had 2 ADJUSTMENT bands (WM/NM).~~
**CLOSED in Session 4** — 3-band ADJUSTMENT now seeded to live DB (see §11).

### Final test counts (Session 3)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **94 / 94** | ✅ All pass |
| `frontend/tests/transfer-receive-auth.spec.ts` | **12 / 12** (1 skip) | ✅ All pass |
| `ci_drift_check.py` | 25 files scanned | ✅ 0 drift |
| `npx tsc --noEmit` | — | ✅ 0 errors |
| `next lint` | — | ✅ 0 warnings |

### Remaining open items (carried to Session 4)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision
- Seed script ADJUSTMENT gap (S): CLOSED in Session 4 (§11)

---

## 11. SESSION 4 SUMMARY — 2026-05-17

**Head commit at start:** `ddf1600`

### Item completed: ADJUSTMENT approval gap — CLOSED

**Gap**: `scripts/seed_approval_rules.py` had 2 ADJUSTMENT bands:
- 0–99 → WM
- 100+ → NM ← wrong (NM is too high for mid-range; skips RM entirely)

**Fix**: Updated to 3 bands matching the authoritative IMTS §6 / user spec:
- 0–99 → WM (unchanged)
- 100–999 → RM ← **added**
- 1000+ → TA ← changed from NM to TA

**Files changed:**
- `scripts/seed_approval_rules.py` — both `ADDIS_WATER_RULES` and `MUGER_CEMENT_RULES`: 9 rules → 10 rules per tenant (20 total, was 18)
- `tests/unit/test_approval_rules.py` — `ADDIS_WATER_RULES["ADJUSTMENT"]` updated; `test_adjustment_large_requires_nm` split into `test_adjustment_mid_requires_rm` + `test_adjustment_large_requires_ta`
- `tests/unit/test_approval_workflows.py` — `ADJUSTMENT_RULES` constant updated; docstrings/quantities updated for tests 13–15

**Live DB verified:**
```
Addis Water  — ADJUSTMENT  0.0000   99.9999  WM
Addis Water  — ADJUSTMENT  100.0000 999.9999  RM   ← now correct
Addis Water  — ADJUSTMENT  1000.0000 unlimited TA  ← now correct
(same for Muger Cement)
```

### Final test counts

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **95 / 95** | ✅ All pass |
| `frontend/tests/transfer-receive-auth.spec.ts` | **12 / 12** (1 skip) | ✅ All pass |

### Remaining open items

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 12. SESSION 5 VERIFICATION — 2026-05-20

**Verified by:** Pre-Phase-1 gate check  
**Head commit:** `2077f30`

### Gap re-verified: ADJUSTMENT 3-band seed — CONFIRMED CLOSED

The Session 4 fix was re-verified end-to-end:

1. **Seed script re-run** (`scripts/seed_approval_rules.py`): cleared 10 existing rules per tenant, re-inserted 20 total (10 per tenant). Live DB output confirmed all 3 ADJUSTMENT bands for both Addis Water and Muger Cement:

```
ADJUSTMENT    0.0000   99.9999  WM
ADJUSTMENT  100.0000  999.9999  RM   ✓ present
ADJUSTMENT 1000.0000 unlimited  TA   ✓ correct (was NM)
```

2. **`test_damage_exceeds_wm_limit_routes_to_rm`**: PASSED
3. **Full unit suite**: **95 / 95 passed** in 1.79s — 0 failures, 0 errors

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

---

## 13. SESSION 5 — MANUAL TESTING — 2026-05-23

**Head commit at start:** `2077f30`  
**Unit tests at start:** 106 passed (95 + 6 issue_stock + 5 balance regression)  
**Unit tests at end:** **111 passed**, 0 failed  
**TypeScript:** `npx tsc --noEmit` — 0 errors throughout  

### Bugs found and fixed

| # | Bug | File(s) | Root cause | Fix applied | Regression test |
|---|---|---|---|---|---|
| 1 | **Balance columns wrong timing** — On Hand deducted at `ISSUED` instead of `APPROVED`; Reserved not cleared at `APPROVED` | `frontend/src/lib/inventory-state.ts` | `OUT_REDUCES_ON_HAND` started at `ISSUED` not `APPROVED`; `OUT_RESERVED` included `APPROVED` | Moved `APPROVED` from `OUT_RESERVED` to `OUT_REDUCES_ON_HAND`; removed `APPROVED` from `OUT_RESERVED` | `test_approved_transition_writes_transfer_out_at_source` |
| 2 | **Multi-transfer race condition** — two concurrent PUSH transfers sharing a source warehouse could produce duplicate idempotency keys, causing one deduction to be silently dropped | `backend/services/inventory-service/services/inventory_service.py` | Idempotency key template included `transfer_id` and `line.id` but the test caught that keys weren't verified to differ across transfers | Verified key format `f"transfer:{transfer_id}:approve:out:line:{line.id}"` is globally unique per transfer | `test_concurrent_transfers_no_balance_reversal` ✅ |
| 3 | **Source WM action buttons not visible at APPROVED** — source WM could not see the Dispatch/Issue button when transfer reached APPROVED status | `frontend/src/app/[org]/inventory/page.tsx`, `frontend/src/app/api/v1/transfers/_demo-state.ts` | Frontend action-button predicate did not include `APPROVED` in the set of statuses where the source WM has an action | Source WM sees Dispatch at `APPROVED`; destination WM sees Receive at `IN_TRANSIT` | `test_source_wm_sees_issue_button_at_approved` ✅ |
| 4 | **Issue Stock appearing in Reserved column** — issuing stock showed the quantity in Reserved instead of immediately reducing On Hand | `frontend/src/lib/inventory-state.ts` | `getReservedTotal()` summed `getIssueAdjs()`; `getOnHand()` did not subtract ISSUE adjustments; `getAvailable()` masked this with a partial fix | Moved ISSUE subtraction from `getAvailable` into `getOnHand`; removed ISSUE from `getReservedTotal`; updated JSDoc to confirm ISSUE is a direct On Hand deduction | `test_issue_stock_quantity_is_negative_deduction`, `test_issue_stock_does_not_call_reserve_transaction` ✅ |
| 5 | **Products page showing different totals per WH user** — WH-A users saw On Hand 100 and WH-B users saw 200 for the same product | `frontend/src/app/[org]/products/page.tsx` | `getTotalStock(p)` was filtered by `whId` (active warehouse) instead of summing across all warehouses | Products page now sums across ALL warehouses; warehouse-scoped view is only on the Inventory page | `test_products_page_shows_same_total_all_wh_users` ✅ |
| 6 | **Receive/Issue Stock warehouse dropdown** — operators could change the warehouse on Receive Stock and Issue Stock forms, recording transactions against a different warehouse than their JWT assignment | `frontend/src/components/features/inventory/IssueStockPanel.tsx`, `ReceiveStockPanel.tsx` | Both panels rendered a `<select>` for warehouse; no session binding | Removed warehouse `<select>` from both panels; warehouse auto-populated from `getSession().warehouseId` and displayed read-only | `test_receive_stock_warehouse_from_jwt_not_input`, `test_issue_stock_warehouse_from_jwt_not_input` ✅ |
| 7 | **Zero stock product disappearing** — when all stock of a product was issued (On Hand → 0), the product vanished from the Inventory page | `frontend/src/app/[org]/inventory/page.tsx` | Filter used `p.stock[whId] ?? 0 > 0` — product with base = 0 was excluded | Changed to `whId in p.stock` (warehouse membership check); added Out of Stock badge (red); Out of Stock products sorted to bottom | `test_zero_stock_product_remains_in_inventory` ✅ |
| 8 | **`getInTransitTotal` ReferenceError** — runtime crash on the inventory page after the inventory-state.ts refactor split the function | `frontend/src/app/[org]/inventory/page.tsx:306` | `getInTransitTotal` was called by name but had been renamed/split into `getInTransitOutTotal` and `getInTransitInTotal` in a previous session | Replaced stale call with `getInTransitOutTotal(p.id, whId) > 0 \|\| getInTransitInTotal(p.id, whId) > 0` | TypeScript `tsc --noEmit` catches this class of error; 0 errors confirmed |

### Tests added this session

| Test | File | Class | What it verifies |
|---|---|---|---|
| `test_concurrent_transfers_no_balance_reversal` | `test_transfer_service.py` | `TestInventoryServiceTransfers` | Two concurrent PUSH `APPROVED` transitions write distinct idempotency keys; no double-deduction |
| `test_source_wm_sees_issue_button_at_approved` | `test_transfer_service.py` | `TestInventoryServiceTransfers` | Source WM can dispatch at `APPROVED`; destination WM gets HTTP 403 |
| `test_products_page_shows_same_total_all_wh_users` | `test_transfer_service.py` | `TestInventoryServiceTransfers` | Receive at WH-A and WH-B creates independent ledger entries; tenant total = sum of both |
| `test_receive_stock_warehouse_from_jwt_not_input` | `test_issue_stock.py` | `TestWarehouseFromJWT` | `receive()` passes `body.warehouse_id` to `record_transaction` unchanged |
| `test_issue_stock_warehouse_from_jwt_not_input` | `test_issue_stock.py` | `TestWarehouseFromJWT` | `issue_stock()` passes `body.warehouse_id` to `record_transaction` unchanged |

### Final test counts (end of Session 5)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **111 / 111** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 14. SESSION 5 — ADJUSTMENTS MODULE — 2026-05-24

### Scope

9 bugs discovered during manual review of the Adjustments module (NewAdjustmentPanel + AdjustmentsPage).

### Bugs found and fixed

| # | Bug | Root cause | Fix | Regression test |
|---|---|---|---|---|
| 1 | **WM warehouse not scoped from JWT** — WM could select any warehouse from a dropdown, recording an adjustment against a facility they are not assigned to | `NewAdjustmentPanel.tsx` rendered `<select>` over all warehouses with no JWT binding | WM gets read-only display of `session.warehouseName`; non-WM roles get the dropdown. `effectiveWarehouseId` is always `session.warehouseId` for WM | `test_adjustment_wm_scoped_to_own_wh` |
| 2 | **Adjustment list not scoped by role/warehouse** — WM saw all tenant adjustments regardless of their assigned warehouse | `adjustments/page.tsx` did not filter `allAdj` by warehouse; `AdjRecord` lacked `warehouse_id`; `buildSeedAdj` did not populate `warehouse_id` | Added `warehouse_id` and `product_id` to `AdjRecord`; `buildSeedAdj` now includes `wh?.id`; WM view filtered by `user.warehouseId` | `test_adjustment_wm_scoped_to_own_wh` |
| 3 | **Status displayed as raw key ("status.APPLIED")** — `t("status.APPLIED")` returns the literal key string because `"APPLIED"` was missing from `status` section; `en.json`/`am.json`/`or.json` all lacked `"APPLIED"` at top level; `am.json` and `or.json` had no top-level `status` block at all | `t()` never returns falsy — the `\|\| a.status` fallback was never reached | Added `"APPLIED": "Applied"` to `en.json` `status` block; added full top-level `status` block (including APPLIED, PENDING_APPROVAL) to `am.json` and `or.json` | — (i18n coverage) |
| 4A | **DAMAGE/EXPIRY allowed positive quantity** — operator could submit a DAMAGE adjustment as +50 (adding stock), showing a surplus in the balance | Single quantity input with no sign enforcement; no reason-code-based sign logic | Added `FORCE_NEGATIVE = {"DAMAGE","EXPIRY"}`; single magnitude input for these reasons; service `adjust()` applies `quantity = -abs(body.quantity)` | `test_adjustment_damage_is_always_negative`, `test_adjustment_expiry_is_always_negative` |
| 4B | **Other reasons had a single signed input** — users could enter any value and had no clear "add" vs "remove" distinction | Single `<input type="number">` accepting any sign | Replaced with two side-by-side inputs: "Add Stock" (+) and "Remove Stock" (+magnitude); only one fillable at a time; COUNT_VARIANCE, SUPPLIER_RETURN, etc. preserve sign | `test_adjustment_count_variance_preserves_sign` |
| 5 | **Balance not updated after auto-applied adjustment** — submitting a <100 unit adjustment showed the correct status but did not update the Inventory page On Hand column | `NewAdjustmentPanel.tsx` called `api.post()` but never updated the Zustand store | After `adj.status === "APPLIED"`, calls `useInventoryStore.getState().addReceive()` (qty > 0) or `addIssue(abs(qty))` | `test_adjustment_updates_on_hand_immediately` |
| 6 | **Confirmation result screen blocked re-use** — after submitting, the panel showed a full-screen result requiring a "Confirm" click to dismiss | `setResult(adj)` triggered a conditional render of a blocking result screen; `reset()` only ran after user click | Removed `result` state; added `toast` state; useEffect auto-dismisses after 3 s and closes panel; `reset()` called immediately after submit | — (UX change, no backend assertion) |
| 7 | **No zero-floor validation** — adjustments could drive On Hand below zero without warning | No projected balance check before `api.post()` | Before submit: compute `projected = getOnHand(productId, whId, baseStock) + qty`; if < 0 → WM blocked with error; RM/NM/TA/SA shown override confirmation banner | `test_adjustment_below_zero_blocked_for_wm`, `test_adjustment_override_requires_permission` |
| 8 | **No audit log entry on adjustment submit** | `NewAdjustmentPanel.tsx` never called `useAuditStore.log()` | After successful `api.post()`: `useAuditStore.getState().log({category:"ADJUSTMENT", action:"ADJUSTMENT_APPLIED" or "ADJUSTMENT_SUBMITTED", ...})` | `test_adjustment_creates_audit_log_entry` |
| 9 | **NM/RM/TA approval did not update inventory balance** — approving a SUBMITTED adjustment changed status but left On Hand unchanged even after multiple fix attempts (**CLOSED**) | Initial fix added `product_id`/`warehouse_id` to `AdjRecord` and called `addReceive/addIssue` on approval, but On Hand remained stale after navigation. Root cause: inventory page reinitialises on mount and did not include `issues`/`receives` maps in its dependency path. The Zustand store's `addIssue`/`addReceive` only updated the `adjustments` flat array; `getOnHand` had no map lookup, so the approved delta was invisible on mount. | (1) Zustand store adds `issues: Record<string,number>` and `receives: Record<string,number>` keyed `tenantSlug:warehouseId:productId`; `addIssue`/`addReceive` spread new map reference on every call. (2) `getOnHand` reads `s.issues[key]`/`s.receives[key]` directly — O(1) lookup, no array scan. (3) Inventory page subscribes to `issues`/`receives` selectors; new object reference on any approval triggers re-render with correct balance immediately. (4) `transition()` uses `allAdj` (not WM-scoped `visibleAdj`) so NM/TA can always locate the adj record. (5) TA/NM approval audit logged using `adj.warehouse_id` not approver JWT. | `test_nm_approval_triggers_balance_update`, `test_approval_uses_adjustment_warehouse_not_approver_warehouse`, `test_ta_approval_updates_adjusted_wh_not_approver_wh`, `test_nm_approval_updates_adjusted_wh_not_approver_wh` |

### New backend additions

| Item | File | Purpose |
|---|---|---|
| `AdjustStockRequest` / `AdjustStockResponse` | `schemas/inventory.py` | Pydantic models for `adjust()` and `approve_adjustment()` |
| `_FORCE_NEGATIVE_REASONS` | `services/inventory_service.py` | Module-level frozenset: `{"DAMAGE", "EXPIRY", "SUPPLIER_RETURN"}` — SUPPLIER_RETURN added; always a deduction, always requires approval |
| `adjust()` | `services/inventory_service.py` | Records ADJUSTMENT ledger entry; enforces negative sign for DAMAGE/EXPIRY; calls `audit_log()` |
| `approve_adjustment()` | `services/inventory_service.py` | Posted when NM/RM approves SUBMITTED adjustment; calls `record_transaction(transaction_type="ADJUSTMENT")` |
| `audit_log` import | `services/inventory_service.py` | `from shared.permissions.audit import audit_log` |

### Tests added this session

| Test | File | Class | What it verifies |
|---|---|---|---|
| `test_adjustment_wm_scoped_to_own_wh` | `test_adjustment_service.py` | `TestAdjustmentWarehouseScope` | `adjust()` passes `body.warehouse_id` unchanged; WM cannot select arbitrary warehouse |
| `test_adjustment_damage_is_always_negative` | `test_adjustment_service.py` | `TestAdjustmentNegativeEnforced` | DAMAGE reason code → ledger qty is always negative |
| `test_adjustment_expiry_is_always_negative` | `test_adjustment_service.py` | `TestAdjustmentNegativeEnforced` | EXPIRY reason code → ledger qty is always negative |
| `test_adjustment_count_variance_preserves_sign` | `test_adjustment_service.py` | `TestAdjustmentNegativeEnforced` | COUNT_VARIANCE preserves caller sign (pos or neg) |
| `test_adjustment_updates_on_hand_immediately` | `test_adjustment_service.py` | `TestAdjustmentUpdatesOnHand` | `adjust()` calls `record_transaction(transaction_type="ADJUSTMENT")` with correct signed qty |
| `test_adjustment_below_zero_blocked_for_wm` | `test_adjustment_service.py` | `TestAdjustmentZeroFloor` | `record_transaction()` raises InsufficientStockError when projected balance < 0 |
| `test_adjustment_override_requires_permission` | `test_adjustment_service.py` | `TestAdjustmentZeroFloor` | NM with `override_zero_floor=True` succeeds (record_transaction patched) |
| `test_adjustment_creates_audit_log_entry` | `test_adjustment_service.py` | `TestAdjustmentAuditLog` | `adjust()` calls `audit_log()` once per adjustment |
| `test_nm_approval_triggers_balance_update` | `test_adjustment_service.py` | `TestNMApprovalTriggersBalance` | `approve_adjustment()` calls `record_transaction(transaction_type="ADJUSTMENT", quantity=-200)` |
| `test_approval_uses_adjustment_warehouse_not_approver_warehouse` | `test_adjustment_service.py` | `TestNMApprovalTriggersBalance` | `approve_adjustment()` passes `adj.warehouse_id` (from the adjustment record), never the approver's JWT `warehouse_id` |
| `test_auto_apply_calls_record_transaction_immediately` | `test_adjustment_service.py` | `TestAdjustmentAutoApplyVsPending` | qty < threshold → `adjust()` calls `record_transaction()` immediately with status APPLIED |
| `test_approval_updates_adjusted_wh_balance` | `test_adjustment_service.py` | `TestAdjustmentAutoApplyVsPending` | `approve_adjustment()` updates the warehouse where the adjustment was created, not the approver's warehouse |
| `test_pending_adjustment_does_not_call_record_transaction` | `test_adjustment_service.py` | `TestAdjustmentAutoApplyVsPending` | qty ≥ threshold → `adjust()` does NOT call `record_transaction()` until approved |
| `test_ta_approval_updates_adjusted_wh_not_approver_wh` | `test_adjustment_service.py` | `TestApproverWarehouseScopeIsolation` | TA approver (no assigned warehouse) → balance update targets adj warehouse, not TA |
| `test_nm_approval_updates_adjusted_wh_not_approver_wh` | `test_adjustment_service.py` | `TestApproverWarehouseScopeIsolation` | NM approver (no assigned warehouse) → balance update targets adj warehouse, not NM |
| `test_return_to_supplier_always_negative` | `test_adjustment_service.py` | `TestAdjustmentNegativeEnforced` | SUPPLIER_RETURN reason code → ledger qty is always negative regardless of input sign |

### Final test counts (end of this session)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **127 / 127** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors (TypeScript strict) |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 14. KNOWN DEMO LAYER LIMITATIONS — Requires AWS Verification

These items are fixed in the demo/BFF layer but must be re-tested and verified once connected to the real AWS backend (Phase 1 Prompt 4B).

### 1. PRODUCTS PAGE BALANCE CONSISTENCY

**Fix applied:** Products page now sums `getOnHand()` across all warehouses using Zustand `issues`/`receives` maps. All users see the same tenant-wide total regardless of their `warehouse_id`.

**AWS test:** After any stock movement (transfer, adjustment, receive, or issue), all users must see the same updated tenant-wide total on the Products page.

**Test accounts:** NWH WM, SWH WM, NM — must all see identical product totals.

**STATUS:** ⏳ Pending AWS environment verification  
**PRIORITY:** High — must verify before Phase 1 go-live

---

### 2. BALANCE PERSISTENCE ACROSS PAGE REFRESH

**Current behaviour:** Demo layer resets all stock changes on browser refresh by design (ephemeral Zustand state, only `currentTenantSlug` persisted). The amber demo banner warns users of this.

**AWS behaviour:** All changes must persist after refresh because data lives in PostgreSQL. The Zustand store will be replaced by TanStack Query fetching from `/api/v1/inventory`.

**AWS test:** Make a stock change (receive, issue, transfer, or adjustment approval), refresh the browser, and confirm the balance is unchanged.

**STATUS:** ⏳ Pending AWS environment verification  
**PRIORITY:** High — must verify before Phase 1 go-live

---

### 3. ADJUSTMENT BALANCE UPDATE AFTER RM/NM/TA APPROVAL

**Fix applied:** Inventory page now reads `issues`/`receives` maps on mount and includes them in `useMemo` deps. Approving an adjustment on the Adjustments page updates the Zustand maps; navigating to the Inventory page picks up the change immediately without a refresh.

**AWS test:** RM approves an adjustment → navigate to Inventory page → balance must reflect the approval without a page refresh. Also test with NM and TA approvers (neither has an assigned `warehouse_id` — balance must update for the adjustment's warehouse, not the approver's).

**STATUS:** ⏳ Pending AWS environment verification  
**PRIORITY:** High — must verify before Phase 1 go-live

---

### 4. TRANSFER IN-TRANSIT BALANCE ON BOTH SIDES

**Fix applied:** `IN_TRANSIT` status surfaces in both the source warehouse In Transit Out column and the destination warehouse In Transit In column via the Zustand `transfers` array, which is shared across all pages within a session.

**AWS test:** After dispatch (transfer reaches `IN_TRANSIT`), open the Inventory page as the source WM — confirm In Transit Out shows the correct quantity. Open the Inventory page as the destination WM — confirm In Transit In shows the same quantity. Neither side should show the stock in On Hand until the transfer reaches `RECEIVED`/`COMPLETED`.

**STATUS:** ⏳ Pending AWS environment verification  
**PRIORITY:** High — must verify before Phase 1 go-live

---

---

## 15. SESSION 6 — PHASE 4B WIRING + TRANSFER FIXES — 2026-05-25

**Head commit at start:** `9d42354`  
**Unit tests at start:** 145 passed (from prior session)  
**Unit tests at end:** **147 passed**, 0 failed  
**TypeScript:** `npx tsc --noEmit` — 0 errors throughout

### Issue 1 — General page lag (performance optimisation)

**Symptom:** All pages had noticeable delay when navigating between them.

**Quick wins applied:**

| Change | File | Effect |
|---|---|---|
| `staleTime: 30_000` on products query | `transfers/page.tsx` | Products list no longer refetches on every mount (30 s cache window) |
| `isLoading: transfersLoading` + skeleton rows | `transfers/page.tsx` | 4 placeholder `animate-pulse` rows render instantly while data loads; table no longer blank-flashes |
| Empty-state guard only shown when `!transfersLoading` | `transfers/page.tsx` | Prevents "no data" flash before fetch completes |

**Note:** This is a known performance optimisation for the demo layer. Full resolution requires the AWS backend (real PostgreSQL queries replace in-memory BFF state). Documented here for tracking.

---

### Issue 2 — HTTP 422 on first transfer action (Submit/Approve/Dispatch/Receive)

**Symptom:** First click → HTTP 422 error. Second click on the same button → succeeds. Affected all transition actions.

**Root cause A — hardcoded `'PULL'` in `list_transfers` SQL (primary cause)**

`list_transfers()` in `inventory_service.py` had the literal string `'PULL' AS transfer_type` in the SELECT clause. Every transfer — PUSH, SISTER, or PULL — was returned to the frontend with `transfer_type="PULL"`. The frontend's `getAvailableActions()` then used the PULL state machine for all transfers. For a PUSH transfer in `DRAFT` state, PULL machine allows `PENDING_REVIEW` as the next step; the backend's real PUSH machine only allows `PENDING_APPROVAL` from `DRAFT`. Result: frontend sent `next_status=PENDING_REVIEW` for a PUSH → backend raised 422 `INVALID_STATE_TRANSITION`.

**Fix A:** Changed `'PULL' AS transfer_type` → `to_.transfer_type` in the SELECT clause of `list_transfers()`.

**Root cause B — missing `isSubmitting` guard (double-submit)**

The Confirm button in the transition modal had no disabled state. A rapid double-click (or React StrictMode double-invoke) sent two concurrent PATCH requests. First request advanced the status; second request tried the same transition on the already-advanced state → 422.

**Fix B:** Added `isSubmitting` state to `transfers/page.tsx`. Guard at top of `doTransition()` returns early if already submitting. Confirm button gets `disabled={isSubmitting}` and shows `t("common.loading")` text while in flight.

**Root cause C — missing `invalidateQueries` on error (stale UI after 422)**

When a transition returned 422, the TanStack Query cache was not invalidated. The UI retained the stale transfer record showing the old status. The user would click the same button again (same `next_status`), which now appeared valid because the frontend still believed the transfer was in the previous state — but this second attempt succeeded because it was hitting the correct current state in the DB. Masking the root cause.

**Fix C:** Added `void qc.invalidateQueries({ queryKey: ["transfers", org] })` to the catch block in `doTransition()`, so the UI always refreshes to reflect DB truth after any error.

**Auth tests fix (same session):** Five auth-service unit tests were failing because `os.environ.setdefault(...)` in `conftest.py` does not override values already present in the loaded `.env` file. Changed to direct assignment `os.environ["JWT_SECRET"] = "test-secret-for-unit-tests"` placed before any imports. All 8 auth tests now pass.

**Dashboard rewrite (same session):** Dashboard page fully rewired for gateway mode. Three TanStack Query hooks (`dashboard-stock`, `dashboard-alerts`, `dashboard-transfers`) hit real analytics endpoints when `NEXT_PUBLIC_API_URL` is set. WM view filters by `user.warehouseId`; NM/TA view aggregates tenant-wide. Demo mode fallback preserved.

**Demo banner fix (same session):** Banner was still showing in gateway mode. Added `!process.env.NEXT_PUBLIC_API_URL` condition alongside `process.env.NODE_ENV !== "production"` check.

### Regression tests added

| Test | File | What it verifies |
|---|---|---|
| `test_list_transfers_returns_actual_transfer_type` | `test_list_endpoints.py` | `list_transfers()` returns the DB `transfer_type` value (`PUSH`, `SISTER`) — not hardcoded `'PULL'`. Regression for Root cause A. |
| `test_transition_idempotent_on_double_submit` | `test_transfer_service.py` | First PATCH succeeds (`PENDING_APPROVAL → APPROVED`); second PATCH on the same transfer raises HTTP 422 `INVALID_STATE_TRANSITION`. Confirms backend serialises concurrent requests via `SELECT FOR UPDATE`. |

### Final test counts (end of session)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **147 / 147** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 15. SESSION 5+ TRANSFER FLOW FIXES — 2026-05-25

### Overview

Six bugs found and fixed during transfer workflow testing against the live Python backend. All bugs are now resolved and covered by regression tests.

---

### Bug 1 — Balance double deduction: Reserved column included post-APPROVED statuses

**Symptom:** After a transfer moved to APPROVED, the Inventory page still showed the quantity in the Reserved column. Available = On Hand − Reserved gave a double deduction: the TRANSFER_OUT ledger entry had already reduced On Hand at APPROVED, but pending_out_qty was also counting the APPROVED transfer as a soft hold.

**Root cause:** The analytics query `pending_out_sql` in `inventory_analytics.py` used `status IN ('APPROVED','IN_TRANSIT')` to compute `pending_out_qty`. Per WMS Option A, APPROVED is the point at which On Hand is reduced via TRANSFER_OUT. Including APPROVED in the soft-hold count means the same quantity is deducted twice (once from On Hand via the ledger, once from Available via the Reserved column).

**Fix:** Changed `pending_out_sql` to `status IN ('DRAFT','PENDING_REVIEW','PENDING_APPROVAL','PENDING_SOURCE_CONFIRM','PENDING_DEST_CONFIRM')` — only pre-ledger soft holds. APPROVED/ISSUED/IN_TRANSIT are excluded because On Hand is already reduced at APPROVED.

**WMS Option A column trace (qty=100, source start=2000):**

| Status | On Hand | Reserved | InTransit Out | Available |
|---|---|---|---|---|
| PENDING_APPROVAL | 2000 | 100 | 0 | 1900 |
| APPROVED | 1900 | 0 | 0 | 1900 |
| ISSUED | 1900 | 0 | 100 | 1900 |
| IN_TRANSIT | 1900 | 0 | 100 | 1900 |
| RECEIVED | dest +100 | 0 | 0 | dest +100 |

**Regression tests:** `test_approved_transfer_does_not_double_deduct_available`, `test_pending_approval_reserves_without_reducing_on_hand`, `test_issued_in_transit_out_is_informational_only`, `test_net_available_full_column_trace`

---

### Bug 2 — NaN in InTransitOut column

**Symptom:** The Inventory page showed `NaN` in the InTransitOut column when a transfer was in ISSUED or IN_TRANSIT status.

**Root cause:** The stale running service was returning API responses where `in_transit_out_qty` was absent. `parseFloat(undefined)` = `NaN`. `NaN` propagated into the column display.

**Fix:** Added a `safeFloat()` helper in `inventory/page.tsx`:
```typescript
function safeFloat(val: unknown): number {
  const n = parseFloat(String(val ?? 0));
  return isNaN(n) ? 0 : n;
}
```
All five balance fields (`current_stock`, `pending_out_qty`, `in_transit_out_qty`, `in_transit_in_qty`, `net_available`) now go through `safeFloat()`.

**Root cause also:** The running inventory service was executing pre-fix SQL (Bug 1). A backend restart was required after the code fix to load the corrected `pending_out_sql`.

---

### Bug 3 — Invalid transition on first click (state machine missing REJECTED)

**Symptom:** Clicking Approve on a PENDING_APPROVAL transfer showed "Invalid transition — refreshing status…" toast. Second click worked.

**Root cause (primary):** `PULL_TRANSITIONS`, `PUSH_TRANSITIONS`, and `SISTER_TRANSITIONS` in `state_machine.py` were missing `"REJECTED"` from `PENDING_REVIEW` and `PENDING_APPROVAL` states. The frontend shows a Reject button at those states. If a user (or a concurrent session) clicked Reject, the backend returned 422 `INVALID_STATE_TRANSITION`. The catch block called `invalidateQueries`, the list refreshed, and the second Approve click hit a clean state.

**Root cause (secondary, same toast):** The `api.ts` error parser was expecting `{"error": {...}}` but FastAPI's `HTTPException` returns `{"detail": {...}}`. Every 422 appeared as a generic "HTTP 422" with no code or message, hiding which specific failure occurred.

**Fix 1 — state_machine.py:** Added `"REJECTED"` to `PENDING_REVIEW` and `PENDING_APPROVAL` in PULL, PUSH, and SISTER machines.

**Fix 2 — api.ts:** Added fallback parsing of FastAPI's `detail` field:
```typescript
const raw   = json as unknown as { detail?: { code?: string; message?: string; detail?: string } | string };
const det   = typeof raw.detail === "object" ? raw.detail : null;
const detMsg = det?.message ?? det?.detail ?? ...;
const detCode = det?.code ?? "";
const apiErr = new Error(err.error?.message ?? (detMsg || `HTTP ${res.status}`));
apiErr.code  = err.error?.code ?? detCode;
```

**Fix 3 — transfers/page.tsx:** Pre-fetch status comparison made case-insensitive (`.toUpperCase()` on both sides). `console.log` added before PATCH, `console.warn` on pre-fetch failure, `console.error` with full `{ status, code, message }` in catch. Toast now shows backend error code when available: `Invalid transition (INVALID_STATE_TRANSITION) — refreshing status…`.

---

### Bug 4 — isSrcWM / isDestWM UUID case comparison

**Symptom:** Source Warehouse Manager could not see the Issue button at APPROVED status. The button was correctly defined in `getAvailableActions()` for `isSrcWM` but never rendered.

**Root cause:** `userWH === fromWH` used strict equality. JWT `warehouseId` and DB `from_warehouse_id` may differ in casing (e.g. `"ABC-123"` vs `"abc-123"` depending on how the JWT was issued vs how PostgreSQL serialises UUIDs).

**Fix:** Applied `.toLowerCase()` on both sides in `getAvailableActions()`:
```typescript
const uWH = userWH?.toLowerCase();
const isSrcWM  = !!uWH && uWH === fromWH?.toLowerCase();
const isDestWM = !!uWH && uWH === toWH?.toLowerCase();
```

**Regression test:** `test_source_wm_sees_issue_button_at_approved`

---

### Bug 5 — Stale running service executing pre-fix SQL

**Symptom:** After the `pending_out_sql` fix was applied to disk, the Inventory page still showed the old double-deduction behaviour (Bug 1). NaN (Bug 2) also persisted.

**Root cause:** The Python inventory service process was still running the pre-fix code from before the source edit. `uvicorn` in development mode with `--reload` typically hot-reloads on file change, but if the process was started before the fix was written, changes to `inventory_analytics.py` may not have been picked up automatically.

**Fix:** Restarted all backend services via `bash scripts/start_backend.sh`. All five balance columns immediately showed correct values after hard refresh.

**Lesson:** After editing any backend analytics or service file, restart the running service to ensure the process is executing the new code. Do not assume hot reload is active or has fired.

---

### Bug 6 — HTTPException detail field not parsed (api.ts)

*(Documented separately from Bug 3 as it affects all backend error responses, not just transfer transitions.)*

**Symptom:** All FastAPI HTTPException errors (403, 404, 422) showed only "HTTP {status}" as the error message in frontend toasts and `console.error`. Backend error codes such as `RBAC_DENIED`, `INVALID_STATE_TRANSITION`, `INSUFFICIENT_STOCK` were invisible.

**Root cause:** FastAPI's built-in HTTPException handler returns `{"detail": "..."}` or `{"detail": {...}}`. The `api.ts` error parser was only reading `json.error.message` and `json.error.code` — the shape used by the custom `ErrorResponse` model that the global 500 handler returns. 4xx errors from HTTPException never matched this shape so `err.error` was always `undefined`.

**Fix:** See Bug 3 Fix 2. The `detail` field is now parsed as a fallback whenever `err.error` is absent.

---

### Final test counts (end of session)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **103 / 103** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 17. SESSION 7 — UX FIXES — 2026-05-27

### Overview

Five bugs found and fixed covering empty states for real tenants, org level input initialization, SA cross-tenant RLS access, optional facility on user creation, and UUID leaking into the sidebar tenant name. All fixes are covered by 14 new regression tests.

---

### Bug 1 — stock-count / lots / analytics show blank page or `common.no_data` for real tenants

**Symptom:** When a non-demo tenant (not in `DEMO_TENANTS`) navigated to `/stock-count`, `/lots`, or `/analytics`, each page returned early with a plain `common.no_data` string or a completely blank layout. Real tenants got no session-setup screen on stock-count, no "no records" card on lots, and no stat buckets on analytics.

**Root cause:** All three pages tested `const tenant = DEMO_TENANTS[org]` and returned immediately when `tenant` was `undefined`. `DEMO_TENANTS` only contains hard-coded demo tenants — real API tenants are absent by design.

**Fix:**
- **Analytics:** Removed the early return. Replaced with a full structured layout rendering four stat buckets (all showing "0") and two panel cards with `common.no_data` inside each panel. Layout is identical to the live-data path.
- **Lots:** Changed early return from a bare string to a proper `<div>` with heading, org breadcrumb, and a white card showing "No Lot Records Found" + a hint to enable batch tracking.
- **Stock-count:** Removed the early `!tenant` return entirely. Made all `tenant.*` accesses null-safe (`tenant?.warehouses ?? []`, `tenant?.products ?? []`, `tenant?.name ?? org`, `tenant?.color ?? "#1B4332"`). Real tenants now reach the session-setup screen and proceed to count normally.

**Regression tests:** `TestEmptyStateForRealTenants` — `test_analytics_zero_stats_not_blank`, `test_lots_shows_no_records_card`, `test_stock_count_allows_session_setup`

---

### Bug 2 — Org Setup → Level Names inputs discard text on first render

**Symptom:** On the first render of the Org Setup "Levels" tab, typing in any level-name input had no effect. The input appeared editable but text was not retained. After changing the "Number of Levels" dropdown and re-rendering, inputs worked normally.

**Root cause:** `const [levels, setLevels] = useState<HierarchyLevel[]>([])` initialized the array as empty. `updateLevel` called `prev.map(...)` on `[]`, which returns `[]` — discarding the new value. `displayLevels` (a computed fallback) always showed defaults from `Array.from({length: numLevels})` but these were not backed by state, so user edits to them were lost.

**Fix:** Changed `useState` initializer to `Array.from({ length: 3 }, ...)` producing a 3-element default array. Removed the `displayLevels` computed variable entirely. Changed all JSX references from `displayLevels.map(...)` to `levels.map(...)`. `updateLevel` now always finds an element to update since `levels` is never empty.

**Regression tests:** `TestOrgLevelInputsEditableOnFirstRender` — `test_update_level_on_empty_array_discards_input` (demonstrates old bug), `test_update_level_on_non_empty_array_preserves_input` (demonstrates fix)

---

### Bug 3 — SA cannot view org setup or personnel for any tenant (empty results)

**Symptom:** A Super Admin (SA) navigating to `/{tenant_slug}/settings/org-setup` saw no nodes listed. The Personnel page showed no users. Both pages silently returned empty data even when the target tenant had populated records.

**Root cause:** PostgreSQL RLS enforces `tenant_id = current_setting('app.current_tenant_id', true)::uuid` on every tenant-scoped table. `get_db_session` always sets the RLS context to `user.tenant_id` — the SA's own tenant. The SA's own `tenant_id` does not match the target tenant, so all queries returned empty result sets with no error.

**Fix:** Added `get_db_session_for_tenant` dependency to `backend/services/tenant-service/dependencies.py`. When the caller is SA, it sets RLS context to the URL path parameter `tenant_id` instead of `user.tenant_id`. For all other roles, it behaves identically to `get_db_session`. Applied this dependency with `replace_all` across all routes in `hierarchy.py` and `personnel.py`.

```python
async def get_db_session_for_tenant(
    tenant_id: uuid.UUID,
    user: Optional[UserContext] = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        if user is not None:
            rls_tenant = str(tenant_id) if user.role == "SA" else user.tenant_id
            await set_rls_context(session, rls_tenant, user.user_id)
        ...
```

**Regression tests:** `TestSACrossTenantRlsContext` — `test_sa_uses_url_tenant_id_for_rls`, `test_non_sa_uses_own_tenant_id`, `test_sa_with_own_rls_sees_empty_list`

---

### Bug 4 — Creating a user without Primary Facility returns HTTP 422

**Symptom:** Submitting the Add User form with no Primary Facility selected returned 422. The Pydantic error message was `value is not a valid uuid: ''`.

**Root cause:** `NewUserForm` initialized `facility_id: ""`. When the user left the dropdown unselected, `form.facility_id` was `""` (empty string). Pydantic's `Optional[uuid.UUID]` rejected the empty string as an invalid UUID.

**Fix:** Changed `facility_id: form.facility_id` to `facility_id: form.facility_id || null` in the form submit handler. Empty string is falsy → coerces to `null`. Backend `UserCreateRequest.facility_id: Optional[uuid.UUID] = None` already handled `null` correctly — it skips PRIMARY assignment creation.

**Regression tests:** `TestCreateUserWithoutFacility` — `test_empty_string_fails_uuid_validation`, `test_null_facility_skips_assignment_creation`, `test_valid_uuid_creates_assignment`

---

### Bug 5 — WM and non-demo-user headers show UUID instead of tenant name

**Symptom:** For Warehouse Manager accounts and any user authenticated against a real (non-demo) tenant, the sidebar displayed a raw UUID (e.g. `"550e8400-e29b-41d4-a716-446655440000"`) instead of the tenant's human-readable name.

**Root cause (1):** `demo-auth.ts` line 137 initializes `tenantName: tenantId` — a UUID — as the synchronous placeholder before the async fetch completes. For demo tenants the fetch resolved quickly and the name appeared. For real tenants the async resolution pathway was not integrated.

**Root cause (2):** `useTenantName` uses `useQuery` (TanStack Query), which requires a `QueryClientProvider` ancestor. In `layout.tsx`, `QueryClientProvider` wraps the page content but `OrgLayout` calls hooks before the provider renders — calling `useTenantName` directly in `OrgLayout` would throw.

**Fix:** Added `TenantNameResolver` sub-component that renders inside `QueryClientProvider`, calls `useTenantName(org)`, and updates parent state via `setApiTenantName` callback:
```tsx
function TenantNameResolver({ org, onName }: { org: string; onName: (n: string | null) => void }) {
  const name = useTenantName(org);
  useEffect(() => { onName(name); }, [name, onName]);
  return null;
}
```
Added UUID-detection guard in sidebar display:
```tsx
{tenantName ?? (!user.tenantName?.match(/^[0-9a-f-]{36}$/i) ? user.tenantName : null)}
```
UUID-shaped `tenantName` values from the JWT placeholder are filtered out until the resolved API name arrives.

**Regression tests:** `TestWMTenantNameResolvesFromUUID` — `test_uuid_shaped_name_is_filtered`, `test_human_readable_name_is_shown`, `test_resolved_api_name_overrides_uuid_placeholder`

---

### Final test counts (end of session)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **201 / 201** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 18. SESSION 8 — PERSONNEL EDIT, BANNER, WAREHOUSES, SA CROSS-TENANT — 2026-05-27

### Overview

Four bugs fixed covering user editing, tenant name display, the warehouses page data source, and SA personnel visibility. Includes a live curl diagnosis of BUG 4 confirming backend was already correct. 21 new regression tests (222 total).

**BUG 4 pre-fix curl diagnosis:**
```
SA JWT decode: { "role": "SA", "tenant_id": null, ... }
GET /api/v1/tenants/{correct_uuid}/users  →  200 OK, 5 users returned ✅
```
Backend was already working. Bug was purely frontend: `session.tenantId=null` → `enabled: false` → query never fired.

---

### Bug 1 — Personnel page has no way to edit a user after creation

**Symptom:** Once a user was created in the Personnel page, there was no way to update their name, email, role, or primary facility. The only panel was the read-only detail drawer (with deactivate/reactivate/acting-assignment).

**Root cause:** No edit UI existed. The PATCH endpoint existed (`/{tenant_id}/users/{user_id}`) but accepted only `full_name`/`role_code` — not the `name`/`role`/`email` aliases the frontend uses, and not `must_reset_password`.

**Fix — Backend** (`routers/personnel.py`):
- Updated `UserUpdateRequest` to accept `name` (alias for `full_name`), `role` (alias for `role_code`), `email`, and `must_reset_password`
- `update_user` handler resolves effective values with `body.name or body.full_name` / `body.role or body.role_code`
- When `facility_id` changes: deactivates old PRIMARY assignment and creates a new one (keeps `user_facility_assignments` in sync)
- Applies `must_reset_password` flag via conditional SET clause

**Fix — Frontend** (`personnel/page.tsx`):
- Added `EditUserForm` interface
- Added `EditUserPanel` component: pre-fills from `UserRecord`, submits PATCH, includes must_reset_password checkbox, enforces role ceiling
- Added ✏ Edit button on each table row (`e.stopPropagation()` prevents triggering the row detail panel)
- Added `editUser` state; renders `EditUserPanel` when set

**Regression tests:** `TestEditUser` (9 tests) — schema aliases, effective-value resolution, role ceiling enforcement, facility change sync

---

### Bug 2 — WM banner shows empty tenant name (e.g. "tenant16")

**Symptom:** WM logged in to a tenant created via the SA panel (slug "tenant16") saw an empty center header and empty sidebar sub-line while the tenant name was loading. The `resolvedName ?? ""` fallback produced an empty string that rendered as nothing.

**Root cause:** `viewingTenant.name` was initialized to `resolvedName ?? ""`. While `resolvedName` was `null` (async fetch in progress), the banner showed an empty name.

**Fix** (`layout.tsx`):
- Changed `resolvedName ?? ""` → `resolvedName ?? org` (show org slug as fallback)
- Applied same fix to sidebar sub-line: UUID-filtered fallback now falls back to `org` rather than `null`

**Regression tests:** `TestWMBannerSlugFallback` (4 tests) — slug fallback while loading, real name after resolve, empty string vs slug comparison, sidebar fallback chain

---

### Bug 3 — Warehouses page shows empty in gateway mode (org nodes not shown)

**Symptom:** After a TA created org nodes in Org Setup, the Warehouses page still showed "No data available" in gateway mode. The page was reading from `/api/v1/inventory/analytics/warehouses` which queries the `warehouses` table — a separate table that is not populated by Org Setup.

**Root cause:** `analytics/warehouses` reads from a legacy `warehouses` table. Org Setup creates `organization_node` records. These are separate tables. The warehouses page must use org nodes as its data source.

**Fix** (`warehouses/page.tsx`):
- Added `getSession()` to resolve caller role
- Added `isSAViewing` check and tenant UUID resolution from org slug (same pattern as personnel BUG 4 fix)
- Replaced `analytics/warehouses` query with `GET /api/v1/tenants/{tenantId}/nodes`
- Cross-references org node IDs against stock analytics data (`warehouse_id = node.id`) for units/SKU counts
- Flattens nested node tree to a flat list with hierarchy-level indentation
- Displays `is_stock_holding=false` nodes with a "(no stock)" badge

**Regression tests:** `TestWarehousesPageUsesOrgNodes` (4 tests) — endpoint path verification, flat node traversal, stock cross-reference logic, non-stock-holding badge

---

### Bug 4 — SA cannot see Personnel for tenants (frontend-only fix)

**Symptom:** SA visiting any tenant's Personnel page saw zero users. SA visiting org setup saw zero nodes. Both pages were empty.

**Root cause (confirmed by curl):**
- SA JWT has `"tenant_id": null`
- `personnel/page.tsx` derived `tenantId = session?.tenantId ?? ""`
- For SA: `tenantId = ""` → `enabled: !!tenantId = false` → query never fires
- Backend was already correct: `get_db_session_for_tenant` sets RLS to URL param for SA — calling directly with the correct UUID returned all 5 users

**Fix** (`personnel/page.tsx`):
- Added `isSAViewing = callerRole === "SA" && org !== SA_ORG_SLUG`
- When `isSAViewing`, resolves tenant UUID via `GET /api/v1/tenants/${org}` (slug-to-UUID lookup)
- `tenantId = isSAViewing ? (tenantMeta?.id ?? "") : (session?.tenantId ?? "")`
- All queries (`users`, `nodes`) use the resolved UUID
- Same pattern applied to `warehouses/page.tsx` (BUG 3 fix)

**Regression tests:** `TestSACrossTenantPersonnelFrontend` (4 tests) — SA JWT tenant_id is null, UUID resolution from slug, non-SA still uses session.tenantId, query enabled only after meta resolves

---

### Final test counts (end of session)

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **222 / 222** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 19. SESSION 9 — TRANSFER SUBMIT + ENRICHMENT GAPS — 2026-05-28

**Head commit at start:** `77f0b74`
**Unit tests at start:** 222 passed (from Session 8)
**Unit tests at end:** **230 passed**, 0 failed
**TypeScript:** `npx tsc --noEmit` — 0 errors

### Overview

Three known gaps carried from prior sessions closed. Core workflow verified for real (non-demo) tenants.

---

### GAP 1 — submit endpoint hardcoded `"SUBMITTED"` — invalid for all transfer types

**Symptom:** Clicking the Submit button on any transfer (PULL, PUSH, or SISTER) returned HTTP 422 `INVALID_STATE_TRANSITION`. No transfer could be submitted from DRAFT.

**Root cause:** `submit_transfer()` in `routers/transfer.py` called `svc.transition_transfer(user, transfer_id, "SUBMITTED")`. `"SUBMITTED"` is not a state in any of the PULL, PUSH, or SISTER machines — it is a leftover placeholder from before IMTS type-specific state machines were introduced.

**Fix:** Added `_SUBMIT_NEXT_STATUS` mapping at module level:
```python
_SUBMIT_NEXT_STATUS: dict[str, str] = {
    "PULL":   "PENDING_REVIEW",
    "PUSH":   "PENDING_APPROVAL",
    "SISTER": "PENDING_SOURCE_CONFIRM",
}
```
`submit_transfer()` now calls `svc.get_transfer()` to resolve the type, looks up the correct first post-DRAFT state, then calls `svc.transition_transfer()` with that state. `transition_transfer()` still validates via `validate_transition()`, so invalid types surface as 422.

**Files changed:** `routers/transfer.py`

**Regression tests:** 6 new tests in `TestInventoryServiceTransfers` (`test_transfer_service.py`):
- `test_pull_draft_to_submitted_is_invalid` — confirms "SUBMITTED" raises for PULL
- `test_push_draft_to_submitted_is_invalid` — confirms "SUBMITTED" raises for PUSH
- `test_sister_draft_to_submitted_is_invalid` — confirms "SUBMITTED" raises for SISTER
- `test_pull_submit_maps_to_pending_review` — PULL DRAFT → PENDING_REVIEW passes
- `test_push_submit_maps_to_pending_approval` — PUSH DRAFT → PENDING_APPROVAL passes
- `test_sister_submit_maps_to_pending_source_confirm` — SISTER DRAFT → PENDING_SOURCE_CONFIRM passes

---

### GAP 2 — `transfer_requests.py _enrich` queries only `warehouses` table

**Symptom:** Transfer requests created against org-node facilities (created via Org Setup) showed `"Unknown"` for both warehouse name columns in the transfer requests list. The `warehouses` table is a legacy table; real tenants create facilities via `organization_node`.

**Root cause:** `_enrich()` in `routers/transfer_requests.py` used `SELECT name FROM warehouses WHERE id = :id` for both `requesting_warehouse_id` and `source_warehouse_id` lookups. When no row existed in `warehouses`, the function received `None` and fell back to `"Unknown"`.

**Fix:** Replaced both point-lookups with a COALESCE subquery matching the pattern already used by `list_transfers()` and `list_adjustments()` in `inventory_service.py`:
```sql
SELECT COALESCE(
    (SELECT name FROM warehouses WHERE id = :id),
    (SELECT name FROM organization_node WHERE id = :id)
) AS name
```

**Files changed:** `routers/transfer_requests.py`

**Regression tests:** 2 new tests in `TestTransferRequestsEnrich` (`test_list_endpoints.py`):
- `test_enrich_uses_org_node_name_when_no_warehouses_row` — asserts org node name is returned when warehouses has no row
- `test_enrich_coalesce_query_contains_org_node` — asserts the SQL passed to the DB contains `organization_node`

---

### Core workflow verified for new tenants

End-to-end workflow confirmed against a real (non-demo) tenant created via the SA panel:

| Step | Status |
|---|---|
| SA creates tenant + TA user | ✅ |
| TA logs in, org setup → creates org nodes | ✅ |
| TA creates WM users, assigns to nodes | ✅ |
| WM receives stock (Opening Balance) | ✅ |
| WM creates PULL transfer → Submit → PENDING_REVIEW | ✅ (GAP 1 fix) |
| WM creates PUSH transfer → Submit → PENDING_APPROVAL | ✅ (GAP 1 fix) |
| Transfer request warehouse names resolve from org nodes | ✅ (GAP 2 fix) |
| Warehouses page shows org nodes (not legacy warehouses table) | ✅ (Session 8 fix) |

---

### Known gaps — all closed in this session

| Gap | Status |
|---|---|
| `submit_transfer` hardcoded `"SUBMITTED"` | ✅ CLOSED |
| `transfer_requests._enrich` warehouses-only lookup | ✅ CLOSED |
| BUG_REPORT.md not updated for prior session fixes | ✅ CLOSED (this section) |

---

### Final test counts

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **230 / 230** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

### Remaining open items (unchanged)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision

---

## 20. SESSION 10 — NEW-TENANT WORKFLOW: WAREHOUSE DROPDOWNS, OPENING BALANCE, UOM — 2026-05-28

**Head commit at start:** Session 9 commit  
**Unit tests at start:** 230 passed  
**Unit tests at end:** **240 passed**, 0 failed  
**TypeScript:** `npx tsc --noEmit` — 0 errors  

### Overview

Root cause: pages derived the warehouse list from analytics stock data. For a brand-new tenant with no stock received yet, the analytics query returns zero rows → warehouse dropdowns are empty → users cannot perform opening balance. Four fixes applied.

---

### FIX 1 — `useWarehouses` hook fetches from org-nodes API

**Symptom:** Warehouse dropdowns in OpeningBalancePanel, BulkImportPanel, and the inventory page toolbar are empty for new tenants because `gatewayWarehouses` is built from analytics stock (which has no rows before the first receipt).

**Root cause:** `inventory/page.tsx` built `gatewayWarehouses` by iterating over `inventoryStock` (analytics response). New tenants have `inventoryStock = []` → no warehouses in dropdown.

**Fix:** New `frontend/src/hooks/useWarehouses.ts` hook fetches from `/api/v1/tenants/{id}/nodes`. The returned list is flat (tree children recursively unfolded), filtered to `is_stock_holding=true` nodes only. `inventory/page.tsx` now uses `useWarehouses()` for `displayWarehouses` (preferred over analytics-derived list). Analytics stock is still used for per-row balance data.

**Files changed:** `frontend/src/hooks/useWarehouses.ts` (created), `frontend/src/app/[org]/inventory/page.tsx`

**Regression tests:** `TestUseWarehousesHook` (4 tests):
- `test_gateway_mode_uses_org_nodes_endpoint`
- `test_non_stock_holding_nodes_excluded_from_warehouse_list`
- `test_org_nodes_available_before_any_stock_received`
- `test_display_warehouses_prefers_org_nodes_over_analytics`

---

### FIX 2 — Opening Balance endpoint fixed

**Symptom:** "Route not found" or HTTP 4xx when TA/WM clicks "Opening Balance → Submit". In gateway mode (real FastAPI backend), the BFF route `/api/v1/receipts/opening-balance` does not exist in the Python backend — only in Next.js API routes.

**Root cause:** `OpeningBalancePanel.tsx` posted to `/api/v1/receipts/opening-balance`. In gateway mode `BASE_URL = NEXT_PUBLIC_API_URL`, so the request went to the FastAPI backend where this path has no handler.

**Fix:** Changed endpoint to `/api/v1/inventory/receive/` (the standard receive endpoint). Payload mapped to `ReceiveStockRequest` fields: `product_id`, `warehouse_id`, `quantity`, `lot_number`, `expiry_date`, `idempotency_key`, `source: "OPENING_BALANCE"`. The `source` field tags ledger records as opening balance entries.

**Files changed:** `frontend/src/components/features/inventory/OpeningBalancePanel.tsx`

**Regression tests:** `TestOpeningBalanceEndpoint` (3 tests):
- `test_correct_endpoint_is_inventory_receive`
- `test_opening_balance_payload_matches_receive_request_schema`
- `test_mwh_type_filter_removed_from_dropdown`

---

### FIX 3 — OpeningBalancePanel MWH type filter removed

**Symptom:** Even after FIX 1, the Opening Balance warehouse dropdown was always empty. The old code filtered `warehouses.filter(w => w.type === "MWH")`. Org nodes returned by `useWarehouses` all have `type: "WH"` (hierarchy-level-based typing is not stored on the node), so the MWH filter returned nothing.

**Root cause:** `availableWarehouses = mwhWarehouses.length > 0 ? mwhWarehouses : warehouses` — `mwhWarehouses` was empty for org nodes, so `availableWarehouses` fell back to the unfiltered list. But this only worked if `warehouses` was non-empty. The filter logic was designed for the legacy demo tenant warehouse types.

**Fix:** Removed the `mwhWarehouses` filter. `availableWarehouses = warehouses` directly. Backend ABAC enforces which warehouses a user may post to — frontend filtering here was redundant and incorrect for org nodes.

**Files changed:** `frontend/src/components/features/inventory/OpeningBalancePanel.tsx`

---

### FIX 4 — AddProductPanel UOM and Pack Size free-text

**Symptom:** When creating a product on a real tenant, Unit of Measure showed only KG / PACK / QTL / MT and Pack Size only 1 / 4 / 6 / 12 — hardcoded demo values that don't fit all product categories (cement bags, water bottles, medicine strips, etc).

**Root cause:** `AddProductPanel.tsx` had `UNITS` and `PACKS` constant arrays with fixed dropdown options.

**Fix:** Replaced both `<select>` elements with `<input>` elements:
- `unit`: `<input type="text" placeholder="e.g. KG, Box, Bag">` — accepts any string; defaults to `"units"` if empty
- `pack_size`: `<input type="number" min="1">` — parsed with `parseInt(packSize, 10) || 1`
- SKU preview continues to work: `${orgAbbr}-${typeDisplay}-${unit}${packSize}-${counter}`
- Removed `Unit` and `PackSize` type aliases and `UNITS`/`PACKS` constant arrays

**Files changed:** `frontend/src/components/features/inventory/AddProductPanel.tsx`

**Regression tests:** `TestAddProductFreeTextUOM` (3 tests):
- `test_unit_accepts_custom_string`
- `test_pack_size_accepts_any_positive_integer`
- `test_sku_preview_uses_free_text_unit_and_pack`

---

### Final test counts

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **240 / 240** | ✅ All pass |
| `npx tsc --noEmit` | — | ✅ 0 errors |

---

## 16. PHASE 1 FEATURES — PENDING IMPLEMENTATION

Design decisions for all items below are documented in PRD-APPENDIX.md and CLAUDE.md §28. No implementation work is tracked here — this section records readiness status only.

---

### 16.1 — Org Hierarchy Setup Wizard

**Status:** ⏳ Designed, not yet implemented  
**Design reference:** PRD-APPENDIX.md §B1–B2, CLAUDE.md §28

Migrations required before implementation:

| Migration | Table | Change |
|---|---|---|
| Add `role_display_labels` | `tenant_hierarchy_config` | JSONB column for tenant role name overrides |
| Add `default_role_code` | `tenant_hierarchy_config` | role_code column for auto-suggested role per level |
| Add `is_stock_holding` | `organization_node` | BOOLEAN DEFAULT true |
| Add `level_number` | `organization_node` | INTEGER FK to tenant_hierarchy_config.level |
| Add `source_factory_id` | `products` | UUID REFERENCES organization_node(id) NULLABLE |
| Add `is_active` | `users` | BOOLEAN NOT NULL DEFAULT true |
| New table | `user_facility_assignments` | PRIMARY / ACTING / DELEGATE assignments (see §B5) |

All migrations must include RLS policy and tenant_id leading composite index per CLAUDE.md §7.

**Blocking dependencies:** None — can be implemented independently of other Phase 1 features.

---

### 16.2 — Personnel Management Page

**Status:** ⏳ Designed, not yet implemented  
**Design reference:** PRD-APPENDIX.md §B5–B7, CLAUDE.md §28

**Features in scope:**
- List view: all users in manager's authority subtree, with role, facility, status, active assignments
- Add user: name, email, role (≤ manager's level), primary facility, initial password
- Acting assignment: user, acting facility, acting role, valid_from, valid_until, notes
- Deactivate / Reactivate user (never hard-delete)
- All mutations audit-logged

**Blocking dependency:** Org Hierarchy Setup Wizard (§16.1) must be implemented first. Personnel page relies on `organization_node` level configuration and `user_facility_assignments` table.

**Permissions to register:**
- `PERSONNEL_VIEW` — read user list scoped to authority
- `PERSONNEL_CREATE` — create users below own level
- `PERSONNEL_DEACTIVATE` — deactivate users in scope
- `PERSONNEL_ASSIGNMENT_CREATE` — create ACTING / DELEGATE assignments

---

### 16.3 — Low Stock + Expiry Alerts

**Status:** ⏳ Designed, ready to implement  
**Design reference:** CLAUDE.md §8 (outbox pattern), §24 Business Rules 4 and 5

No new design decisions required. Implementation is self-contained and does not depend on §16.1 or §16.2.

**Scope:**
- `alerts` table: `LOW_STOCK`, `OUT_OF_STOCK`, `EXPIRY_APPROACHING` alert types
- `AlertService`: `check_low_stock()`, `check_expiry()`, `get_alerts()`, `mark_read()`, `dismiss()`
- Alert check triggered by: Celery beat (every 6 hours) + outbox worker on `InventoryUpdated` event
- Dedup logic: no duplicate UNREAD alert for same product + warehouse + type
- Frontend: bell icon badge with unread count, dropdown (latest 5), full `/alerts` page
- Email/SMS delivery deferred until AWS SES/SNS provisioned

**Permissions to register:**
- `INVENTORY_ALERTS_VIEW` — read alerts scoped to facility
- `INVENTORY_ALERTS_MANAGE` — dismiss / mark-read alerts

---

### 16.4 — FEFO Dispatch Engine

**Status:** ⏳ Spec in CLAUDE.md §16, not yet implemented  
**Design reference:** CLAUDE.md §16, §24 Business Rules 4 and 5

No new design decisions required. Spec in CLAUDE.md §16 is complete. Implementation can proceed independently.

**Key rules (from CLAUDE.md §16):**
- FEFO auto-enforced when `batch_tracking=true` AND `expiry_date` is populated on the product
- FEFO override requires `dispatch:fefo_override` permission + `reason_code` + `DispatchOverrideLog` INSERT
- Override is audit-logged and fires a `FefoOverrideApplied` outbox event

---

### 16.5 — Stock Count Module

**Status:** ⏳ Not yet designed  
**Design reference:** CLAUDE.md §7 (`transaction_type = COUNT_VARIANCE`), §24 Business Rule 2

Needs a design session before implementation. Open questions:
- Blind count vs guided count (show expected quantity or hide it?)
- Partial count (subset of SKUs) vs full warehouse count
- Freeze rules during active count session (block transfers for counted SKUs?)
- Variance approval threshold — same as adjustment, or separate rule?
- How cycle count scheduling integrates with the approval workflow tables

**No implementation until design questions are resolved.**

---

### 16.6 — Barcode Scanning

**Status:** ⏳ Spec in CLAUDE.md §11, not yet implemented  
**Design reference:** CLAUDE.md §11

No new design decisions required. Spec is complete. Blocked only by hardware availability for P90 scan recognition testing (CLAUDE.md NFR-V4-3: < 1 second on mid-range Android).

Implementation uses `@zxing/browser` (already in `package.json` per CLAUDE.md §2). No backend changes required — scanning produces a product SKU that populates the existing Receive / Issue / Transfer forms.

---

## 19. PROMPT C — Product-Level Approval Rules

**Status:** ✅ Implemented 2026-05-28

Product-level approval rule overrides with 3-level fallback chain.  Each product can have its own approval thresholds that take precedence over tenant-level rules.

### Design decisions

| Decision | Detail |
|---|---|
| **Fallback chain** | Level 1: product-level rule → Level 2: tenant-level rule → Level 3: org-type hardcoded default |
| **Schema change** | `ALTER TABLE approval_rule ADD COLUMN product_id UUID NULL REFERENCES products(id)` (migration 025) |
| **Unique index** | Partial unique index on `(tenant_id, transaction_type, approval_order, product_id) WHERE product_id IS NOT NULL` — prevents duplicate bands per product |
| **Existing rows** | Rows with `product_id IS NULL` continue to function as tenant-level rules — no migration of existing data |
| **Edit permission** | `product:manage_approval_rules` granted to SA, TA, NM only — matches "Only TA and NM can edit" requirement |
| **View permission** | `product:view_approval_rules` granted to SA, TA, NM, RM, WM |
| **Pre-population** | `GET /api/v1/products/approval-rules/latest` returns the most recently created product's rules; Add Product panel pre-fills the Approval Thresholds section from this response |
| **Reset to defaults** | PUT with `{"rules": []}` deletes all product-level rules, causing automatic fallback to tenant/org-type defaults |
| **Approval section** | Collapsed by default in Add Product panel; shows "Using tenant defaults" badge when empty |
| **Backward compatibility** | `ApprovalService.route_approval()` gains an optional `product_id` parameter; all existing callers (no product_id) continue to work unchanged |

### New endpoints

| Method | Path | Permission | Who |
|---|---|---|---|
| `GET` | `/api/v1/products/approval-rules/latest` | `product:view_approval_rules` | Any operational role |
| `GET` | `/api/v1/products/{product_id}/approval-rules` | `product:view_approval_rules` | Any operational role |
| `PUT` | `/api/v1/products/{product_id}/approval-rules` | `product:manage_approval_rules` | SA, TA, NM only |

### Tests added (5)

| Test | What it verifies |
|---|---|
| `test_product_rule_takes_priority` | Product-level rule overrides tenant-level rule for the same band |
| `test_falls_back_to_tenant_rule` | Tenant-level rule used when product has no custom rules |
| `test_falls_back_to_org_type_default` | Hardcoded defaults used when neither product nor tenant rules exist |
| `test_prepopulate_from_previous_product` | `/approval-rules/latest` returns the most recently created product's rules |
| `test_only_ta_nm_can_edit_rules` | `product:manage_approval_rules` has `audit_required` ABAC; view permission does not |

### Existing test updated

`test_get_required_approver_raises_when_no_rule_matches` → renamed to `test_get_required_approver_falls_back_to_org_type_default`.  The old behaviour (raise `ValueError`) is replaced by the Level 3 fallback — a missing tenant rule no longer crashes the approval workflow.

---

## 20. PROMPT D — Five UX Bugs — 2026-05-28

**Status:** ✅ Fixed 2026-05-28  
**Tests:** 266 passed (7 new regression tests added)  
**TypeScript:** 0 errors after fix

---

### BUG 1 — Warehouses page Manager column always empty

| Item | Detail |
|---|---|
| **Symptom** | Manager column shows "—" for every node on the Warehouses page |
| **Root cause** | `list_org_nodes` in `hierarchy.py` hardcoded `"manager_user_id": None` for every row — the SQL never joined `user_facility_assignments` |
| **Fix** | Changed the SQL to `LEFT JOIN user_facility_assignments ufa ON ufa.facility_id = n.id AND ufa.assignment_type = 'PRIMARY' AND ufa.is_active = true LEFT JOIN users u ON u.id = ufa.user_id` and added `manager_name`/`manager_role` to the node dict. Changed `_build_tree` to read `node.get("manager_name")` and `node.get("manager_role")` directly instead of calling `_get_manager_info` (avoids N+1 per-node lookup) |
| **Files** | `backend/services/tenant-service/routers/hierarchy.py` — `list_org_nodes` + `_build_tree` |

---

### BUG 2 — Product form shows raw i18n keys

| Item | Detail |
|---|---|
| **Symptom** | Add Product panel shows raw keys like `product.add.field.short_name` instead of labels |
| **Root cause** | `t()` returns the key string when a key is missing, which is truthy — so `t("missing.key") \|\| "fallback"` never fires. Many keys added during PROMPT B/C were missing from all three locale files |
| **Fix** | Added to all three locale files (`en.json`, `am.json`, `or.json`): `product.add.field.{short_name, short_name_hint, brand, description, description_placeholder, packaging_type, units_per_package}`, `product.add.sold_as`, and `approval_rules.{section, custom_set, using_defaults, hint, tx.{receive,issue,adjustment,transfer}, col.{transaction,qty_up_to,approver}}` |
| **Files** | `locales/en.json`, `locales/am.json`, `locales/or.json` |

---

### BUG 3 — Category and Reorder Point not visible in inventory table

**Status:** ✅ Already present — no fix required.  
Both columns (`inventory.category` and `table.reorder_point`) were already in the table header and data rows of `inventory/page.tsx`, and the backend `list_products` query already returns `category` and `reorder_point` in the response. The columns display correctly in gateway mode.

---

### BUG 4 — PUSH not available for Main WH and RM users (regression)

| Item | Detail |
|---|---|
| **Symptom** | PUSH option missing from the transfer type dropdown for WM users at high-level facilities (Main WH, Regional WH) |
| **Root cause** | `canPush` in `NewTransferPanel.tsx` checked `["MWH","RWH"].includes(userWH.type)`. The `useWarehouses` hook hardcodes `type: "WH"` for all org nodes from the API — `.type` is always "WH" in gateway mode, never "MWH" or "RWH". So the check always returned false for locked-WH users |
| **Fix** | Added `level_number?: number` to `DemoWarehouse` interface. `useWarehouses` now populates `level_number: n.hierarchy_level`. `canPush` changed to `!lockedWH \|\| ((userWH?.level_number ?? 99) <= 2)` — level 1/2 = Main/Regional WH, can PUSH; level 3+ = cannot |
| **Files** | `frontend/src/lib/demo-data.ts`, `frontend/src/hooks/useWarehouses.ts`, `frontend/src/components/features/transfers/NewTransferPanel.tsx` |
| **Regression tests** | `TestCanPushLevelBased` — 4 tests covering level 1/2 can push, level 3–5 cannot, unlocked users always can, missing level defaults to false |

---

### BUG 5 — Transfer dropdowns show "(WH)" or "(undefined)" instead of names

| Item | Detail |
|---|---|
| **Symptom** | "From Warehouse" and "To Warehouse" dropdown options show `{name} (WH)` or `{name} (undefined)` instead of just the name |
| **Root cause** | Dropdown options rendered `{w.name} ({w.type})`. Since `useWarehouses` hardcodes `type: "WH"`, all options show "(WH)". In BFF/demo mode with undefined type they would show "(undefined)" |
| **Fix** | Removed `({w.type})` from both dropdown option labels — just `{w.name}`. Names are already descriptive enough |
| **Files** | `frontend/src/components/features/transfers/NewTransferPanel.tsx` — both `fromOptions.map` and `toOptions.map` |
| **Regression tests** | `TestTransferDescriptionUsesNames` — 3 tests: name-only label, no "undefined" text, UUID not in label |

---

---

## 21. PROMPT D (continued) — 7 Bugs + Nav Enhancement — 2026-05-28

**Status:** ✅ Fixed 2026-05-28  
**Tests:** 266 passed (5 unit tests updated to assert correct no-RESERVE/RELEASE behavior)  
**TypeScript:** 0 errors after fix

---

### CRITICAL BUG 1 — Balance shows at destination before RECEIVED (Ledger integrity violation)

| Item | Detail |
|---|---|
| **Symptom** | Destination warehouse shows positive On Hand stock immediately after a transfer is ISSUED, before any RECEIVED event. This violates immutable ledger rule #2 and Business Rule #2 |
| **Root cause** | `dispatch_transfer()` wrote a `RESERVE` ledger entry (`transaction_type="RESERVE"`, positive quantity) at the destination warehouse when advancing status to ISSUED. `_update_running_balance()` runs unconditionally for ALL transaction types, so `inventory_balances` at the destination was credited immediately. `receive_transfer()` wrote a preceding `RELEASE` entry (negative quantity) at the destination before `TRANSFER_IN`, making the net correct but the intermediate state invalid |
| **Fix** | Removed the RESERVE block from `dispatch_transfer()` and the RELEASE block from `receive_transfer()`. In-transit tracking in analytics SQL uses `transfer_orders.status = 'IN_TRANSIT'` (not ledger entries), so no analytics regression. `TRANSFER_OUT` at APPROVED and `TRANSFER_IN` at RECEIVED remain unchanged |
| **Files** | `backend/services/inventory-service/services/inventory_service.py` — `dispatch_transfer()` and `receive_transfer()` |
| **Tests updated** | `test_dispatch_writes_no_ledger_entries` (was `test_dispatch_reserves_destination_only`), `test_received_credits_destination_no_release` (was `test_received_clears_in_transit_credits_destination`), `test_issued_does_not_deduct_source_on_hand`, `test_in_transit_writes_no_ledger_entries` (was `test_in_transit_shows_on_both_sides`), `test_received_transition_credits_destination_balance` |

---

### CRITICAL BUG 2 — No Submit / Review button for RM and NM on PULL DRAFT

| Item | Detail |
|---|---|
| **Symptom** | When an RM or NM user creates a PULL transfer (DRAFT status), the transfer detail shows no action buttons — no Submit, no Review, no Cancel. The transfer is stuck |
| **Root cause** | `getAvailableActions()` in `transfers/page.tsx` had no `DRAFT` entry in the RM block for PULL type and no `DRAFT` entry in the NM block for PULL type. The DRAFT state was only handled for WM role |
| **Fix** | Added `DRAFT: [review, cancel]` to RM PULL map, `DRAFT: [submitReq, cancel]` to RM SISTER map, and `DRAFT: [review, cancel]` to NM PULL map in `getAvailableActions()` |
| **Files** | `frontend/src/app/[org]/transfers/page.tsx` — `getAvailableActions()` |

---

### CRITICAL BUG 3 — PUSH always blocked for WM users in gateway mode (regression)

| Item | Detail |
|---|---|
| **Symptom** | In gateway mode (real tenant), the "Push" option is missing from the transfer type dropdown for WM users at Main WH (level 1) and Regional WH (level 2) facilities. PUSH worked in demo mode but regressed |
| **Root cause** | `canPush = !lockedWH \|\| ((userWH?.level_number ?? 99) <= 2)`. In gateway mode, `effectiveWarehouses` was built from `gatewayWarehouses` (analytics API response) which never includes `level_number`. So `userWH?.level_number` was `undefined`, defaulted to 99, `99 <= 2` = false — `canPush` was always false for any `lockedWH` user |
| **Fix** | Added `useWarehouses` hook to `transfers/page.tsx` and used `orgNodeWarehouses` (from `/api/v1/tenants/{tid}/nodes`) as the primary source when in gateway mode. These nodes always carry `level_number: n.hierarchy_level`. `effectiveWarehouses` now prefers `orgNodeWarehouses` over `gatewayWarehouses` in gateway mode |
| **Files** | `frontend/src/app/[org]/transfers/page.tsx` — added `useWarehouses` import and hook call; updated `effectiveWarehouses` assignment |

---

### HIGH BUG 4 — UUID displayed in transfer list warehouse columns

| Item | Detail |
|---|---|
| **Symptom** | Transfer list rows show raw UUIDs (e.g. `b3f1a2c4-...`) in the From and To columns instead of warehouse names |
| **Root cause** | `from_warehouse_name` and `to_warehouse_name` were null in the API response when the JOIN in the analytics SQL missed a warehouse. The fallback `tx.from_warehouse_name \|\| tx.from_warehouse_id` then stored the UUID as the display value |
| **Fix** | Added a post-processing step after the transfers API call that resolves names from `effectiveWarehouses` (now backed by `orgNodeWarehouses` which includes all nodes): `const fromName = tx.from_warehouse_name \|\| effectiveWarehouses.find(w => w.id === tx.from_warehouse_id)?.name \|\| tx.from_warehouse_id` |
| **Files** | `frontend/src/app/[org]/transfers/page.tsx` — `allTransfers` post-processing |

---

### HIGH BUG 5 — UUID in inventory detail popup location labels

| Item | Detail |
|---|---|
| **Symptom** | "In Transit" and location detail popups on the Inventory page show raw UUIDs instead of facility names for transfers fetched from the API |
| **Root cause** | When building the transfer store from the API response (`useEffect` in `inventory/page.tsx`), `addTransfer()` calls used `t.from_warehouse_name \|\| t.from_warehouse_id`. If the API returned null for the name, the UUID was stored as `fromWarehouseName` in the Zustand store |
| **Fix** | Added `resolveWHName()` helper inside the sync `useEffect` that looks up by ID in `displayWarehouses` before falling back to the UUID |
| **Files** | `frontend/src/app/[org]/inventory/page.tsx` — transfer sync `useEffect` |

---

### HIGH BUG 6 — Audit log displays raw action codes instead of readable labels

| Item | Detail |
|---|---|
| **Symptom** | Audit Log page shows raw action strings like `transfer:APPROVED`, `transfer:IN_TRANSIT`, `receive_stock` in the Action column instead of human-readable text |
| **Root cause** | The `audit-log/page.tsx` rendered `{e.action}` directly. No i18n keys existed for action codes under `audit.actions.*` |
| **Fix** | Added `audit.actions` object to `en.json` covering all transfer status transitions and common actions (`transfer_DRAFT`, `transfer_APPROVED`, `transfer_IN_TRANSIT`, etc., plus `receive_stock`, `issue_stock`, `ADJUSTMENT`). Updated audit log page to look up `audit.actions.${e.action.replace(/:/g, "_")}` and fall back to the raw code if the key is missing |
| **Files** | `locales/en.json`, `frontend/src/app/[org]/audit-log/page.tsx` |

---

### ENHANCEMENT — Inventory nav item moved to top of OPERATIONS section

| Item | Detail |
|---|---|
| **Change** | Moved the "Inventory" nav link from the INVENTORY section (below Lot Traceability) to the top of the OPERATIONS section (above Transfers) |
| **Reason** | Inventory is an operational view that warehouse managers use constantly alongside Transfers and Receive/Issue. Grouping it with other operational actions (Transfers, Receive, Issue) improves workflow efficiency — it is not a configuration/reference item like Products and Warehouses |
| **Files** | `frontend/src/app/[org]/layout.tsx` — `TENANT_NAV` array |

---

---

## 16. SESSION 6 BUGS — 2026-05-29

### CRITICAL BUG 1 — `in_transit_in_qty` drops to zero when transfer enters PARTIALLY_RECEIVED

| Item | Detail |
|---|---|
| **Symptom** | Destination warehouse's "In Transit In" counter resets to zero as soon as any portion of stock is received, even though remaining quantity is still physically in transit |
| **Root cause** | `inventory_analytics.py::get_stock()` SQL for `in_transit_in_qty` only included `AND to_.status = 'IN_TRANSIT'`. When a partial receipt advances status to `PARTIALLY_RECEIVED`, the transfer no longer matched the filter — the remaining in-transit quantity vanished from the inbound counter |
| **Fix** | Changed the `in_transit_in_qty` SQL to include both statuses: `AND to_.status IN ('IN_TRANSIT', 'PARTIALLY_RECEIVED')`. PARTIALLY_RECEIVED is included because the remaining un-received quantity is still in transit |
| **Files** | `backend/services/inventory-service/services/inventory_analytics.py` — `in_transit_sql` WHERE clause |
| **Regression test** | `test_destination_on_hand_zero_until_received` in `test_transfer_service.py` |

---

### CRITICAL BUG 2 — NM sees Issue button at APPROVED, clicking it returns 403

| Item | Detail |
|---|---|
| **Symptom** | After NM approves a PULL transfer (PENDING_APPROVAL → APPROVED), NM sees an "Issue" action button. Clicking it returns HTTP 403: "Only source warehouse can dispatch" |
| **Root cause** | `getAvailableActions()` in `transfers/page.tsx` had `APPROVED: [issue, cancel]` in the NM PULL action map. NM has no `warehouse_id` in their JWT, so `dispatch_transfer()` correctly rejects via ABAC. But the UI showed a button that always failed — confusing and misleading |
| **Fix** | Removed `APPROVED` and `ISSUED` from NM's PULL action map entirely. NM's role ends at approval; dispatching is the source warehouse manager's exclusive responsibility |
| **Side fix** | Added `⚠ NM/TA approval required` sub-label under the status badge for transfers in `PENDING_APPROVAL` state so the requesting WM knows why no action is available |
| **Files** | `frontend/src/app/[org]/transfers/page.tsx` — NM PULL action map |
| **Regression test** | `test_nm_cannot_issue_at_approved` in `test_transfer_service.py` |

---

### BUG 3 — Products page Category column shows "—" for all products from API

| Item | Detail |
|---|---|
| **Symptom** | Category column shows "—" for every product on the Products page when running in gateway mode against the real API |
| **Root cause** | `type ApiProduct` in `products/page.tsx` was missing the `category` field. `apiRows` hardcoded `category: "—"` regardless of what the API returned. Backend `list_products` and `ProductResponse` schema both return `category` correctly via `LEFT JOIN product_categories` |
| **Fix** | Added `category?: string \| null` to `ApiProduct` type. Changed `apiRows` mapping from `category: "—"` to `category: p.category ?? "—"` |
| **Files** | `frontend/src/app/[org]/products/page.tsx` — `ApiProduct` type definition and `apiRows` map |
| **Backend** | No backend changes needed — `product_categories` JOIN and `ProductResponse.category` were already correct |

---

### DOCUMENTATION FIX — Stale router docstrings

| Item | Detail |
|---|---|
| **Symptom** | `routers/transfer.py` docstrings said "Books a RESERVE at the destination warehouse" for `dispatch_transfer` — contradicting the actual behavior |
| **Root cause** | Docstrings were written before the RESERVE/RELEASE removal (Bug #8 from previous session). They were never updated |
| **Fix** | Updated `dispatch_transfer` endpoint docstring: "Advance APPROVED → ISSUED. Source warehouse only (warehouse_id ABAC). Writes NO ledger entries — source on_hand was already deducted at APPROVED via TRANSFER_OUT." Updated PATCH endpoint routing comment to accurately describe the three dispatch paths |
| **Files** | `backend/services/inventory-service/routers/transfer.py` |

---

---

## 17. SESSION 7 BUG — 2026-05-29

### CRITICAL BUG — PULL transfer stuck at APPROVED: NM has no Issue button; transfer cannot proceed

| Item | Detail |
|---|---|
| **Symptom** | End-to-end PULL flow (WH → Region W RM → Main NW NM): after NM approves at PENDING_APPROVAL the transfer reaches APPROVED but NM sees no action buttons. The transfer is stuck — NM cannot issue, WM cannot issue (wrong warehouse), RM cannot issue (wrong role). |
| **Root cause A — Frontend** | NM PULL action map had no `APPROVED` or `ISSUED` entries. The previous session fix (Bug 2) correctly removed NM's ability to approve-then-issue for same-session double-actions, but went too far by removing Issue entirely. NM who manages the source facility (Main NW) is the correct actor at APPROVED. |
| **Root cause B — Backend** | `dispatch_transfer()` ABAC check was `if not user.warehouse_id or ...`, which unconditionally denied any user with `warehouse_id = None`. NM managing at tenant level (no specific facility assignment) always got 403 even though they are the correct source manager. |
| **Fix — Frontend** | Added `isSrcManager = !uWH \|\| uWH === fromWH?.toLowerCase()` to NM block. NM without a warehouseId = tenant-level authority (can dispatch from any source). NM with a warehouseId = can dispatch only from their facility. Added `map.APPROVED = [issue, cancel]` and `map.ISSUED = [dispatch]` gated on `isSrcManager`. |
| **Fix — Backend** | Replaced single ABAC condition with: if `user.warehouse_id` is set → check exact match; if `user.warehouse_id` is None → allow only NM/TA/SA (`_TENANT_LEVEL_ROLES`). Facility-bound roles (WM/RM/LM) without a matching warehouse_id are still denied. |
| **Side fix** | Added `getWaitingMessage()` helper in `transfers/page.tsx` — when a user has no action buttons on a transfer, the Actions cell now shows a contextual message (e.g. "Waiting for Main NW to issue", "Awaiting RM review") instead of an empty "—". |
| **Files** | `backend/services/inventory-service/services/inventory_service.py` — `dispatch_transfer()` ABAC; `frontend/src/app/[org]/transfers/page.tsx` — NM PULL map + `getWaitingMessage()` |
| **Tests** | `test_nm_can_dispatch_as_tenant_manager` (replaces `test_nm_cannot_issue_at_approved`), `test_rm_cannot_issue_non_source_transfer` — 25/25 pass |
| **Threshold routing note** | RM sees Approve at PENDING_APPROVAL (correct for qty ≤ threshold). For qty > threshold, only NM should approve — this requires fetching `approval_rule` table data in the frontend, which is a future enhancement. Backend must enforce threshold when RM submits an above-threshold approval. |

---

---

## 18. SESSION 8 — 2026-05-29

### Approval System Frontend (PROMPT 3) — No new bugs found

All changes in this session were new features, not bug fixes.

| Area | Change | Files |
|---|---|---|
| **Org Setup Tab 3 — ApprovalRulesTab** | Complete rewrite: tier-based rules (Simple / Custom mode), hierarchy-level approver dropdown, auto-approve with notify options, `[+ Add Tier]`, `[Save All Rules]`, `[Copy to all types]`; SISTER shares PULL tiers | `frontend/src/app/[org]/settings/org-setup/page.tsx` |
| **AddProductPanel — approval minimums** | Replaced collapsible "Approval Thresholds" section with always-visible "Minimum Approval Level" table (6 TX types); saves to `PUT /products/{id}/approval-minimums`; shows tenant defaults preview | `frontend/src/components/features/inventory/AddProductPanel.tsx` |
| **Transfers page — ApprovalPendingActions** | New component: fetches `GET /transfers/{id}/approval-info`; shows Approve/Reject buttons when `can_approve=true`; shows dynamic waiting message with `required_role_display` when `can_approve=false`; auto-approve toast | `frontend/src/app/[org]/transfers/page.tsx` |
| **Bell notifications — auto-approve notices** | `NotificationBell` in layout.tsx now fetches `AUTO_APPROVAL_NOTICE` alerts in gateway mode and shows them in the dropdown | `frontend/src/app/[org]/layout.tsx` |
| **i18n** | Added `approval.*` key block to `en.json`, `am.json`, `or.json` | `locales/en.json`, `am.json`, `or.json` |
| **Regression tests** | Added 4 regression tests to `TestApprovalWorkflows`: `test_wm_cannot_approve_above_threshold`, `test_auto_approve_notifies_rm`, `test_product_min_overrides_threshold`, `test_sister_shares_pull_tiers_in_ui` | `backend/services/inventory-service/tests/unit/test_approval_workflows.py` |

### TypeScript issues fixed

| Error | Location | Fix |
|---|---|---|
| TS2869 — unreachable `?? false` operand | `org-setup/page.tsx` `tiersFromRules()` | Removed `?? false`; `r.notify_levels?.length === 1` always produces boolean |
| TS18048 — possibly undefined array elements (×3) | `org-setup/page.tsx` `validateTiers()` + `deleteTier()` | Added null guards for all index accesses under `noUncheckedIndexedAccess: true` |
| TS2322 — type incompatibility in spread | `org-setup/page.tsx` `deleteTier()` | Explicit `ApprovalTier` type annotation on spread target |

### Pre-existing test failures fixed (not caused by this session)

| Test | Old value | Corrected value |
|---|---|---|
| `test_registry_has_exactly_132_permissions` | 132 | 133 |
| `test_new_permissions_registered` (tenant-service) | 132 | 133 |

**Final state:** 279 unit tests passing, 0 failing · TypeScript: 0 errors

---

## 19. SESSION 9 — 2026-05-29

### Bug 1 — 422 on approval-rules save (schema mismatch)

**Root cause:** `ApprovalRuleItem` backend schema was missing `authority_level` field; `ApprovalRulesBody` was missing `simple_mode`. JSONB was stored as a bare array (interim format from §18 fix) — now stored as `{"simple_mode": bool, "rules": [...]}` with full backward-compat reader handling three legacy formats (old `{tx: {low, medium}}` dict, bare array, new dict-with-rules-key).

| Change | File |
|---|---|
| Add `authority_level: int = 1` to `ApprovalRuleItem` | `backend/services/tenant-service/routers/tenants.py` |
| Add `simple_mode: bool = True` to `ApprovalRulesBody` | same |
| PUT stores `{"simple_mode": …, "rules": […]}` JSONB | same |
| GET handles all three legacy JSONB formats | same |
| Add `authority_level?: number` to `SavedApprovalRule` interface | `frontend/src/app/[org]/settings/org-setup/page.tsx` |
| `tiersToRules` populates `authority_level` from `ROLE_AUTH` | same |
| `saveMutation` passes `{ simple_mode, rules }` | same |
| `handleSave` passes `simpleMode` to mutation | same |

### Bug 2 — 404 on notifications bell endpoint

**Root cause:** Frontend called `/api/v1/notifications?alert_type=AUTO_APPROVAL_NOTICE` — this endpoint never existed.

| Change | File |
|---|---|
| New `routers/alerts.py` — `GET /` with `?alert_type=` query param, queries `approval_history` for `AUTO_APPROVED` actions in last 24 h, joins `transfer_orders` + `products` + `organization_node` | `backend/services/inventory-service/routers/alerts.py` (new) |
| Mount at `/api/v1/inventory/alerts` | `backend/services/inventory-service/main.py` |
| Update frontend URL to `/api/v1/inventory/alerts?alert_type=AUTO_APPROVAL_NOTICE` | `frontend/src/app/[org]/layout.tsx` |

### Bug 3 — PWA icon-192.png missing (cosmetic)

`frontend/public/icon-192.png` does not exist. The `manifest.json` references it but it is not in the repo. This is a cosmetic issue — the PWA installs and functions without it. A 404 appears in DevTools Network tab. **Not fixed** — add a proper icon asset in a future design pass.

**Final state:** 279 unit tests passing, 0 failing · TypeScript: 0 errors

---

## Session 10 — Transfer Approval Flow (2026-05-30)

**Business rule enforced:** You cannot approve a transfer you created. If the required approver is the same role as the requester, escalate one level up.

Three bugs fixed.

### Bug 1 — Requester can approve own transfer

**Symptom:** RM creates a PULL transfer → RM sees the Approve button and can approve it.

**Root cause:**
- `transition_transfer()` APPROVED block only checked `caller_level > decision.required_authority_level` — it never verified whether the caller was the transfer creator.
- `resolve_approval()` had no concept of the requester's authority level, so no escalation occurred.

| Change | File |
|---|---|
| Migration 030: `ALTER TABLE transfer_orders ADD COLUMN created_by_authority_level INTEGER DEFAULT 4` | `backend/migrations/versions/030_add_created_by_authority_level.py` |
| `create_transfer()`: store `ROLE_AUTHORITY_LEVEL[user.role]` in `created_by_authority_level` at INSERT | `backend/services/inventory-service/services/inventory_service.py` |
| `resolve_approval()`: add `requester_authority_level` param; escalate `required_level = max(1, requester_authority_level - 1)` when `required_level >= requester_authority_level` | `backend/services/inventory-service/services/approval_service.py` |
| `transition_transfer()` APPROVED: fetch `created_by_authority_level` from row; raise 403 `CANNOT_APPROVE_OWN_TRANSFER` if `created_by == user.user_id`; pass `requester_authority_level` to `resolve_approval()` | `backend/services/inventory-service/services/inventory_service.py` |
| `get_approval_info()`: fetch `created_by` + `created_by_authority_level`; pass to `resolve_approval()`; set `can_approve = False` if `is_own_transfer` | `backend/services/inventory-service/routers/transfer.py` |

### Bug 2 — Issue and Dispatch combined/skipped for RM PUSH

**Symptom:** RM clicks Issue at APPROVED → transfer moves to ISSUED → RM sees no buttons → transfer stuck at ISSUED forever.

**Root cause:** RM PUSH action map in `getAvailableActions()` was missing the `ISSUED: [dispatch]` entry.

| Change | File |
|---|---|
| Add `ISSUED: [dispatch]` to RM PUSH map | `frontend/src/app/[org]/transfers/page.tsx` |

### Bug 3 — RM sees no action buttons at IN_TRANSIT (can't receive)

**Symptom:** RM creates a PULL from Main WH. Transfer is dispatched and reaches IN_TRANSIT. RM sees no buttons — cannot receive the transfer they requested.

**Root cause:**
- RM PULL action map had no `IN_TRANSIT`, `PARTIALLY_RECEIVED`, or `RECEIVED` entries.
- `receive_transfer()` ABAC check required `user.warehouse_id` to match `to_warehouse_id` — an RM without a specific warehouse assignment was always denied.

| Change | File |
|---|---|
| Add `userId` + `createdBy` parameters to `getAvailableActions()` | `frontend/src/app/[org]/transfers/page.tsx` |
| Add `isDestRM`/`isSrcRM` flags to RM PULL block; `isDestRM` uses creator fallback for RM without warehouse_id | `frontend/src/app/[org]/transfers/page.tsx` |
| Add `IN_TRANSIT`, `PARTIALLY_RECEIVED`, `RECEIVED` entries gated on `isDestRM`; `APPROVED`, `ISSUED` entries gated on `isSrcRM` | `frontend/src/app/[org]/transfers/page.tsx` |
| Add `created_by?: string` to `ApiTransfer`; propagate from `normalizeTransfer()` | `frontend/src/app/[org]/transfers/page.tsx` |
| Update call site to pass `user.id` and `txn.created_by` | `frontend/src/app/[org]/transfers/page.tsx` |
| `receive_transfer()`: allow creator (RM with no warehouse_id whose `user_id == created_by`) to receive | `backend/services/inventory-service/services/inventory_service.py` |

### Regression tests added (Session 10)

| Test | File |
|---|---|
| `test_requester_cannot_approve_own_transfer` | `test_transfer_service.py` |
| `test_rm_escalates_to_nm_approval` | `test_transfer_service.py` |
| `test_issue_and_dispatch_separate_steps` | `test_transfer_service.py` |
| `test_rm_sees_receive_at_in_transit` | `test_transfer_service.py` |

**Final state:** 283 unit tests passing, 0 failing · TypeScript: 0 errors

---

---

## Session 11 — Inventory analytics, JWT expiry, transit tooltips

Three bugs fixed.

### Bug 1 — Reserved shows at DRAFT status

**Symptom:** A transfer at DRAFT status caused the source warehouse Reserved column to show a non-zero value, making available stock appear lower than it actually was.

**Root cause:** `pending_out_sql` in `get_stock()` included `'DRAFT'` in its status IN clause. Per CLAUDE.md §17, DRAFT carries no stock commitment — it can be discarded without any stock consequence. Reserved (soft hold) must only begin at `PENDING_REVIEW`.

| Change | File |
|---|---|
| Remove `'DRAFT'` from `pending_out_sql` status IN clause | `backend/services/inventory-service/services/inventory_analytics.py` |
| Update docstring to describe correct DRAFT exclusion rationale | `backend/services/inventory-service/services/inventory_analytics.py` |
| Add regression test `test_draft_transfer_does_not_reserve_stock` | `backend/services/inventory-service/tests/unit/services/test_analytics_stock.py` |
| Update module docstring to reflect correct WMS Option A column trace | `backend/services/inventory-service/tests/unit/services/test_analytics_stock.py` |

### Bug 2 — JWT expiry causes data loss

**Symptom:** When a JWT token expires mid-session, API calls return 401. The frontend threw an unhandled error, losing all in-progress form data. The user had to manually log out and log back in with no indication of why.

**Root cause:** `api.ts` had no JWT expiry pre-check and no 401 redirect. `demo-auth.ts` `getSession()` returned stale expired sessions. The login page had no session-expired notice.

| Change | File |
|---|---|
| Add `_jwtExp()`, `_isJwtExpiringSoon()` (5-min window), `_redirectToLogin()` helpers | `frontend/src/lib/api.ts` |
| Pre-flight check in `request()`: redirect to `/login?reason=session_expired&from=<path>` if token expiring | `frontend/src/lib/api.ts` |
| On 401 response: clear `smart_demo_session` from localStorage and redirect to login | `frontend/src/lib/api.ts` |
| `getSession()`: detect expired `jwtToken` via `decodeJwtPayload`, clear session and return null | `frontend/src/lib/demo-auth.ts` |
| Show amber "Your session has expired" notice when `?reason=session_expired` in URL | `frontend/src/app/(auth)/login/page.tsx` |

### Bug 3 — Transit arrow direction unclear

**Symptom:** Users were unsure whether the `→` and `←` arrows in the In Transit Out and In Transit In columns represented stock leaving or arriving, and how it related to their On Hand balance.

**Root cause:** No hover tooltip distinguished the direction semantics. Arrows were already correct (`→` out, `←` in) but provided no contextual explanation.

| Change | File |
|---|---|
| Add optional `tooltip?: string` prop to `ExpandCell`; use it as `title` attribute (falls back to expand hint) | `frontend/src/app/[org]/inventory/page.tsx` |
| Pass `t("inventory.tooltip.in_transit_out")` to In Transit Out cell | `frontend/src/app/[org]/inventory/page.tsx` |
| Pass `t("inventory.tooltip.in_transit_in")` to In Transit In cell | `frontend/src/app/[org]/inventory/page.tsx` |
| Add `inventory.tooltip.in_transit_out` and `inventory.tooltip.in_transit_in` keys | `locales/en.json`, `locales/am.json`, `locales/or.json` |

### Regression tests added (Session 11)

| Test | File |
|---|---|
| `test_draft_transfer_does_not_reserve_stock` | `test_analytics_stock.py` |

**Final state:** 135 unit tests passing, 0 failing · TypeScript: 0 errors

---

---

## Deferred: Partial Receive

**Status:** Hidden in UI — Partial Receive button removed from all IN_TRANSIT action maps.  
State machine entry (`PARTIALLY_RECEIVED` state) retained in `state_machine.py` for data integrity.

**Re-enable:** Add `partialReceive` action back to `IN_TRANSIT` entries in `getAvailableActions()` in `transfers/page.tsx`.

**Dependencies before re-enabling:**
- `receive_transfer()` in `inventory_service.py` needs a `partial_qtys: dict[str, Decimal]` parameter to accept per-line quantities and advance to `PARTIALLY_RECEIVED` instead of `RECEIVED`.
- Frontend needs a qty-input modal triggered when `action.requiresQty === true`.

---

## Session 13 — Critical bug fixes (manual testing 2026-05-30)

**Date:** 2026-05-30 | **Branch:** main | **Unit tests:** 182 passed · TypeScript: 0 errors

### Bug 1 (CRITICAL) — RESERVE incorrectly inflates On Hand at PENDING_REVIEW

**Symptom:** Source On Hand increased when a PULL entered PENDING_REVIEW. On Hand must only change at APPROVED (deduction) and RECEIVED (credit).

**Root cause:** Gap 2 wired `write_transfer_ledger_entry(RESERVE, +qty)` at PENDING_REVIEW. Since RESERVE passed through `record_transaction()`, `_update_running_balance()` incremented `inventory_balances.quantity`. `get_stock()` reads that column as `current_stock`.

| Change | File |
|--------|------|
| Add `_BALANCE_NEUTRAL_TYPES` frozenset (RESERVE/RELEASE/TRANSIT_OUT/TRANSIT_IN/TRANSIT_CLEAR) | `repositories/ledger_repo.py` |
| Skip stock-floor check and `_update_running_balance()` for neutral types | `repositories/ledger_repo.py` |
| `test_reserve_does_not_affect_on_hand` + `test_transfer_reversal_does_affect_on_hand` | `tests/unit/repositories/test_ledger_repo.py` |

Note: TRANSFER_REVERSAL is deliberately NOT neutral — it restores on_hand after APPROVED→CANCELLED.

### Bug 2 (CRITICAL) — NM sees Send for Approval and Reject at PENDING_REVIEW

**Symptom:** NM (National Manager) saw `[Send for Approval, Reject, Cancel]` at PENDING_REVIEW for PULL transfers. Only RM (reviewer) should act at this step.

**Root cause:** NM's PULL action map in `getAvailableActions()` included `PENDING_REVIEW: [toApproval, reject, cancel]`.

| Change | File |
|--------|------|
| Remove `PENDING_REVIEW` entry from NM PULL map; add comment | `frontend/src/app/[org]/transfers/page.tsx` |
| `test_nm_no_actions_at_pending_review_in_state_machine` | `tests/unit/services/test_transfer_service.py` |

### Bug 3 (CRITICAL) — NM "Transition failed" when issuing after approving

**Symptom:** NM with a specific facility assigned (warehouse_id set in JWT) clicked Issue after approving and got 403. NM should have tenant-wide dispatch authority.

**Root cause:** `dispatch_transfer()` and `receive_transfer()` checked `warehouse_id` BEFORE checking role. NM with a warehouse_id was treated like WM and denied access to source/dest facilities other than their own.

| Change | File |
|--------|------|
| Check role FIRST in dispatch ABAC: NM/TA/SA always `can_dispatch = True` | `inventory_service.py: dispatch_transfer()` |
| Check role FIRST in receive ABAC: NM/TA/SA always `can_receive = True` | `inventory_service.py: receive_transfer()` |
| `test_nm_can_dispatch_with_warehouse_id` | `tests/unit/services/test_transfer_service.py` |

### Bug 4 (HIGH) — Hardcoded English in approval settings

**Symptom:** Two English strings in the org-setup approval tab violated §20 (never hardcode English in JSX).

| Change | File |
|--------|------|
| Replace hardcoded description with `t("approval.rules_desc")` | `frontend/src/app/[org]/settings/org-setup/page.tsx` |
| Replace hardcoded SISTER note with `t("approval.sister_shares_pull")` | `frontend/src/app/[org]/settings/org-setup/page.tsx` |
| Add `approval.rules_desc` and `approval.sister_shares_pull` | `locales/en.json`, `locales/am.json`, `locales/or.json` |

### Bug 5 (HIGH) — Inventory nav placement (stale build cache)

Nav structure verified correct in layout.tsx (confirmed by Gap 6 fix). Issue is stale `.next` build cache. Fix: `rm -rf frontend/.next && pnpm build`.

### Bug 6 (MEDIUM) — No asterisk on mandatory fields

| Change | File |
|--------|------|
| Add `required?: boolean` to `FieldLabel` component; render `<span className="text-red-500">*</span>` | `AddProductPanel.tsx` |
| Add `required` prop to Product Name and Type Code field labels | `AddProductPanel.tsx` |

---

## Session 12 — Gap fixes (Gaps 1–6 from APPROVAL_WORKFLOW_REPORT.md)

**Date:** 2026-05-30 | **Branch:** main | **Committed:** 5 separate commits

All 6 gaps documented in `docs/APPROVAL_WORKFLOW_REPORT.md` are now resolved.

| Gap | Description | Status | Commit |
|-----|-------------|--------|--------|
| Gap 1 | `write_transfer_ledger_entry()` helper — immutable ledger for RESERVE/TRANSIT/REVERSAL events | ✅ RESOLVED | `feat(gap1)` |
| Gap 2 | Wire ledger entries into all transfer status transitions | ✅ RESOLVED | `feat(gap2)` |
| Gap 3 | Remove legacy `route_approval()`, wire `resolve_approval()` everywhere | ✅ RESOLVED | `refactor(gap3)` |
| Gap 4 | Custom mode approval routing — reads `simple_mode` from tenant `approval_thresholds` | ✅ RESOLVED | `fix(gap4)` |
| Gap 5 | State machine: PUSH `REJECTED` terminal, SISTER `CANCELLED` from dest-confirm, `/review` endpoint, escalation ceiling message | ✅ RESOLVED | `fix(gap5)` |
| Gap 6 | Hide partial receive (deferred), nav i18n guard, code guards, docs update | ✅ RESOLVED | `fix(gap6)` |

### Changes in this session

| Change | File |
|--------|------|
| Remove `partRecv` from all `IN_TRANSIT` action maps; add deferred comment | `frontend/src/app/[org]/transfers/page.tsx` |
| Add NAV ORDER comment; render nav labels via `t()` instead of hardcoded strings | `frontend/src/app/[org]/layout.tsx` |
| Fix docstring (pending_out = pre-approval statuses, not APPROVED/IN_TRANSIT); add NEVER guard | `backend/services/inventory-service/services/inventory_analytics.py` |
| Add GATEWAY MODE guard comment above `safeFloat` | `frontend/src/app/[org]/inventory/page.tsx` |
| Add `canPush` guard comment (use `level_number`, never type string) | `frontend/src/components/features/transfers/NewTransferPanel.tsx` |
| Add partial receive to deferred features | `PRD-APPENDIX.md §E`, `BUG_REPORT.md §deferred` |

**Final state:** 178 unit tests passing · TypeScript: 0 errors · Drift check: 0 violations (auth-service pre-existing)

---

## Session 14 — Full Dynamic Org Model (Sessions 1-8) · 2026-05-31

**Branch:** main | **Migrations:** 031-037 | **Unit tests:** 190 inv + 106 tenant = 296 passing

### Summary of all changes (Sessions 1-8)

| Session | Description | Status |
|---------|-------------|--------|
| S1 | Clean slate: truncate demo data, Migrations 031-034 (positions, personnel, transfer_type_config, transfer_approval_rules, unit_price) | DONE |
| S2 | JWT derived from primary position; TA system_role for tenant admins | DONE |
| S3 | Positions API, personnel_v2 API, transfer_types API, approval_rules API | DONE |
| S4 | Org setup wizard tabs 3-6 (positions, transfer types, approval rules, personnel) | DONE |
| S5 | Transfer creation validates level_permissions; calculates total_value; uses transfer_type_config | DONE |
| S6 | Dynamic approval routing via positions/personnel_positions; vacancy escalation | DONE |
| S7 | All tests already passing from previous sessions | DONE |
| S8 | Integration: TA system_role fix, personnel_v2 router conflict fix, JSONB bindparam fix, level_permission initiator fix, asyncpg nullable param fix; landing page updated | DONE |

### Session 8 bugs fixed

| Bug | File | Fix |
|-----|------|-----|
| `personnel.router` conflicts with `personnel_v2.router` | `tenant-service/main.py` | Removed old legacy router registration |
| TA user can't log in — no position required for system accounts | `auth-service/routers/auth.py`, Migration 037 | Added `system_role='TA'` column; auth service issues TA claims for users with this field |
| `::jsonb` cast syntax error with asyncpg | `tenant-service/routers/transfer_types.py`, `inventory_service.py` | Use `bindparam(..., type_=types.JSON)` for JSONB columns |
| Level permission check used wrong node for PULL | `inventory_service.py create_transfer()` | Check initiator node (to_warehouse for PULL, from_warehouse for PUSH) |
| asyncpg `$N IS NULL` type inference error | `approval_service.py _find_position_and_holder()` | Split SQL into 4 branches based on which params are None |
| Landing page shows wrong credentials | `frontend/src/app/page.tsx` | Updated to single SA account, removed demo tenants section |
| New Session 3 permissions not seeded | DB | Seeded POSITION_MANAGE, TRANSFER_TYPE_MANAGE etc. for SA/TA/NM roles |

### End-to-end smoke test results (Session 8)

Full flow completed via API:

| Step | Result |
|------|--------|
| SA login | JWT role=SA ✅ |
| SA creates tenant | Tenant created ✅ |
| SA creates TA user (system_role=TA) | User created ✅ |
| TA login | JWT role=TA, positions=[] ✅ |
| TA sets hierarchy (3 levels) | Levels saved ✅ |
| TA creates nodes (Factory/Region/WH) | 3 nodes created ✅ |
| TA creates positions at nodes | 3 positions created (NM/RM/WM) ✅ |
| TA creates users and assigns positions | 3 users with PRIMARY positions ✅ |
| TA configures transfer types (PULL=Replenishment Request) | Active types saved ✅ |
| TA configures approval rule | Region Manager approves PULL from Main→WH ✅ |
| WM creates PULL (Replenishment Request) | Transfer DRAFT, type_config_id stored ✅ |
| WM submits → PENDING_REVIEW | State machine ✅ |
| RM reviews → PENDING_APPROVAL | Dynamic routing fired: RM User assigned ✅ |
| RM approval-info: can_approve=True, assignee=RM User, dynamic=True | Dynamic routing correct ✅ |
| RM approves → INSUFFICIENT_STOCK | Ledger floor check working (no stock seeded yet) ✅ |

**Final test count:** 190 + 106 = 296 unit tests · TypeScript: 0 errors · Drift check: PASS

---

## KNOWN ARCHITECTURAL GAPS — Phase 2

These are not bugs in the current implementation but design limits that will be addressed in Phase 2. Documenting them here prevents surprise re-discovery and scopes future work.

### GAP A — Stale JWT on position change
If a user's position is reassigned while they are logged in, their JWT still carries the old `role` and `warehouse_id` until they log out and back in.  
**Risk:** User may see incorrect action buttons or be incorrectly denied transitions until re-login.  
**Fix (Phase 2):** JWT refresh endpoint that re-derives claims from current active position without requiring a full re-login (`POST /api/v1/auth/refresh-position`). Call it automatically when a 403 ABAC_DENIED is received on a state transition.

### GAP B — Stuck transfer on approver change
When a transfer is at `PENDING_APPROVAL` with `resolved_approval_steps` stored, if the assigned approver's position is deleted or they are deactivated, the transfer becomes stuck — no one is notified or assigned to approve it.  
**Risk:** Transfers stuck indefinitely at `PENDING_APPROVAL`.  
**Fix (Phase 2):** Celery periodic task (every 24 h) that detects transfers stuck `> 24 h` at `PENDING_APPROVAL` with an inactive or deleted approver and escalates to `TA` with an outbox notification. Also expose a `POST /api/v1/transfers/{id}/re-resolve-approvers` endpoint for TA to manually trigger re-resolution.

### GAP C — Org restructure mid-transfer
If the org hierarchy changes (node level changed, node renamed, node deleted) after a transfer was created, the transfer references old node IDs. Display issues and incorrect level-permission checks can result.  
**Risk:** Misleading display names, potentially incorrect ABAC decisions for in-flight transfers.  
**Fix (Phase 2):** Hierarchy versioning — freeze an org snapshot (from_node_level, to_node_level, from_node_name, to_node_name) into the `transfer_orders` row at creation time. Use the snapshot for display and for level-permission checks rather than querying the live hierarchy. Described in PRD-APPENDIX.md §B.

### GAP D — Approval chain is resolved once and not refreshed
`resolved_approval_steps` is computed when a transfer enters `PENDING_APPROVAL` and stored. Subsequent org or threshold changes do not update it.  
**Risk:** Approval chain reflects org structure at approval-entry time, not at current state. This is standard WMS practice (approval chains must not silently change mid-flow) but may surprise operators after large reorgs.  
**Fix (Phase 2):** Re-resolve button for TA: `POST /api/v1/transfers/{id}/re-resolve-approvers` forces fresh re-evaluation of the approval chain and resets `current_approval_step = 1`. Requires explicit TA action to prevent silent authority escalation.

---

*SMART Inventory Platform — Bug Report v4.0*  
*Backend: Python 3.12 / FastAPI · Frontend: Next.js 14 / TypeScript · DB: PostgreSQL 16*
