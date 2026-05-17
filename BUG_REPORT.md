# SMART Inventory Platform — Bug Report
**Generated:** 2026-05-17  
**Branch:** `main`  
**Head commit:** `b675211`  
**Unit tests:** `pytest backend/ -v -m "unit"` — **75 passed, 0 failed, 0 errors**  
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
| 10 | **Add `idempotency_key` column to `outbox` table** (Alembic migration) | S | ⏳ OPEN — schema gap documented in `writer.py`; deferred to next session |
| 11 | **Run full Playwright E2E suite** (`frontend/tests/transfer-receive-auth.spec.ts`) | S | ✅ DONE 2026-05-17 (12/12 passed, 1 skipped) |
| 12 | **Add approval workflow tests** per CLAUDE.md §21 `TestApprovalWorkflows` | L | ⏳ OPEN — none of the 15 approval matrix test cases written yet |

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

### Final test counts

| Suite | Count | Status |
|---|---|---|
| `pytest backend/ -v -m "unit"` | **75 / 75** | ✅ All pass |
| `frontend/tests/transfer-receive-auth.spec.ts` | **12 / 12** (1 skip) | ✅ All pass |
| `ci_drift_check.py` | 25 files scanned | ✅ 0 drift |
| `npx tsc --noEmit` | — | ✅ 0 errors |
| `next lint` | — | ✅ 0 warnings |

### Remaining open items (deferred)

- §8-6 (L): AWS dev environment — Terraform apply, RDS + ElastiCache provisioning
- §8-9 (L): Native-speaker review of `or.json` — staffing decision
- §8-10 (S): `idempotency_key` column on `outbox` table — Alembic migration 007
- §8-12 (L): Approval workflow tests per CLAUDE.md §21 `TestApprovalWorkflows` class

---

*SMART Inventory Platform — Bug Report v2.0*  
*Backend: Python 3.12 / FastAPI · Frontend: Next.js 14 / TypeScript · DB: PostgreSQL 16*
