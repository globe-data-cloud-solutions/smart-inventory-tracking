## 9. Backend — Python / FastAPI Architecture

### Service directory structure

```
backend/services/<service>/
├── main.py                     # FastAPI app factory, lifespan, middleware
├── routers/<resource>.py       # One router file per resource
├── services/<resource>_service.py    # Business logic only
├── repositories/<resource>_repo.py   # SQLAlchemy queries only
├── schemas/<resource>.py       # Pydantic v2 request/response models
├── tests/
│   ├── conftest.py             # fixtures: test DB, mock user contexts
│   ├── test_<resource>_routes.py
│   └── test_permissions.py    # All 15 cases per action (required)
├── Dockerfile
└── pyproject.toml
```

### Every protected route requires `@require_permission`

```python
# backend/services/inventory-service/routers/receive.py
from fastapi import APIRouter, Depends
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS

router = APIRouter()

@router.post("/", status_code=201)
@require_permission(PERMISSIONS.INVENTORY_RECEIVE)
async def receive_stock(
    body: ReceiveStockRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession  = Depends(get_db_session),
) -> SuccessResponse[ReceiveStockResponse]:
    result = await inventory_service.receive(db, user, body)
    return SuccessResponse(data=result)

# Routes without @require_permission fail the CI drift check — PRs blocked.
```

### Dependency injection — JWT + DB + RLS

```python
# backend/shared/db/dependencies.py
async def get_db_session(user: UserContext = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        await set_rls_context(session, user.tenant_id, user.user_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Standard response envelope

```python
class SuccessResponse[T](BaseModel):
    success: bool = True
    data: T
    request_id: str
    timestamp: str

class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail   # code: RBAC_DENIED | ABAC_DENIED | INVALID_STATE | etc.
    request_id: str
    timestamp: str
```


## 13. Permission System — RBAC + ABAC

### Registry — single source of truth

```python
# backend/shared/permissions/registry.py
# Every action MUST be here before it can be used in any route.
# Seeded into the DB by scripts/seed_permissions.py.

from dataclasses import dataclass, field
from typing import List

@dataclass(frozen=True)
class Permission:
    id:   str
    abac: List[str] = field(default_factory=list)

class PERMISSIONS:
    # Domain 1 — Tenant & System
    TENANT_CREATE          = Permission("tenant:create",          ["platform_only"])
    TENANT_CONFIGURE       = Permission("tenant:configure",       ["tenant_id"])
    TENANT_SET_ORG_TYPE    = Permission("tenant:set_org_type",    ["tenant_id","audit_required"])

    # Domain 4 — Inventory
    INVENTORY_RECEIVE      = Permission("inventory:receive",      ["tenant_id","warehouse_id"])
    INVENTORY_ADJUST       = Permission("inventory:adjust",       ["tenant_id","warehouse_id","approval_threshold"])
    INVENTORY_TRANSFER     = Permission("inventory:transfer",     ["tenant_id","scope"])
    INVENTORY_CYCLE_COUNT  = Permission("inventory:cycle_count",  ["tenant_id","warehouse_id"])
    # IMTS: new inventory permissions
    INVENTORY_VIEW_DISTRIBUTION = Permission("inventory:view_distribution", ["tenant_id","facility_id"])
    INVENTORY_VIEW_SOURCES      = Permission("inventory:view_suggested_sources", ["tenant_id","warehouse_id"])

    # Domain 7 — AI
    AI_FORECAST_VIEW       = Permission("ai:forecast_view",       ["tenant_id"])
    AI_MODEL_RUN           = Permission("ai:model_run",           ["system_only"])  # SYS ONLY

    # Domain 9 — Dispatch (v3.0+)
    DISPATCH_CONFIGURE     = Permission("dispatch:configure",     ["tenant_id"])
    DISPATCH_FEFO_OVERRIDE = Permission("dispatch:fefo_override", ["tenant_id","override_permission","reason_required"])

    # ... all 156 entries
```

### Every new permission must be classified for read-only (2026-10-10)

A tenant whose contract has gone `READ_ONLY` (see `shared/billing/
contract_stage.py`, docs/claude/billing-and-tenants.md §S14) still passes
RBAC/ABAC normally — the read-only check is a separate layer on top, in
`shared/permissions/read_only.py`. **Adding a new action to the registry is
not enough**: until it is classified, it is blocked by that layer's
fail-closed default whenever a tenant is `READ_ONLY`, which silently breaks
even a GET route if nobody remembers this step.

- A route that only ever reads → add its action id to `READ_ACTIONS`.
- A write that must keep working in `READ_ONLY` (narrow — see
  `ALLOWED_WRITE_ACTIONS`'s existing members for the bar) → add it there
  instead.
- A GET route that happens to be gated behind an action id that *looks*
  like a write → decorate the route with `@require_permission(...,
  read_only_exempt=True)` rather than reclassifying the action (the action
  id may still correctly describe a write elsewhere).
- A mutating route gated behind an action id that *looks* like a read →
  decorate it with `@require_permission(..., read_only_force_write=True)`
  instead of reclassifying the action. `read_only_exempt` and
  `read_only_force_write` are mutually exclusive on the same route.
- Everything else (the common case: a genuine write, correctly named) needs
  no change — it is blocked in `READ_ONLY` by default, which is correct.

### Three-layer enforcement — all three layers are mandatory

```
Layer 1 — API Gateway:  JWT valid? Coarse role check. Rejects unauthenticated requests.
Layer 2 — Service Layer: RBAC check → ABAC attribute check → Conditional routing. Writes audit log.
Layer 3 — PostgreSQL RLS: tenant_id == session context. Cannot be bypassed by app code.

