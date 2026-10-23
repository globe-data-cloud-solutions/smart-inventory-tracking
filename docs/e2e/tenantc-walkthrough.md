# End-to-end walkthrough: TenantC01, TenantC02, TenantC03

Local run on 2026-10-23 against a clean `smart_e2e` database (PostgreSQL 16, Redis, five backend services,
Next.js dev server). Everything below was driven through the public sign-up wizard, the gateway API, and
headless Chromium. No SA account was used.

## Setup per tenant

| Item | Value |
|---|---|
| Company | TenantC01 / TenantC02 / TenantC03 |
| Plan | Enterprise, monthly (trial path, no real payment) |
| Organisation type | HYBRID |
| TA login | admin@tc01.com, admin@tc02.com, admin@tc03.com |
| Password (all accounts) | smart1026 (test accounts only; never outside a developer machine) |

Per tenant, the walkthrough creates:

- **Levels (4):** Factory (NM, stock-holding), Region (RM, approval only), Subregion (LM, approval only), Warehouse (WM, stock-holding).
- **Nodes (9):** Factory A, Factory B; Region North (under A), Region South (under B); Subregion A1 (under North), Subregion B1 (under South); WH A1-1 and WH A1-2 (under A1); WH B1-1 (under B1).
- **Positions (9):** one per node, reporting upward (warehouse → subregion → region → factory).
- **Users (11):** userNW (NM, Factory A), userNW2 (NM, Factory B), userRM1 / userRM2, userLM1 / userLM2, userWM1 / userWM2 / userWM3, userAU1 (tenant-wide AU), plus the TA. Format: `user<POS><n>@tcNN.com`.
- **Transfer types (3):** PULL (initiated and received at warehouses), PUSH (initiated at factory, received at warehouse), SISTER (warehouse to warehouse).
- **Approval mix:** PULL under 1,000 units needs RM North. PULL at 1,000 or more needs RM North, then NM Factory A. PUSH needs RM North, then NM Factory A. SISTER needs RM North.
- **Products (7):** Maize Flour, Cooking Oil and Iodised Salt (plain, no lots); Yoghurt and Cream Biscuit (batch and expiry, FEFO); Sugar and Rice (batch only, FIFO).
- **Opening stock:** each warehouse manager receives into their own warehouse: 1,500 units of each plain product, and two lots of each lot-tracked product (1,000 and 800 units, with different expiry dates for FEFO items).

## What was exercised (375 steps, all passed)

