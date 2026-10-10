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

```python
# backend/services/inventory-service/services/dispatch_service.py
async def resolve_strategy(db, tenant_id, product_id, category_id,
                           batch_tracking: bool, expiry_tracking: bool) -> str:
    # Auto-FEFO when both batch tracking AND expiry date are active
    if batch_tracking and expiry_tracking:
        return "FEFO"
    cfg = await get_dispatch_config(db, tenant_id, "PRODUCT", product_id)
    if cfg: return cfg.strategy
    cfg = await get_dispatch_config(db, tenant_id, "CATEGORY", category_id)
    if cfg: return cfg.strategy
    return "FIFO"   # system default

async def select_lots(db, tenant_id, product_id, warehouse_id,
                      required_qty: Decimal, strategy: str) -> list:
    lots = await get_available_lots(db, tenant_id, product_id, warehouse_id)
    if   strategy == "FEFO": lots.sort(key=lambda l: l.expiry_date)
    elif strategy == "FIFO": lots.sort(key=lambda l: l.received_at)
    else:                    lots.sort(key=lambda l: l.received_at, reverse=True)

    selections, remaining = [], required_qty
    for lot in lots:
        if remaining <= 0: break
        take = min(lot.available_quantity, remaining)
        selections.append(LotSelection(lot_id=lot.id, lot_number=lot.lot_number,
                                       quantity=take, strategy_applied=strategy))
        remaining -= take
    if remaining > 0:
        raise InsufficientStockError(product_id, required_qty, required_qty - remaining)
    return selections
```


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