UI-level hiding is NOT a security layer. Never rely on it alone.
```

### `check_permission()` implementation

```python
# backend/shared/permissions/middleware.py
async def check_permission(
    user: UserContext,
    action: Permission,
    resource: dict | None = None,
    db: AsyncSession | None = None,
    scope_cache: dict[str, set[str]] | None = None,
) -> PermissionResult:
    # 1. RBAC check
    grant = await permission_store.get_role_permission(user.role, action.id)
    if not grant:
        await audit_log(user, action.id, resource, "DENIED", "RBAC_DENIED")
        return PermissionResult(allowed=False, reason="RBAC_DENIED")

    # 2. Tenant isolation — always checked
    if resource.get("tenant_id") and resource["tenant_id"] != user.tenant_id:
        await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: tenant mismatch")
        return PermissionResult(allowed=False, reason="ABAC_DENIED: tenant mismatch")

    # 3. Region scope
    if "region_id" in action.abac and user.region_id:
        if resource.get("region_id") and resource["region_id"] != user.region_id:
            await audit_log(user, action.id, resource, "DENIED", "ABAC_DENIED: region scope")
            return PermissionResult(allowed=False, reason="ABAC_DENIED: region scope")

    # 4. Warehouse scope — node + descendant traversal
    FACILITY_SCOPED_ROLES = {"WM", "LM", "SA_GT", "RT"}
    if user.role in FACILITY_SCOPED_ROLES and user.warehouse_id:
        resource_wh = resource.get("warehouse_id")
        if resource_wh and "warehouse_id" in action.abac:
            # Descendant set cached per-request in scope_cache
            # Falls back to exact-match if db is None
            if resource_wh_str not in scope_cache[user_wh_str]:
                return PermissionResult(
                    allowed=False,
                    reason="ABAC_DENIED: warehouse scope"
                )

    # 5. Conditional — route to approval workflow
    if grant.grant_type == "CONDITIONAL":
        await audit_log(user, action.id, resource, "CONDITIONAL", "APPROVAL_REQUIRED")
        return PermissionResult(allowed=True, condition="APPROVAL_REQUIRED")

    await audit_log(user, action.id, resource, "GRANTED")
    return PermissionResult(allowed=True)
```

### Role hierarchy (highest → lowest privilege)

```
SA (10) > TA (9) > NM (8) > RM (7) > WM (6) = LM (6) > SA_GT (4) > RT (3) > AU (2) > SYS (1)
```

Users may not assign roles at or above their own level.

### Role scope — facility-scoped vs tenant-wide

`FACILITY_SCOPED_ROLES` in `backend/shared/permissions/middleware.py` determines which
roles are restricted to their own assigned node for `warehouse_id`-scoped actions:

```
FACILITY_SCOPED_ROLES = {"WM", "LM", "SA_GT", "RT"}
```

```
WM:    node-scoped. Scope = the position's assigned node (assigned node + active descendants, §24 Rule 25).
LM:    node-scoped. Scope = the position's assigned node (assigned node + active descendants, §24 Rule 25).
       A tenant-wide LM account (system_role="LM", created without a position)
       has warehouse_id=None in its JWT and is NOT subject to this check at all
       — it keeps unrestricted tenant-wide read access. Node-scoping only
       applies once an LM is assigned a position at a specific node.
SA_GT, RT: node-scoped. Scope = the position's assigned node (assigned node + active descendants, §24 Rule 25).
TA, NM, RM, AU, SA: NOT facility-scoped — operate across all warehouses within
       their tenant. Their warehouse_id JWT claim (if present) is a home
       facility, not a cage.
```

> Node + descendant traversal is live — see §24 Rule 25 (`get_descendant_node_ids()` in
> `backend/shared/permissions/hierarchy_service.py`, wired into `check_permission()`).

### JWT payload — required fields

```python
class JWTPayload(BaseModel):
    sub:          str            # user UUID
    role:         str            # role_code
    tenant_id:    str
    region_id:    str | None
    warehouse_id: str | None     # maps to organization_node.id (facility_id) regardless of hierarchy level
                                 # Facility scope for FACILITY_SCOPED_ROLES resolved via get_descendant_node_ids()
                                 # (organization_node.parent_node_id) — see §24 Rule 25
    iat:          int
    exp:          int            # max JWT_EXPIRE_MINUTES (60 min)
