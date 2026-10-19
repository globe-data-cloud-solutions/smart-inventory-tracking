# Claude E2E Review — TenantClaude18

Local end-to-end functional test of the SMART inventory platform, run entirely against a
local dev stack (no AWS, no code/doc changes). Covers subscription sign-up through
multi-level org setup, products, transfers, and adjustments. Tenant `TenantClaude18` was
left active and intact for further testing — not deactivated or purged.

## Environment setup (repeatable)

1. `service postgresql start` + `service redis-server start` (local, not RDS/ElastiCache).
2. Created `smart_dev` DB and the `smart_runtime` role by hand, mirroring the grants
   `bootstrap_db_role.py` would apply on RDS (not applicable locally).
3. Untracked local `.env`: `DATABASE_URL`, `DATABASE_READ_URL`, `REDIS_URL`, `JWT_SECRET`,
   `ENVIRONMENT=local`, `FEATURE_LOT_TRACKING=true`, per-service URLs.
4. Python 3.12 venv at `/home/user/.venv-smart`; `pip install -e` for `backend/shared` plus
   the 5 core services; `PYTHONPATH=backend`.
5. `alembic upgrade head` — 89 migrations, clean, single head.
6. `scripts/seed_permissions.py`.
7. `scripts/create_partitions.py --months 3` — **required**, not optional (see Bug 4).
8. Backend services started manually via `uvicorn` on ports 8000–8004. The shipped
   `scripts/start_backend.sh` assumes Windows (`py -3.12` / PowerShell) and does not run
   as-is on this Linux dev box.
9. Frontend (Next.js) was **not** started — all steps were driven directly against the
   backend APIs.

## Round 1 — subscription sign-up through products, opening balances, first transfer

### Created
- **Tenant**: `TenantClaude18` (slug `tenantclaude18`, id `9195dd55-f890-4b94-a77b-6b9d1cb82b0d`),
  package GROWTH/MONTHLY, created via the real `POST /public/signup` self-service flow.
- **Users**:
  - TA: `ta-admin@tenantclaude18.local` / `ClaudeTA18Pass!`
  - AU: `auditor@tenantclaude18.example.com` / `ClaudeAU18Pass!`
  - LM: `logistics@tenantclaude18.example.com` / `ClaudeLM18Pass!`
- **Hierarchy**: National (non-stock-holding) → Main Regional WH + Dire Dawa Regional WH
  (siblings, stock-holding) → Bole Sub Depot (child of Main, stock-holding).
- **Products**:
  - BW-001 — regular
  - CT-001 — FIFO, 2 lots
  - YG-001 — FEFO, 2 lots with different expiry dates
  - ETH-001 — intended as a Controlled product — **blocked**, see Bug 1
- **Ledger activity**: 6 opening RECEIPTs, 3 ISSUEs (including correct FIFO and FEFO
  auto lot-selection), 1 PUSH transfer (ended stuck at `PENDING_APPROVAL`), 1 ADJUSTMENT
  (ended stuck at `DRAFT`) — 11 ledger rows total; balances verified consistent throughout.

### What worked correctly
- Self-signup → TA login → hierarchy/node-tree creation: all solid.
- FIFO and FEFO lot dispatch both picked the correct lot on ISSUE.
- Self-approval guardrail (`CANNOT_APPROVE_OWN_TRANSFER`) correctly rejected TA approving
  its own transfer.
- Ledger integrity held even through the failed-submit adjustment — balances were never
  touched until a transaction actually posted.

### Could not test in round 1
- Controlled-product designation (needs a position).
- Full transfer lifecycle / SISTER transfers (needs a second approver).
- The role-hierarchy ceiling rule at this depth (needs a facility-manager account).
- Any frontend/Playwright UI-rule pass (backend blockers consumed the available scope).

## Round 2 — positions, warehouse managers, multi-level transfers

Goal: work through Bugs 1–3 rather than stop at them, create managers at National /
Regional / Sub-WH levels, and complete the stuck transfer and adjustment using real
multi-level accounts, with TA restricted to its intended role of creating positions, org
levels, and approvals.

### Re-verification of Bug 1 (position creation)
Checked every plausible path before concluding it was a hard wall:
- Position CRUD endpoints — gated by `position:manage`, SA-only, no exception.
- `assign_position` — requires an *already-existing* position; 404s otherwise, no
  create-on-the-fly.
- Onboarding wizard (`complete_wizard`) — never touches positions.
- `OrgNodeCreate` / `OrgNodePatch.manager_user_id` — accepted by the request schema, but
  **purely cosmetic**: resolves a display name for that one response only and is never
  persisted or turned into a position/assignment (new Bug 10).

**Conclusion: there is no TA-reachable way to create a position or attach a facility-scoped
manager to a node.** This is a confirmed, reproducible blocker, not a one-endpoint fluke.

### Partial workaround found
TA holds full rights on `tenant:self_approval_manage` (unlike position/transfer_type/
approval-rule management). Configured a self-approval policy (TA, level 1, PUSH/PULL/SISTER,
value ≤ 100000) → created a fresh PUSH transfer → submitted it → it went straight
`DRAFT → APPROVED` with `is_self_approved: true`, bypassing the normal approval wall.