- Sign-up wizard (plan, details, review, confirm), email verification, TA login, TA dashboard and inventory page.
- Hierarchy PUT, node and position creation, user creation with positions and an auditor.
- Transfer types and the approval rules above.
- **PULL small:** create, submit, review, approve, dispatch, in transit, receive.
- **PULL large:** same, with a two-step chain (RM, then NM). Both approvals are recorded.
- **SISTER:** source confirm, destination confirm, approval, dispatch, in transit, receive.
- **PULL FEFO (yoghurt):** dispatch took the earliest-expiring lot first. Mutation responses include lines and totals (bug 8 fix, PR #45, verified on live data).
- **Adjustments:** DAMAGE and COUNT (positive) approved by the regional manager. EXPIRY on a specific lot approved by NM. A refused scope test: an RM from another region got `ADJUSTMENT_OUT_OF_SCOPE`, which is correct (RB-2). Three adjustments per tenant left in PENDING_APPROVAL on purpose, for your test.
- **Discrepancy:** a PULL of 100 units received as 90 gives one open discrepancy, resolved as WRITTEN_OFF by the regional manager.
- **Issues:** FEFO issue from a lot-tracked product; plain issue.

Final state per tenant: 5 transfers RECEIVED, 3 posted adjustments, 3 adjustments pending approval (scope test), 1 discrepancy resolved, 2 issues posted.

## Findings (not fixed in this pass)

1. **Information leak (bug).** A failed receive returns HTTP 500 `INTERNAL_ERROR` with the raw SQLAlchemy error and SQL text in `error.message` (for example `no partition of relation "inventory_transactions" ... [SQL: INSERT INTO inventory_transactions ...]`). Internal SQL must not reach API clients. Fix: map database errors to a generic code and log the detail server-side.
2. **Setup gap.** Migrations do not create the monthly `inventory_transactions` partitions. A fresh database fails every receipt until `scripts/create_partitions.py` runs. Either run it in the setup step (document it) or have the migration create the current and next months.
3. **Approval chain can name a role that cannot approve (bug).** The transfer approval rules API accepted a step for the Logistics Manager position. LM has no `transfer:approve`, so that step can never be signed off (review and approve both return `RBAC_DENIED`). Fix: validate approver positions against `transfer:approve` when saving rules.
4. **Approval info text does not match the configured chain (bug, minor).** For a PULL whose rule names the Regional Manager, `approval-info` still reports "requires Logistics Manager (level 3)". The Regional Manager can approve, so the routing works, but the message is wrong.
5. **Factory-specific products cannot be created (gap).** A code search found no product or inventory endpoint or screen that sets `products.source_factory_id`. The factory-scoped pull rule (CLAUDE.md §6) therefore cannot be tested end to end. Needs a product form field or an endpoint.
6. **Receive a transfer with an empty body (API inconsistency, minor).** `POST …/receive` with `{}` returns 422 "lines required". The router documents "no body = full receipt". Either accept `{}` or document the rule.
7. **Adjustment lot reference (unclear error, minor).** A negative adjustment on a lot-tracked product returns `LOT_REQUIRED` even when `lot_number` is sent. The endpoint needs `lot_id` for an existing lot. Either accept `lot_number` for existing lots or make the error say so.
8. **Login rate limit blocks scripted runs (note).** The login bucket allows 20 attempts per 15 minutes per IP. Repeated runs hit HTTP 429. The walkthrough sets `RATE_LIMIT_LOGIN` for local runs. Not a defect, but tests need a higher local limit or cached tokens.
9. **Expected behaviour (not bugs, recorded so nobody reports them):**
   - FIFO with expiry tracking returns 422 `INVALID_DISPATCH_STRATEGY`. Expiry tracking forces FEFO by design.
   - SISTER transfers skip review and go through source and destination confirmation.
   - `review` requires `transfer:approve`, so only TA, NM and RM can review.

## Retest and fix status

Each finding was re-run against the live services before any change was made. The fix PR
(`fix/e2e-findings-f1-f7`) addresses the ones that reproduced.

| # | Retest result | Status |
|---|---|---|
| 1 | Receive overflow returned raw SQL and INSERT text | Fixed: generic 500 message, detail logged server-side (inventory and tenant services) |
| 2 | Fresh database rejected receipts until partitions were created by hand | Fixed: migration 099 creates the current and next two months. Verified by running all migrations on an empty database |
| 3 | Approval rule saved a Logistics Manager step | Fixed: save rejects approver positions whose role lacks `transfer:approve` (`APPROVER_ROLE_CANNOT_APPROVE`), before existing rules are replaced |
| 4 | Approval info named the wrong approver | Not reproduced on the current data (this PULL routes to Regional Manager and reports it correctly). Needs an open PULL in PENDING_APPROVAL to re-check; not changed |
| 5 | Factory-specific products could not be set | Fixed on the API: create and PATCH accept `source_factory_id`, which must name an active node of the same tenant. The product form has no factory field yet, so this is API-only |
| 6 | Receive with `{}` returned 422 | Fixed: `{}` is a full receipt, as the router documents |
| 7 | Negative lot adjustment with `lot_number` returned a bare `LOT_REQUIRED` | Fixed: the error is now `LOT_ID_REQUIRED` and echoes the lot number. The rule itself is unchanged: a reduction needs an existing `lot_id` |
| 8 | Login rate limit blocks scripted runs | Note only: local runs set `RATE_LIMIT_LOGIN` |

Findings 1, 3, 5, 6 and 7 were reproduced live before the fix and rechecked live after it. Finding 2 was confirmed in code (no migration called the partition function) and verified by running every migration on an empty database after the fix.

## Not covered yet: outlines for future runs

- **Personnel lifecycle:** deactivate and reactivate users; ACTING and DELEGATE assignments with expiry; one PRIMARY per user; deactivating the only holder of a position.
- **Role ceiling:** a TA assigning a role at or above its own (`ROLE_CEILING_EXCEEDED`); a WM editing users.
- **Org changes:** move, deactivate and reactivate nodes; the level-role lock (`LEVEL_ROLE_LOCKED`); a node with open transfers or pending adjustments (`NODE_HAS_OPEN_TRANSFERS`, `NODE_HAS_PENDING_ADJUSTMENTS`); a node whose only user is removed (`NODE_HAS_SOLE_USERS`).
- **Approval rules:** value thresholds (not just quantity); self-approval; the override approver; `NOT_ASSIGNED_APPROVER` when the wrong holder tries to act.
- **Transfer rejection and cancellation** at each state; discrepancy resolutions ARRIVED_LATE, RETURNED and RECEIVED_AS_LOT; partial receipts with reason codes SHORT, DAMAGED and WRONG_LOT.
- **PUSH from a factory:** requires factory stock, which cannot be seeded through receive yet (see finding 5 and the factory receive question).
- **FEFO override** (`dispatch:fefo_override`), manual lot selection on issue and transfer, and `override_reason` handling.
- **Stock count sessions** (count, variance, approval).
- **Products:** discontinue and reactivate; approval minimums; product image upload; cross-warehouse view; unit price changes after transfers.
- **Reports and exports:** lot traceability, expiry alerts, dispatch summary, stock movement, inventory valuation, transfer history, audit log export (CSV and print).
- **Analytics** pages and the Stock Movement report with region scope.
- **Tenant isolation (RB-1):** a TA from TenantC01 calling TenantC02 URLs must get `TENANT_ACCESS_DENIED`; a shared slug must not leak data.
- **Plan and billing:** plan change is SA-only (TA gets 403 `PLAN_CHANGE_SA_ONLY`); invoices and checkout; contract stages GRACE and read-only.
- **Offline sync (RB-10):** a batch with mixed SYNCED, CONFLICT and ERROR items, and the Discard path on the device.
- **Amharic (am) rendering** of the new screens, including the P7 error templates.
- **Sign-up edge cases:** duplicate email, slug clash, verification resend, the 5-per-hour sign-up limit per IP.

## How to run on your PC

See `scripts/e2e/README.md`. Short version: start the stack (with `FEATURE_LOT_TRACKING=true` for the inventory service), run the sign-up and verification scripts, then run `run_e2e.py`. It creates data, so run it on a fresh database only.