```

### Token revocation

A JWT is normally valid for its full lifetime even after the event that
should invalidate it — `backend/shared/cache/token_revocation.py` closes that
gap with Redis "revoked-before" timestamps, checked once at the gateway.

- **Keys**: `revoked_before:user:{user_id}` and `revoked_before:tenant:{tenant_id}`
  (ids lower-cased). Value is the epoch second the revoke happened.
- **TTL**: `JWT_EXPIRE_MINUTES * 60 + 300` — a token can't outlive the key
  that would revoke it.
- **Triggers**: `revoke_user_tokens(user_id)` after password change
  (`PATCH /auth/password/{id}`), password reset (`POST /auth/reset-password`),
  a TA-issued password reset (`PATCH /tenants/{tid}/users/{uid}` with
  `password` set), user deactivation, and the auto-deactivate path when an SA
  force-removes a user's sole PRIMARY assignment. `revoke_tenant_tokens(tenant_id)`
  after tenant suspend and tenant deactivate — **not** reactivate (reactivating
  a tenant never restores sessions that were already invalidated).
- **Check**: the gateway's `proxy()` calls `is_token_revoked(payload)` right
  after `_decode_jwt()`, for every authenticated request — downstream
  services never check this themselves; enforcement relies on service
  security groups accepting traffic only from the gateway.
- **Fail-open / fail-safe**: mirrors `shared.cache.rate_limit`'s pattern.
  `revoke_*` swallows any Redis error (logs and returns — the business
  operation must never fail because Redis is down). `is_token_revoked` fails
  OPEN (returns not-revoked) on a Redis error, but treats a missing/non-int
  `iat` claim as revoked.
- **Redis-loss window**: if Redis is unreachable at revoke time, the revoke
  is silently dropped — any token issued before that point stays valid until
  it naturally expires (≤ `JWT_EXPIRE_MINUTES`). This is a known, accepted
  gap, not a bug to fix reactively.


## 14. Inventory Ledger — Immutable Rules

### warehouse_stock is a computed read model — never write to it directly

```
warehouse_stock holds pre-computed balance columns (on_hand, reserved, in_transit_in,
in_transit_out) for fast dashboard queries. It is NOT a source of truth.

The ONLY permitted writer:   update_running_balance() in ledger_repo.py
The ONLY permitted caller:   record_transaction() in ledger_repo.py
Both run in the SAME database transaction as the inventory_transactions INSERT.

Every other code path that touches warehouse_stock is READ ONLY (SELECT).

The database enforces this via a PostgreSQL RULE on warehouse_stock that rejects
any UPDATE issued outside the privileged ledger session role. This is defence in depth
on top of the application-level rule above.

IMTS §13.2 describes warehouse_stock as an inventory table. That description is accurate —
it is a table. What IMTS does not make explicit is that it is a derived/read table, not
a directly-writable one. PRD v4 §11.4 PR-NEW-9 is the authoritative rule: no direct
balance updates. This section operationalises that rule.
```

```python
# backend/services/inventory-service/repositories/ledger_repo.py
async def record_transaction(db: AsyncSession, tx: NewTransaction) -> InventoryTransaction:
    # 1. Idempotency — reject duplicate with 409
    await check_and_register_idempotency_key(db, tx.idempotency_key)

    # 2. Concurrency lock — prevent race conditions
    await db.execute(
        text("SELECT id FROM inventory_balances "
             "WHERE tenant_id=:tid AND product_id=:pid AND warehouse_id=:wid FOR UPDATE"),
        {"tid": tx.tenant_id, "pid": tx.product_id, "wid": tx.warehouse_id}
    )

    # 3. Stock floor — cannot go below zero without override
    if tx.quantity < 0:
        await validate_stock_available(db, tx.tenant_id, tx.product_id,
                                       tx.warehouse_id, abs(tx.quantity))

    # 4. INSERT ledger record (never UPDATE)
    new_tx = InventoryTransaction(**tx.model_dump())
    db.add(new_tx)
    await update_running_balance(db, tx)

    # 5. Write to outbox IN THE SAME TRANSACTION
    await write_to_outbox(db, tx.tenant_id, "InventoryUpdated",
        InventoryUpdatedPayload(product_id=str(tx.product_id),
                                warehouse_id=str(tx.warehouse_id),
                                delta=float(tx.quantity),
                                transaction_id=str(new_tx.id)))
    return new_tx

# WRONG — this bypasses the ledger entirely
async def set_balance(db, product_id, qty):
    await db.execute(text("UPDATE inventory_balances SET quantity=:q WHERE ..."), ...)
    # ← FORBIDDEN. Will fail CI review.
```

### IMTS: Authority scope resolution

> **ARCHIVED — do not implement or call.** `get_authority_scope()` is dead code (see §1).
> Scope resolution uses `get_descendant_node_ids()` — §24 Rule 25. The sample below is
> kept for history only; `get_suggested_sources()` remains valid.

```python
# backend/services/inventory-service/services/hierarchy_service.py
async def get_authority_scope(db: AsyncSession, tenant_id: str,
                              facility_id: str) -> list[str]:
    """
    Returns all organization_node IDs that the given facility has PRIMARY_REPORTS_TO
    authority over. Used by ABAC checks to determine if a user at facility_id
    can act on resources belonging to child facilities.
    Never infer authority from role alone — always call this function.
    """
    rows = await db.execute(
        text("""
            WITH RECURSIVE authority_tree AS (
                SELECT from_node_id AS node_id
                FROM org_node_hierarchy
                WHERE tenant_id = :tid
                  AND to_node_id = :fid
                  AND relationship_type = 'PRIMARY_REPORTS_TO'
                UNION ALL
                SELECT h.from_node_id
                FROM org_node_hierarchy h
                INNER JOIN authority_tree a ON h.to_node_id = a.node_id
                WHERE h.tenant_id = :tid
                  AND h.relationship_type = 'PRIMARY_REPORTS_TO'
            )
            SELECT node_id FROM authority_tree
        """),
        {"tid": tenant_id, "fid": facility_id}
    )
    return [str(r[0]) for r in rows.fetchall()]