This does **not** fully unblock things: dispatch/receive require a position-linked
warehouse-manager identity. Dispatch was tried as the LM system-role account (which does
hold `transfer:dispatch` in the registry) — RBAC passed, but a business-rule check then
rejected it: *"Only the source warehouse manager can dispatch this transfer"* — i.e.
dispatch is gated on a position-linked identity at that node, which Bug 1 still prevents
creating. **Net result: a transfer can reach APPROVED via self-approval, but can never reach
DISPATCHED/RECEIVED — stock never actually moves.** Adjustments have no equivalent escape
hatch: `adjustment:submit` is blocked by the router decorator before any self-approval logic
runs, with no workaround found.

### Created in round 2
- Second sub-warehouse, "Dire Dawa Sub Depot," under Dire Dawa Regional WH (so the
  structure is now 2 regions × 1 sub-depot each).
- One new transfer (FIFO product, Main WH → Bole Sub Depot, 10 units) — ended at
  **APPROVED**, self-approved, undispatchable.
- No new managers or positions — confirmed fully blocked (Bug 1).

### End states
- Original transfer: stays `PENDING_APPROVAL` (self-approval only applies at submit time,
  not retroactively).
- New transfer: stuck at `APPROVED`, cannot be dispatched.
- Adjustment: stays `DRAFT`, permanently unsubmittable by TA.

### Explicit answer: is the TA-driven position/approval path reachable?
- Position creation: **No — confirmed fully blocked**, every avenue checked.
- Approval-rule / transfer-type configuration: **No — confirmed SA-only**, same pattern as
  position management.
- Self-approval policy: **Yes — reachable**, and it meaningfully advances a transfer to
  APPROVED, but does not let it complete (no dispatch/receive without a position).

## Bugs found

Ordered most severe first within each round; round 2 continues the numbering.

1. **CRITICAL** — `position:manage` is granted to SA only in `scripts/seed_permissions.py`'s
   matrix (confirmed against `registry.py` and all 89 migrations). No tenant role,
   including TA, can ever create an org position. Reproduced live: TA got
   `403 RBAC_DENIED position:manage` creating a position on a brand-new hierarchy node.
2. **CRITICAL, same root cause** — `transfer_type:manage` and `transfer_approval_rule:manage`
   are likewise SA-only. TA can view but never configure PUSH/PULL/SISTER types or their
   approval rules.
3. **CRITICAL** — `adjustment:submit` is granted only to NM/RM/WM/SA, never TA/AU/LM.
   Combined with Bug 1 (no way to create an NM/RM/WM account), a self-signup tenant can
   create an adjustment but can never submit it — confirmed stuck in DRAFT. The same
   dead-end affects transfers: TA is correctly blocked from self-approving by default
   (`CANNOT_APPROVE_OWN_TRANSFER` — a control that works), but with no other approver-eligible
   account reachable, a normal transfer is permanently stuck `PENDING_APPROVAL` too.
4. **HIGH** — `inventory_transactions` is monthly-partitioned, but nothing creates the
   partition automatically — not migrations, not Celery beat, not the seed/start scripts.
   Every RECEIVE/ISSUE/TRANSFER/ADJUST 500s on a fresh environment until someone manually
   runs `create_partitions.py`.
5. **MEDIUM** — No PostgreSQL RULE actually protects `inventory_balances` from direct
   UPDATE/DELETE, despite CLAUDE.md and `ledger_repo.py`'s own docstring both claiming one
   exists. `pg_rules` shows RULEs only on audit-log-style tables; none on the balance table.
6. **MEDIUM** — Documentation drift: CLAUDE.md and other docs refer to `warehouse_stock`;
   the real, live table is `inventory_balances` (renamed at some point, docs never updated).
7. **LOW-MEDIUM** — `POST /nodes` always returns `address: null` in its response even when
   the address is correctly persisted (confirmed via immediate follow-up GET).
8. **LOW-MEDIUM** — Every transfer-mutation response (create/submit) returns empty `lines`
   and null `total_value`/`currency` despite correct persistence; `GET /{id}` fixes `lines`
   but still nulls `total_value`/`currency` — no single response shows complete data.
9. **LOW** — `personnel_v2.UserCreate` uses a strict `EmailStr` that rejects `.local`
   addresses, inconsistent with signup's deliberately looser validator for the same purpose.
10. **LOW-MEDIUM** (round 2) — `OrgNodeCreate`/`OrgNodePatch.manager_user_id` is accepted by
    the request schema and silently discarded: never written to `organization_node`, never
    creates a `personnel_positions` row. It presents as a working "assign manager" field; it
    does nothing.
11. **CRITICAL** (round 2) — `PATCH /{tenant_id}/users/{user_id}` has **no role-ceiling check
    at all**. The TA account successfully promoted the AU user to `system_role: 'TA'` — a
    second full Tenant Admin — with a `200 OK`, confirmed in the database. This directly
    violates the explicit CLAUDE.md rule "never allow users to assign roles equal to or
    above their own level." Reproduced live and left in place as evidence (not reverted).

## Net assessment

The gap is not at the edges — it is that **no self-signup tenant can currently complete a
transfer, complete an adjustment, or build a real management hierarchy at all without SA
intervention**, because position creation and warehouse-manager assignment are unreachable
from any tenant-side role. On top of that, the one mutation path TA *can* reach unchecked
(editing another user's role) has no guardrail, so it can mint a second admin account.
Bugs 1, 3, and 11 should be prioritized together — fixing only the permission matrix without
also adding the role-ceiling check on the user-edit endpoint would leave Bug 11 open.

## Confirmed clean

- `git status` / `git diff` showed no tracked-file changes at the end of each round.
- Tenant `TenantClaude18`, its users, hierarchy, products, and all ledger data were left
  in place, untouched, for further testing.
- No AWS resources, workflows, or pipelines were touched at any point.