async def get_suggested_sources(db: AsyncSession, tenant_id: str,
                                facility_id: str, product_id: str) -> list[dict]:
    """
    IMTS §10.1 source suggestion algorithm.
    Retrieves all SUPPLY_FROM sources for the facility, checks available stock,
    and ranks by: preferred source first, then stock availability, then proximity.
    Used by GET /api/v1/{tenant}/warehouses/{wh_id}/suggested-sources
    All queries run on DATABASE_READ_URL (read replica).
    """
    sources = await db.execute(
        text("""
            SELECT h.to_node_id AS source_id,
                   h.is_preferred,
                   ws.available,
                   n.name AS source_name
            FROM org_node_hierarchy h
            JOIN organization_node n ON n.id = h.to_node_id
            LEFT JOIN warehouse_stock ws ON ws.facility_id = h.to_node_id
                                        AND ws.product_id = :pid
                                        AND ws.tenant_id = :tid
            WHERE h.tenant_id = :tid
              AND h.from_node_id = :fid
              AND h.relationship_type = 'SUPPLY_FROM'
            ORDER BY h.is_preferred DESC, ws.available DESC NULLS LAST
        """),
        {"tid": tenant_id, "fid": facility_id, "pid": product_id}
    )
    return [dict(r) for r in sources.fetchall()]
```

### IMTS: New API endpoints

```
# Dashboard Service — IMTS distribution view (NM/LM role, read replica)
GET  /api/v1/{tenant}/facilities/{facility_id}/distribution-view
     @require_permission(PERMISSIONS.INVENTORY_VIEW_DISTRIBUTION)
     Returns: hierarchical stock tree from facility_id down, with threshold color status

# Multi-source suggestion (WM/RM role, read replica)
GET  /api/v1/{tenant}/warehouses/{wh_id}/suggested-sources?product_id={pid}
     @require_permission(PERMISSIONS.INVENTORY_VIEW_SOURCES)
     Returns: ranked list of SUPPLY_FROM sources with available stock

# IMTS: Transfer endpoints extended with type parameter
POST /api/v1/{tenant}/transfers/pull     # Pull request — uses PULL_TRANSITIONS
POST /api/v1/{tenant}/transfers/push     # Push issue — uses PUSH_TRANSITIONS
POST /api/v1/{tenant}/transfers/sister   # Sister transfer — uses SISTER_TRANSITIONS
# All existing PUT /{id}/submit|review|approve|dispatch|receive remain valid
# validate_transition() now requires transaction_type alongside current/next_state
```


## 16. Dispatch Strategy Engine

`backend/services/inventory-service/services/dispatch_service.py` (Phase B). It only
decides WHICH lots a movement draws from (`lot_balances` JOIN `stock_lots`); it never
writes a balance — deductions still go through `record_transaction()`.

**Strategy resolution** — `resolve_strategy(batch_tracking, expiry_tracking, product_strategy)`
returns `(strategy, source)`, pure, first match wins:

| Condition | Result |
|---|---|
| not batch-tracked | `(None, "NOT_BATCH")` |
| expiry-tracked | `("FEFO", "FORCED")` |
| `products.dispatch_strategy` set | `(it, "PRODUCT")` |
| otherwise | `("FIFO", "DEFAULT")` |

Category strategy is **parked**: the engine never reads categories or the archived
`dispatch_strategy_configs` table.

**Sort keys** (`sort_lots`, deterministic):

- FEFO: lots with NO expiry first (OPENING and pre-expiry-tracking lots), then
  `expiry_date` asc, `first_received_at` asc, `lot_number` asc.
- FIFO: `first_received_at` asc, `lot_number` asc.
- LIFO: `first_received_at` desc, `lot_number` asc.

**Allocation** — `plan_allocation(lots, qty, strategy, today)` returns
`Allocation(lines, shortfall, expired_skipped)` and never raises. Lots with
`expiry_date < today` are NEVER allocated under any strategy (reported in
`expired_skipped`); zero-quantity lots are ignored.

**Locking** — `load_candidate_lots(..., lock=True)` first locks the product's
`lot_balances` rows in that warehouse `ORDER BY lot_id FOR UPDATE` (fixed order, no
deadlocks), then reads. `allocate()` (write paths, Phase C) always locks and raises
`InsufficientStockError` on shortfall. The preview never locks.

**Manual selection + override** — `validate_manual_selection()` returns
`(plan, is_override)` and raises `DispatchError(code)` — a domain error, not an
HTTPException — with `LOT_NOT_IN_WAREHOUSE`, `LOT_EXPIRED`, `INSUFFICIENT_LOT_STOCK`
or `SELECTION_QTY_MISMATCH`. `is_override` is true when the chosen lot/quantity set
differs from the plan (order within the selection is irrelevant).
`record_override()` INSERTs one `lot_allocation_overrides` row (append-only by code —
no update/delete function). A FEFO override needs a non-blank reason
(`OVERRIDE_REASON_REQUIRED`); for FIFO/LIFO it is optional. The CALLER must check
`PERMISSIONS.DISPATCH_FEFO_OVERRIDE` for FEFO overrides and
`PERMISSIONS.DISPATCH_LOT_SELECT` for FIFO/LIFO overrides — Phase C wires the callers.

**Preview** — `GET /api/v1/inventory/dispatch/preview?product_id&warehouse_id&quantity`
(`routers/dispatch.py`, read replica, `inventory:view_balance`, same `warehouse_id`
ABAC scoping as `GET /lots`). Returns `{product_id, warehouse_id, quantity, strategy,
strategy_source, lines, shortfall, expired_skipped, available_total}`; a shortfall or a
non-batch product (`strategy: null`, `NOT_BATCH`, no lines) is a 200, not an error.

Real-DB proof: `python scripts/smoke_dispatch_engine.py` (rollback-only).

### Transfers

`backend/services/inventory-service/services/transfer_lots.py` (migration 085,
`transfer_line_allocations`). A batch-tracked transfer line is split into lots
ONCE — at final approval or self-approval — and every later step replays that
split rather than re-allocating.

- **Allocation timing**: `post_transfer_out()` allocates (or accepts the
  approver's manual selection) the first time a line is posted, INSERTs one
  `transfer_line_allocations` row per lot, then posts one `TRANSFER_OUT` per
  lot. A replay with the same `key_prefix` finds the stored rows and reuses
  them — nothing is allocated twice, and a lot whose `TRANSFER_OUT` already
  exists (409 on the ledger insert) is skipped as an idempotent no-op.
- **Ledger keys**: a batch line's entries key as
  `<key_prefix>:line:<line_id>:lot:<lot_id>`; a non-batch line keeps the old
  `<key_prefix>:line:<line_id>` key (no allocation rows for non-batch lines).
- **Lock order**: same as `record_transaction()` — the product's
  `inventory_balances` row `FOR UPDATE` first, then the lot rows (`allocate()`
  locks `lot_balances` `ORDER BY lot_id`).
- **Overrides**: only at `POST /transfers/{id}/approve` (the final approval
  step). The router resolves both checks up front and passes them in — a FEFO
  override needs `DISPATCH_FEFO_OVERRIDE` plus a non-blank reason
  (`OVERRIDE_REASON_REQUIRED` otherwise); a FIFO/LIFO override needs
  `DISPATCH_LOT_SELECT` — both scoped at the source warehouse. An override
  without the matching permission raises `OVERRIDE_NOT_PERMITTED` (403).
- **Transit audit vs. receipt credit**: `post_lot_audit()` writes
  `TRANSIT_OUT` / `TRANSIT_IN` / `TRANSIT_CLEAR` / `TRANSFER_REVERSAL` entries
  per allocation — audit only, no balance effect beyond what `TRANSFER_OUT`
  already moved. `post_transfer_in()` credits the destination with one
  `TRANSFER_IN` per allocation on the **same `lot_id`** the source was debited
  on, so `stock_lots.lot_number`, `expiry_date` and `first_received_at` carry
  over unchanged.
- **Cancel after approval**: reverses each allocation at the source via
  `post_lot_audit(..., transaction_type="TRANSFER_REVERSAL", sign=1)`.
- **Batch-tracking toggle guard**: `lot_settings_service.py` blocks turning
  batch tracking OFF while any lot still carries a positive balance
  (`BATCH_TRACKING_IN_USE`, 409), and blocks turning it ON while any transfer
  of the product is past approval — status in `APPROVED`, `ADVISED`,
  `ISSUED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`
  (`BATCH_TRACKING_TRANSFERS_OPEN`, 409). Transfers still waiting on approval
  don't block the toggle — their lots haven't been picked yet.

Real-DB proof: `python scripts/smoke_transfer_lots.py` (rollback-only).

#### Receipt confirmation (C2)

`InventoryService.receive_transfer()` +
`backend/services/inventory-service/services/transfer_discrepancies.py`
(migration 086, `transfer_discrepancies`). The destination confirms what
actually arrived — per allocated lot for a batch line, per line for a
non-batch line.

- **One receipt event, always RECEIVED**: a transfer is received once and ends
  in `RECEIVED`, short or not. `PARTIALLY_RECEIVED` is kept in the state
  machine but is unreachable — `PATCH /transfers/{id}` to it returns 422
  `PARTIAL_RECEIPT_NOT_SUPPORTED`.
- **Optional body**: `POST /transfers/{id}/receive` takes an optional
  `ReceiveTransferRequest` (`lines: [{line_id, lot_id?, received_quantity,
  reason?, note?}]`). No body — and `PATCH` to `RECEIVED` — is a full receipt
  with the same ledger entries and idempotency keys as before C2.
- **What the ledger gets**: `TRANSFER_IN` credits only what arrived (same
  `lot_id` as the source, key `transfer:<id>:receive:in:line:<line_id>` plus
  `:lot:<lot_id>` for a batch line). `TRANSIT_CLEAR` always clears the full
  sent quantity at source and destination. A received quantity of 0 writes no
  `TRANSFER_IN` (and no `StockTransferred` event) at all.
- **Where the shortfall lives**: only in `transfer_discrepancies` — one row
  per short lot (batch) or line (non-batch), `status = 'OPEN'`,
  `missing = sent - received`. Record-only: no ledger entry carries the
  missing quantity. Append-only by code — `insert_discrepancy()` is the only
  write path; there is no update or delete function. Resolution (write-off, or
  return to the source lot) is a later phase.
- **Validation — all before any write**: `validate_receipt()` checks the whole
  body against `expected_entries()` (one entry per allocation of a batch line,
  one `lot_id = NULL` entry per non-batch line) before the first ledger entry.
  All four codes are HTTP 422:

  | Code | When |
  |---|---|
  | `RECEIPT_LINES_MISMATCH` | the body does not list every expected (line, lot) entry exactly once |
  | `RECEIPT_EXCEEDS_SENT` | `received_quantity` is above what was sent |
  | `RECEIPT_REASON_REQUIRED` | `received_quantity` is below what was sent and `reason` is missing (`SHORT` \| `DAMAGED` \| `WRONG_LOT`) |
  | `PARTIAL_RECEIPT_NOT_SUPPORTED` | `PATCH` to `PARTIALLY_RECEIVED` (router) |

- **In-transit analytics**: `in_transit_out` / `in_transit_in` in
  `inventory_analytics.get_stock()` are driven by transfer status, so both
  drop to 0 at `RECEIVED` — a shortfall never stays "in transit".
- **Read side**: `receive_transfer()` and `get_transfer()` return
  `discrepancies` (`TransferDiscrepancyOut`, with `lot_number` joined from
  `stock_lots`).

#### Issue and Adjustment (C3)

`InventoryService.issue_stock()` / `create_adjustment()` /
`transition_adjustment()` / `approve_adjustment()` (migration 087, lot columns
on `adjustment_orders`).

- **Issue — allocation at posting**: a batch-tracked line allocates against
  the dispatch engine (`services/dispatch_service.py`) the moment
  `issue_stock()` runs — there is no separate approval step, since ISSUE is a
  direct On Hand deduction. One `ISSUE` ledger row per lot, sorted by
  `lot_id`, all sharing `reference_id = issue_ref` (a `uuid5` of tenant +
  idempotency key); key = `<idempotency_key>:lot:<lot_id>`. A replay (rows
  already posted for `issue_ref`) returns those rows and writes nothing — the
  same lock order as `record_transaction()` (balance row, then lots) protects
  the check against a concurrent duplicate. `InsufficientStockError` reports
  `expired_qty`: the part of the shortfall sitting in lots whose
  `expiry_date` has passed (never allocated).
- **Issue — overrides**: a `lot_selections` body that differs from the
  engine's own plan is an override, exactly as for transfers — FEFO needs
  `DISPATCH_FEFO_OVERRIDE` plus a non-blank reason
  (`OVERRIDE_REASON_REQUIRED` otherwise), FIFO/LIFO needs
  `DISPATCH_LOT_SELECT`; either without the matching permission raises
  `OVERRIDE_NOT_PERMITTED` (403). `routers/issue.py` resolves both checks up
  front. A posted override writes one `lot_allocation_overrides` row with
  `movement_type = 'ISSUE'` and `reference_id = issue_ref`.
- **Issue — non-batch unchanged**: a single `ISSUE` row, negative quantity,
  `lot_id` NULL, key = the plain `idempotency_key`. `lot_selections` on a
  non-batch product is `LOT_NOT_TRACKED` (422).
- **Adjustment — lot captured at creation, posted later**:
  `create_adjustment()` validates the lot input against the product's
  tracking and stores it on `adjustment_orders` (`lot_id`, `lot_number`,
  `expiry_date`, `auto_lot`) — it never creates a lot or touches a balance.
  `_adjustment_lot_for_post()` resolves the lot the moment the ledger INSERT
  actually happens (self-approve at submit, or `approve_adjustment()`),
  creating a new lot (entered number or auto lot) in the same transaction as
  the post and writing it back to `adjustment_orders.lot_id`. `LOT_NOT_FOUND`
  (422) if a lot chosen by `lot_id` at creation was removed before posting.
- **Adjustment — effective sign**: `DAMAGE` / `EXPIRY` / `SUPPLIER_RETURN`
  always force a negative quantity regardless of the sign supplied
  (`_FORCE_NEGATIVE_REASONS`); any other reason with a negative
  `quantity_delta` is negative on its own terms. Either way counts as the
  "effective negative" path in `_validate_adjustment_lot()`.
- **Adjustment — negative needs a lot**: `lot_id` is required
  (`LOT_REQUIRED` otherwise) and must already hold enough balance at the
  warehouse (`LOT_NOT_IN_WAREHOUSE` if it holds none there,
  `INSUFFICIENT_LOT_STOCK` if the requested quantity exceeds what it holds).
  An **expired** lot is explicitly allowed here — writing off expired stock
  is the normal way an EXPIRY adjustment is done. The same
  `INSUFFICIENT_LOT_STOCK` code can also surface at posting (the lot-level
  floor check in `record_transaction()`) if the lot was drained by something
  else between creation and posting — independent of, and checked after, the
  product-level stock floor.
- **Adjustment — positive chooses or creates a lot**: exactly one of an
  existing `lot_id`, a new `lot_number`, or `auto_lot` (`LOT_REQUIRED` for
  none, `LOT_INPUT_CONFLICT` for more than one). An existing lot keeps its
  own expiry (passing `expiry_date` alongside `lot_id` is also
  `LOT_INPUT_CONFLICT`) and may land in a warehouse it has never held stock
  in before — `lot_balances` gets a fresh row at posting. A new lot follows
  `receive()`'s rules (`EXPIRY_REQUIRED`, `EXPIRY_IN_PAST`,
  `LOT_EXPIRY_MISMATCH` on a reused number with a different expiry) but is
  only actually created in `_adjustment_lot_for_post()`, at posting.
- **Both posting paths covered**: self-approval at submit
  (`transition_adjustment()`, DRAFT → PENDING_APPROVAL) and the
  `POST /adjustments/{id}/approve` route both end by calling
  `record_transaction()` with the resolved lot and updating
  `adjustment_orders.lot_id`/status identically. Which path a given tenant
  uses depends entirely on whether `adjustment_approval_rules` has a matching
  active row for the submitter's `(role_code, level_number, reason_code)` —
  `check_adjustment_self_approval()` returns `(False, None, None)` with no
  match (or immediately, if `level_number` is `None`), which routes to
  PENDING_APPROVAL every time. The permanent `zz-e2e-ta` smoke tenant has no
  `adjustment_approval_rules` rows of its own, so its real users (`level_number
  = None`) never self-approve — `scripts/smoke_issue_adjust_lots.py` scenarios
  A1-A7 all post via the approve-route for that reason. The script's A8
  scenario installs one temporary `adjustment_approval_rules` row (`role_code
  = 'WM'`, `level_number = 99`, `reason_code` NULL/GLOBAL, generous limits —
  rolled back with everything else) and calls `create_adjustment()` /
  `transition_adjustment()` under a matching user, so the self-approve-at-submit
  path is exercised too, end to end.

Real-DB proof: `python scripts/smoke_issue_adjust_lots.py` (rollback-only).

> **Phase D note**: blocking expired lots on a *manual* pick (an operator
> selecting an expired lot by hand) must not apply to Adjustment — an
> expired lot is the normal, intended target of an EXPIRY write-off.

Real-DB proof: `python scripts/smoke_transfer_receipt.py` (rollback-only).


## 17. Workflow State Machines

```python
# backend/services/inventory-service/services/state_machine.py
#
# IMTS enhancement: type-specific machines replace the single TRANSFER_TRANSITIONS dict.
# Each transaction type has genuinely different states — a single dict cannot enforce
# the PENDING_REVIEW step that PULL requires but PUSH does not, or the dual-confirm
# steps that SISTER requires and PULL does not.

PULL_TRANSITIONS = {
    # WH requests stock from RWH or MWH — has a review step before approval
    "DRAFT":              ["PENDING_REVIEW", "CANCELLED"],
    "PENDING_REVIEW":     ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
    "PENDING_APPROVAL":   ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":           ["ISSUED", "CANCELLED"],
    "ISSUED":             ["IN_TRANSIT"],
    "IN_TRANSIT":         ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED": ["RECEIVED"],
    "RECEIVED":           ["COMPLETED"],
    "COMPLETED": [], "REJECTED": [], "CANCELLED": [],
}

PUSH_TRANSITIONS = {
    # MWH or RWH proactively sends stock down — no review step; ADVISED precedes ISSUED
    "DRAFT":              ["PENDING_APPROVAL", "CANCELLED"],
    "PENDING_APPROVAL":   ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":           ["ADVISED", "ISSUED", "CANCELLED"],
    # ADVISED: destination notified, can flag overstock/space issues to pause dispatch
    "ADVISED":            ["ISSUED", "CANCELLED"],
    "ISSUED":             ["IN_TRANSIT"],
    "IN_TRANSIT":         ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED": ["RECEIVED"],
    "RECEIVED":           ["COMPLETED"],
    "COMPLETED": [], "REJECTED": [], "CANCELLED": [],
}

SISTER_TRANSITIONS = {
    # WH ↔ WH same level — both managers must explicitly agree before any approval above
    "DRAFT":                   ["PENDING_SOURCE_CONFIRM", "CANCELLED"],
    "PENDING_SOURCE_CONFIRM":  ["PENDING_DEST_CONFIRM", "CANCELLED"],
    "PENDING_DEST_CONFIRM":    ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
    "PENDING_APPROVAL":        ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":                ["ISSUED", "CANCELLED"],
    "ISSUED":                  ["IN_TRANSIT"],
    "IN_TRANSIT":              ["PARTIALLY_RECEIVED", "RECEIVED"],
    "PARTIALLY_RECEIVED":      ["RECEIVED"],
    "RECEIVED":                ["COMPLETED"],
    "COMPLETED": [], "REJECTED": [], "CANCELLED": [],
}

ADJUSTMENT_TRANSITIONS = {
    # DAMAGE and EXCESS adjustments — no transit states; ends at POSTED
    "DRAFT":            ["PENDING_APPROVAL", "CANCELLED"],
    "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
    "APPROVED":         ["POSTED"],
    "POSTED": [], "REJECTED": [], "CANCELLED": [],
}

# Machine registry — keyed by transaction type code
TRANSFER_MACHINES = {
    "PULL":   PULL_TRANSITIONS,
    "PUSH":   PUSH_TRANSITIONS,
    "SISTER": SISTER_TRANSITIONS,
}

def get_machine(transaction_type: str) -> dict:
    """Returns the correct state machine for the given transaction type."""
    if transaction_type in ("DAMAGE", "EXCESS", "COUNT"):
        return ADJUSTMENT_TRANSITIONS
    machine = TRANSFER_MACHINES.get(transaction_type)
    if not machine:
        raise ValueError(f"Unknown transaction type: {transaction_type}")
    return machine

def validate_transition(transaction_type: str, current: str, next_state: str) -> None:
    """Raises InvalidStateTransitionError → HTTP 422 for any invalid transition."""
    machine = get_machine(transaction_type)
    if next_state not in machine.get(current, []):
        raise InvalidStateTransitionError(current=current, attempted=next_state,
                                          transaction_type=transaction_type)
```


## 18. Offline Sync Strategy

```typescript
// Idempotency key — generated client-side before any network call
export function generateIdempotencyKey(userId: string, action: string, productId: string): string {
  return `${userId}:${action}:${productId}:${Date.now()}:${nanoid(8)}`;
}
```

```python
# Conflict resolution (server-side)
async def resolve_sync_item(db: AsyncSession, item: OfflineSyncQueueItem) -> SyncResult:
    # Rule 1: duplicate idempotency key → already processed
    if await idempotency_key_exists(db, item.idempotency_key):
        return SyncResult(status="SYNCED", message="Already processed")
    # Rule 2: quantity mismatch → mark CONFLICT for human review
    try:
        result = await process_transaction(db, item)
        return SyncResult(status="SYNCED", transaction_id=result.id)
    except QuantityMismatchError as e:
        await mark_conflict(db, item, conflict_data=e.detail)
        return SyncResult(status="CONFLICT", detail=e.detail)
    # Rule 3: concurrent update → last-write-wins, both values in audit log
```


## 19. API Conventions

```
URL structure:
  /api/v1/{resource}              GET list, POST create
  /api/v1/{resource}/{id}         GET, PATCH, DELETE
  /api/v1/{resource}/{id}/{sub}   nested resource

Authentication:
  All requests:     Authorization: Bearer <jwt>  (max 60 min)
  SYS integrations: X-API-Key: <key>

HTTP status codes:
  201  Created
  200  OK
  400  Validation error (malformed request body)
  401  Unauthenticated or expired JWT
  403  Permission denied — RBAC_DENIED or ABAC_DENIED
  404  Not found
  409  Idempotency key conflict — duplicate transaction
  422  Invalid state transition | Insufficient stock
  429  Plan limit exceeded (SKU cap, rate limit)

Standard envelope:
  { "success":true,  "data":{...},                          "request_id":"...", "timestamp":"..." }
  { "success":false, "error":{"code":"RBAC_DENIED","message":"..."}, "request_id":"...", "timestamp":"..." }

Exception — auth-service public endpoints (/auth/token, verify-email, resend-verification,
forgot-password, reset-password, PATCH /auth/password/{id}) return flat JSON (OAuth-style
token response), NOT the {success,data} envelope above. ~30 scripts/e2e scripts and the
frontend auth helpers depend on this flat shape. Errors on these endpoints still use
{"detail":{"code","message"}}, not the error envelope. This is intentional — do not change
the response shape of these endpoints to match the standard envelope.
```

---

## 20. AI & Analytics Pipeline

```python
# Separate model cohorts — never train on mixed data
def get_model_cohort(org_type: str) -> str:
    return "PRODUCER" if org_type == "PRODUCER" else "RETAILER"
# PRODUCER cohort: production demand signals, lead times, batch cycle data
# RETAILER cohort: SKU-level sales velocity, reorder frequency, stockout patterns

# AI recommendations: always PENDING_APPROVAL, never auto-execute
class RecommendationStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"  # default — human must act before anything executes
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"

# ai:model_run (Action 91) is SYS role ONLY — user call returns HTTP 403
# Analytics ETL: triggered by Celery outbox worker consuming InventoryUpdated events
# All analytics queries use DATABASE_READ_URL (read replica) — never the primary

# Large Retailer catalogue batch forecasting
@celery_app.task
def generate_retailer_forecasts(tenant_id: str) -> None:
    """Runs off-peak. Pre-computes and caches to Redis before dashboard load."""
    if get_sku_count(tenant_id) <= 5000:
        return  # on-demand is acceptable for small catalogues
    forecasts = run_inference(tenant_id)
    cache_forecasts(tenant_id, forecasts, ttl_hours=24)
```

---
