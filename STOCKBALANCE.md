# Claude Code Prompt — SMART Inventory
## Stock Balance Management: Receiving, Issuing & In-Transit
### Inventory Service 

---

> **Read CLAUDE.md in full before writing a single line of code.**
> Every constraint below is derived from that file. When in doubt, re-read the
> relevant CLAUDE.md section rather than guessing.

---

## 1. What You Are Building

Implement the **stock balance management module** for the SMART Inventory platform.
This module covers the full lifecycle of stock movement between warehouses,
distribution centres, and stores — specifically:

- **Receiving** stock (from supplier, production, donation, or transfer-in)
- **Issuing** stock (for sale, internal consumption, dispatch, or distribution)
- **Transferring** stock between locations with a formal state machine
  (`DRAFT → SUBMITTED → APPROVED → IN_TRANSIT → RECEIVED → CLOSED`)
- **Real-time balance visibility** showing On Hand, In Transit (pending inbound),
  Issued, and Available quantities per location per SKU
- **Immutable ledger recording** of every mutation — no direct balance updates, ever

This is an **XL workstream** (8–12 weeks, per SOW §3 Phase 1). You are implementing
the backend service layer, API endpoints, database schema, and frontend components
for this feature set.

---

## 2. Absolute Rules — Violations Cause PR Rejection

```
NEVER update inventory_balances directly — every stock change must INSERT
  into inventory_transactions and call record_transaction().

NEVER write to the outbox table in a separate DB transaction — it must be
  committed atomically with the inventory_transactions INSERT.

NEVER run balance queries on the primary DB — use the read replica session.

NEVER skip the three-layer permission check — gateway JWT, service-layer
  check_permission(), and PostgreSQL RLS must all fire.

NEVER allow a transfer to skip a state — validate_transition() must be called
  before every status change. DRAFT → IN_TRANSIT is an invalid jump and must
  raise InvalidStateTransitionError (HTTP 422).

NEVER deduct stock from source before the transfer reaches APPROVED state.
  Stock is locked (reserved) at SUBMITTED, deducted at APPROVED.

NEVER credit stock to the destination before the transfer reaches RECEIVED state.

NEVER hardcode UI strings — every label, button, status, and error message
  must use an i18n key from en.json / am.json.
```

---

## 3. Stack — Confirmed, Do Not Deviate

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.x (async) · Pydantic v2 · python-casbin · Alembic |
| Async side effects | Transactional Outbox Pattern — PostgreSQL outbox table + Celery + NOTIFY |
| Database | PostgreSQL 16 — RLS on every tenant-scoped table |
| Frontend | React 18 · Next.js 14 App Router · TypeScript 5 strict · Tailwind CSS 3 · TanStack Query · Zustand · Zod |
| Offline | IndexedDB (`idb`) offline queue — transactions created offline must sync when connectivity returns |
| i18n | JSON language packs (en.json, am.json) loaded from S3 — no hardcoded strings |

---

## 4. Database Schema

### 4.1 Required Enums (Phase 0 — already exist, do not redefine)

```sql
-- Confirm these exist before running migrations
transaction_type  ENUM ('RECEIVE','TRANSFER_OUT','TRANSFER_IN','ISSUE',
                        'ADJUSTMENT','RESERVE','RELEASE','RETURN','COUNT_VARIANCE')
transfer_status   ENUM ('DRAFT','SUBMITTED','APPROVED','IN_TRANSIT',
                        'RECEIVED','CLOSED','REJECTED','CANCELLED')
dispatch_strategy ENUM ('FEFO','FIFO','LIFO')
outbox_status     ENUM ('PENDING','PROCESSING','PROCESSED','FAILED')
```

### 4.2 New / Extended Tables — Alembic Migration Required

```sql
-- inventory_transactions — partitioned by transaction_date (Phase 0 partition already exists)
-- Add any missing columns via Alembic ALTER TABLE, never DROP existing columns
CREATE TABLE inventory_transactions (
  id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
  tenant_id           UUID        NOT NULL REFERENCES tenants(id),
  transaction_date    DATE        NOT NULL DEFAULT CURRENT_DATE,  -- partition key
  transaction_type    transaction_type NOT NULL,
  product_id          UUID        NOT NULL REFERENCES products(id),
  warehouse_id        UUID        NOT NULL REFERENCES warehouses(id),
  lot_id              UUID        REFERENCES lots(id),            -- NULL if no lot tracking
  quantity            NUMERIC(15,4) NOT NULL,                     -- positive=in, negative=out
  balance_before      NUMERIC(15,4) NOT NULL,
  balance_after       NUMERIC(15,4) NOT NULL,
  reference_type      VARCHAR(50),    -- 'TRANSFER','PURCHASE_ORDER','MANUAL', etc.
  reference_id        UUID,           -- FK to transfers.id or purchase_orders.id
  idempotency_key     VARCHAR(100) NOT NULL,
  performed_by        UUID        NOT NULL REFERENCES users(id),
  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, transaction_date)
) PARTITION BY RANGE (transaction_date);

-- inventory_balances — running balance, updated atomically with each transaction
CREATE TABLE inventory_balances (
  tenant_id       UUID        NOT NULL REFERENCES tenants(id),
  product_id      UUID        NOT NULL REFERENCES products(id),
  warehouse_id    UUID        NOT NULL REFERENCES warehouses(id),
  on_hand         NUMERIC(15,4) NOT NULL DEFAULT 0,
  in_transit_in   NUMERIC(15,4) NOT NULL DEFAULT 0,  -- inbound pending receipt
  in_transit_out  NUMERIC(15,4) NOT NULL DEFAULT 0,  -- outbound pending delivery
  reserved        NUMERIC(15,4) NOT NULL DEFAULT 0,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, product_id, warehouse_id)
);

-- transfers — one record per transfer request
CREATE TABLE transfers (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID        NOT NULL REFERENCES tenants(id),
  transfer_number     VARCHAR(30) NOT NULL,   -- human-readable, e.g. TRF-2025-00001
  status              transfer_status NOT NULL DEFAULT 'DRAFT',
  from_warehouse_id   UUID        NOT NULL REFERENCES warehouses(id),
  to_warehouse_id     UUID        NOT NULL REFERENCES warehouses(id),
  requested_by        UUID        NOT NULL REFERENCES users(id),
  approved_by         UUID        REFERENCES users(id),
  expected_delivery   DATE,
  transporter_details JSONB,
  proof_of_receipt    TEXT,        -- S3 key
  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_different_warehouses CHECK (from_warehouse_id <> to_warehouse_id)
);

-- transfer_lines — one row per SKU per transfer
CREATE TABLE transfer_lines (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  transfer_id     UUID        NOT NULL REFERENCES transfers(id) ON DELETE CASCADE,
  product_id      UUID        NOT NULL REFERENCES products(id),
  lot_id          UUID        REFERENCES lots(id),
  requested_qty   NUMERIC(15,4) NOT NULL CHECK (requested_qty > 0),
  approved_qty    NUMERIC(15,4),
  received_qty    NUMERIC(15,4),
  discrepancy_qty NUMERIC(15,4) GENERATED ALWAYS AS
                    (COALESCE(received_qty,0) - COALESCE(approved_qty,0)) STORED,
  unit_of_measure VARCHAR(20) NOT NULL
);

-- idempotency_keys — prevent duplicate processing (Phase 0 table — already exists)
-- INSERT OR IGNORE pattern in record_transaction()

-- RLS policies — every table above must have a tenant_id RLS policy
-- Pattern (apply to all new tables):
ALTER TABLE transfers        ENABLE ROW LEVEL SECURITY;
ALTER TABLE transfer_lines   ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_balances ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON transfers
  USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

CREATE POLICY tenant_isolation ON transfer_lines
  USING (EXISTS (
    SELECT 1 FROM transfers t
    WHERE t.id = transfer_lines.transfer_id
    AND t.tenant_id = current_setting('app.current_tenant_id')::uuid
  ));

CREATE POLICY tenant_isolation ON inventory_balances
  USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

### 4.3 Indexes

```sql
CREATE INDEX idx_inv_tx_tenant_product_wh
  ON inventory_transactions (tenant_id, product_id, warehouse_id, transaction_date DESC);

CREATE INDEX idx_inv_tx_reference
  ON inventory_transactions (reference_type, reference_id)
  WHERE reference_id IS NOT NULL;

CREATE UNIQUE INDEX idx_idempotency_key
  ON idempotency_keys (tenant_id, idempotency_key);

CREATE INDEX idx_transfers_tenant_status
  ON transfers (tenant_id, status, created_at DESC);
```

---

## 5. Backend — Service Layer

### 5.1 File Locations

```
backend/services/inventory-service/
├── api/
│   └── v1/
│       ├── stock_balance.py     # GET balance endpoints
│       ├── receiving.py         # POST /receive
│       ├── issuing.py           # POST /issue
│       └── transfers.py        # CRUD + state transitions
├── services/
│   ├── balance_service.py       # orchestrates receive / issue / transfer
│   ├── transfer_service.py      # state machine transitions
│   └── dispatch_service.py      # FEFO/FIFO/LIFO lot selection (already exists)
├── repositories/
│   ├── ledger_repo.py           # record_transaction() — already exists in Phase 0
│   ├── balance_repo.py          # read balance queries → read replica
│   └── transfer_repo.py         # CRUD for transfers + lines
└── models/
    ├── inventory_transaction.py
    ├── inventory_balance.py
    └── transfer.py
```

### 5.2 Core Function — `record_transaction()`

This function already exists from Phase 0. **Do not rewrite it.** Call it for every
stock mutation. Its signature:

```python
# backend/services/inventory-service/repositories/ledger_repo.py
async def record_transaction(
    db: AsyncSession,
    tx: NewTransaction
) -> InventoryTransaction:
    """
    1. Checks idempotency key — raises HTTP 409 if duplicate.
    2. Acquires SELECT FOR UPDATE lock on inventory_balances row.
    3. Validates stock floor (quantity cannot go below zero without override).
    4. INSERTs into inventory_transactions.
    5. Updates inventory_balances (on_hand / in_transit_in / in_transit_out).
    6. Writes InventoryUpdated event to outbox — SAME TRANSACTION.
    Returns the created InventoryTransaction.
    """
```

### 5.3 Receive Stock

```python
# backend/services/inventory-service/services/balance_service.py

async def receive_stock(
    db: AsyncSession,
    tenant_id: UUID,
    warehouse_id: UUID,
    product_id: UUID,
    lot_id: UUID | None,
    quantity: Decimal,
    reference_type: str,
    reference_id: UUID | None,
    performed_by: UUID,
    idempotency_key: str,
) -> InventoryTransaction:
    """
    Receiving increases on_hand at the destination warehouse.
    If this is a TRANSFER_IN receipt, also decrements in_transit_in.

    Transaction type: RECEIVE (supplier/manual) or TRANSFER_IN (from another warehouse)

    Balance changes:
      - on_hand += quantity
      - in_transit_in -= quantity  (only for TRANSFER_IN receipts)
    """
    tx_type = TransactionType.TRANSFER_IN if reference_type == "TRANSFER" else TransactionType.RECEIVE
    return await record_transaction(db, NewTransaction(
        tenant_id=tenant_id,
        transaction_type=tx_type,
        product_id=product_id,
        warehouse_id=warehouse_id,
        lot_id=lot_id,
        quantity=quantity,          # positive — always
        reference_type=reference_type,
        reference_id=reference_id,
        performed_by=performed_by,
        idempotency_key=idempotency_key,
    ))
```

### 5.4 Issue Stock

```python
async def issue_stock(
    db: AsyncSession,
    tenant_id: UUID,
    warehouse_id: UUID,
    product_id: UUID,
    lot_id: UUID | None,
    quantity: Decimal,
    destination: str | None,       # customer / department / project
    reference_type: str,
    reference_id: UUID | None,
    performed_by: UUID,
    idempotency_key: str,
) -> InventoryTransaction:
    """
    Issuing decreases on_hand at the source warehouse.

    Before calling record_transaction():
      1. Invoke dispatch_service.resolve_strategy() to get FEFO/FIFO/LIFO
      2. Invoke dispatch_service.select_lots() to pick the correct lot(s)
      3. Validate stock availability — raises InsufficientStockError if short

    Transaction type: ISSUE
    quantity passed to record_transaction() must be NEGATIVE.

    Balance changes:
      - on_hand -= quantity
    """
```

### 5.5 Transfer State Machine

```python
# backend/services/inventory-service/services/transfer_service.py

# State machine — matches CLAUDE.md §17 exactly
TRANSFER_TRANSITIONS = {
    "DRAFT":      ["SUBMITTED", "CANCELLED"],
    "SUBMITTED":  ["APPROVED", "REJECTED", "CANCELLED"],
    "APPROVED":   ["IN_TRANSIT", "CANCELLED"],
    "IN_TRANSIT": ["RECEIVED", "CANCELLED"],
    "RECEIVED":   ["CLOSED"],
    "CLOSED":     [],
    "REJECTED":   [],
    "CANCELLED":  [],
}

async def transition_transfer(
    db: AsyncSession,
    transfer_id: UUID,
    next_status: str,
    performed_by: UUID,
    user_context: UserContext,
) -> Transfer:
    """
    1. Load transfer with FOR UPDATE lock.
    2. Call validate_transition(TRANSFER_TRANSITIONS, current, next_status).
       Raises InvalidStateTransitionError → HTTP 422 on invalid jump.
    3. Check permission for this transition:
         SUBMITTED → APPROVED: requires action APPROVE_TRANSFER
         APPROVED  → IN_TRANSIT: requires action DISPATCH_TRANSFER (Warehouse Manager)
         IN_TRANSIT → RECEIVED: requires action RECEIVE_TRANSFER (destination WM)
    4. Execute stock mutation for this transition:
         → APPROVED:   record TRANSFER_OUT on source (deducts on_hand, increments in_transit_out)
                       record RESERVE on source lines that were already SUBMITTED
         → IN_TRANSIT: no balance change; status change only + update transporter details
         → RECEIVED:   for each transfer_line: record TRANSFER_IN on destination
                         (increments on_hand, decrements in_transit_in on dest)
                         record TRANSFER_OUT settlement on source (decrements in_transit_out)
                       set received_qty on each line; compute discrepancy_qty (generated column)
         → CANCELLED:  if was APPROVED or IN_TRANSIT, reverse any TRANSFER_OUT records
                       by inserting offsetting RETURN transactions
    5. Update transfer.status and transfer.updated_at.
    6. Outbox event written inside record_transaction() — no separate outbox write needed.
    """
```

### 5.6 Balance Query — Read Replica Only

```python
# backend/services/inventory-service/repositories/balance_repo.py

async def get_balance_by_location(
    db_replica: AsyncSession,   # MUST be the read replica session, never primary
    tenant_id: UUID,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
) -> list[BalanceRow]:
    """
    Returns: on_hand, in_transit_in, in_transit_out, reserved, available per SKU per location.
    available = on_hand - reserved - in_transit_out

    Query routes to read replica. NEVER call with primary db session.
    Use set_rls_context() before querying — RLS enforces tenant isolation.
    """

async def get_transaction_history(
    db_replica: AsyncSession,
    tenant_id: UUID,
    product_id: UUID | None = None,
    warehouse_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[InventoryTransaction]:
    """
    Returns paginated ledger history. Read replica only.
    Partitioned table — always include transaction_date range in WHERE clause
    to allow partition pruning.
    """
```

---

## 6. API Endpoints

All endpoints follow CLAUDE.md §19 conventions:
- Base path: `/v1/`
- Auth header: `Authorization: Bearer <JWT>`
- Response envelope: `{"data": ..., "meta": {...}}`
- Errors: `{"error": {"code": "...", "message": "...", "details": [...]}}`

### 6.1 Endpoint Definitions

```
GET    /v1/inventory/balances
       Query: warehouse_id?, product_id?, page?, page_size?
       Permission action: VIEW_WAREHOUSE_INVENTORY (action #40)
       Routes to: balance_repo.get_balance_by_location() — read replica

GET    /v1/inventory/transactions
       Query: warehouse_id?, product_id?, date_from?, date_to?, page?, page_size?
       Permission action: VIEW_STOCK_HISTORY (action #48)
       Routes to: balance_repo.get_transaction_history() — read replica

POST   /v1/inventory/receive
       Body: ReceiveRequest (warehouse_id, product_id, lot_id?, quantity,
             reference_type, reference_id?, notes?, idempotency_key)
       Permission action: ADD_RECEIVE_STOCK (action #41) — warehouse_id ABAC scope
       Routes to: balance_service.receive_stock()

POST   /v1/inventory/issue
       Body: IssueRequest (warehouse_id, product_id, lot_id?, quantity,
             destination?, reference_type, reference_id?, notes?, idempotency_key)
       Permission action: ISSUE_STOCK (action derived from #38–#45 matrix)
       Routes to: balance_service.issue_stock()

POST   /v1/transfers
       Body: CreateTransferRequest (from_warehouse_id, to_warehouse_id,
             lines: [{product_id, lot_id?, requested_qty, unit_of_measure}],
             expected_delivery?, notes?)
       Permission action: TRANSFER_STOCK (action #43)
       Returns: Transfer with status=DRAFT

GET    /v1/transfers/{transfer_id}
       Permission action: VIEW_STOCK_HISTORY (action #48)

PATCH  /v1/transfers/{transfer_id}/status
       Body: { "status": "SUBMITTED" | "APPROVED" | "IN_TRANSIT" | "RECEIVED"
                        | "CLOSED" | "REJECTED" | "CANCELLED",
               "notes"?: string,
               "transporter_details"?: object,
               "proof_of_receipt"?: string,
               "received_lines"?: [{ line_id, received_qty }] }
       Permission action: depends on transition (see §5.5)
       Routes to: transfer_service.transition_transfer()

GET    /v1/transfers
       Query: status?, from_warehouse_id?, to_warehouse_id?, page?, page_size?
       Permission action: VIEW_STOCK_HISTORY (action #48)
```

### 6.2 Register All Actions

Every endpoint's permission action **must be registered** in
`backend/shared/permissions/registry.py` before the endpoint is shipped.
CI will fail if an unregistered action is used.

---

## 7. Pydantic Schemas

```python
# backend/services/inventory-service/schemas/balance.py

class ReceiveRequest(BaseModel):
    warehouse_id:    UUID
    product_id:      UUID
    lot_id:          UUID | None = None
    quantity:        Decimal = Field(gt=0, decimal_places=4)
    reference_type:  Literal["PURCHASE_ORDER", "RETURN", "PRODUCTION", "DONATION", "MANUAL"]
    reference_id:    UUID | None = None
    notes:           str | None = None
    idempotency_key: str = Field(min_length=10, max_length=100)

class IssueRequest(BaseModel):
    warehouse_id:    UUID
    product_id:      UUID
    lot_id:          UUID | None = None
    quantity:        Decimal = Field(gt=0, decimal_places=4)
    destination:     str | None = None   # customer / department / project
    reference_type:  Literal["SALE", "INTERNAL", "DISPATCH", "PROJECT"]
    reference_id:    UUID | None = None
    notes:           str | None = None
    idempotency_key: str = Field(min_length=10, max_length=100)

class BalanceRow(BaseModel):
    product_id:      UUID
    product_name:    str
    sku:             str
    warehouse_id:    UUID
    warehouse_name:  str
    on_hand:         Decimal
    in_transit_in:   Decimal    # inbound — show as "In Transit" on UI
    in_transit_out:  Decimal    # outbound — reduces available
    reserved:        Decimal
    available:       Decimal    # on_hand - reserved - in_transit_out
    unit_of_measure: str
    last_updated:    datetime

class TransferLineCreate(BaseModel):
    product_id:      UUID
    lot_id:          UUID | None = None
    requested_qty:   Decimal = Field(gt=0, decimal_places=4)
    unit_of_measure: str

class CreateTransferRequest(BaseModel):
    from_warehouse_id:    UUID
    to_warehouse_id:      UUID
    lines:                list[TransferLineCreate] = Field(min_length=1)
    expected_delivery:    date | None = None
    transporter_details:  dict | None = None
    notes:                str | None = None

class TransferStatusUpdate(BaseModel):
    status:              Literal["SUBMITTED","APPROVED","IN_TRANSIT","RECEIVED",
                                  "CLOSED","REJECTED","CANCELLED"]
    notes:               str | None = None
    transporter_details: dict | None = None
    proof_of_receipt:    str | None = None      # S3 key
    received_lines:      list[ReceivedLine] | None = None  # required when status=RECEIVED
```

---

## 8. Frontend Components

### 8.1 File Locations

```
frontend/src/
├── app/
│   └── inventory/
│       ├── balances/
│       │   └── page.tsx           # stock balance dashboard
│       ├── receive/
│       │   └── page.tsx           # receive stock form
│       ├── issue/
│       │   └── page.tsx           # issue stock form
│       └── transfers/
│           ├── page.tsx           # transfers list
│           ├── new/page.tsx       # create transfer
│           └── [id]/page.tsx      # transfer detail + status actions
├── components/features/inventory/
│   ├── BalanceTable.tsx           # per-location per-SKU balance grid
│   ├── BalanceSummaryCards.tsx    # top-level: On Hand / In Transit / Issued totals
│   ├── ReceiveForm.tsx
│   ├── IssueForm.tsx
│   ├── TransferForm.tsx
│   ├── TransferStatusBadge.tsx    # colour-coded status pill
│   ├── TransferTimeline.tsx       # state machine progress indicator
│   └── LedgerTable.tsx            # paginated transaction history
└── hooks/
    ├── useInventoryBalance.ts     # TanStack Query → GET /v1/inventory/balances
    ├── useTransactions.ts         # TanStack Query → GET /v1/inventory/transactions
    └── useTransfer.ts             # TanStack Query + mutations for transfers
```

### 8.2 Balance Display Rules

The UI must show these columns per SKU per location with the exact field meanings:

| UI Column | Source field | Colour / meaning |
|---|---|---|
| On Hand | `balance.on_hand` | Green — physical stock present |
| In Transit | `balance.in_transit_in` | Amber — inbound, not yet received |
| Issued | sum of ISSUE transactions for period | Red — dispatched out |
| Available | `balance.available` | Blue — can be committed |

When a transfer is created and reaches APPROVED: source location's `in_transit_out`
increases — show this as a reduction to Available immediately, before physical dispatch.

When a transfer reaches IN_TRANSIT: destination location's `in_transit_in` increases —
show amber "In Transit" badge on destination immediately.

When a transfer reaches RECEIVED: destination `in_transit_in` → `on_hand`. Green.

### 8.3 Real-Time Balance Updates

Use TanStack Query with `refetchInterval: 15000` on the balance query so balances
refresh every 15 seconds without a full page reload. Optimistic updates are NOT used
for ledger mutations — always wait for server confirmation before updating the UI.

### 8.4 i18n Keys Required (en.json additions)

```json
{
  "inventory.balance.onHand": "On hand",
  "inventory.balance.inTransit": "In transit",
  "inventory.balance.issued": "Issued",
  "inventory.balance.available": "Available",
  "inventory.balance.reserved": "Reserved",
  "inventory.receive.title": "Receive stock",
  "inventory.receive.success": "Stock received successfully",
  "inventory.issue.title": "Issue stock",
  "inventory.issue.success": "Stock issued successfully",
  "inventory.issue.error.insufficientStock": "Insufficient stock. Available: {{available}}",
  "inventory.transfer.title": "Stock transfer",
  "inventory.transfer.status.DRAFT": "Draft",
  "inventory.transfer.status.SUBMITTED": "Submitted",
  "inventory.transfer.status.APPROVED": "Approved",
  "inventory.transfer.status.IN_TRANSIT": "In transit",
  "inventory.transfer.status.RECEIVED": "Received",
  "inventory.transfer.status.CLOSED": "Closed",
  "inventory.transfer.status.REJECTED": "Rejected",
  "inventory.transfer.status.CANCELLED": "Cancelled",
  "inventory.transfer.error.invalidTransition": "This status change is not permitted",
  "inventory.transfer.error.insufficientApproval": "You do not have authority to approve this transfer"
}
```

Add equivalent keys to `am.json` (Amharic). Oromifa (`or.json`) is deferred —
do not block Phase 1 on it.

### 8.5 Offline Support

Issue and Receive transactions must be queueable offline using the IndexedDB queue
(`offlineQueue.ts`). When offline:

1. Generate a local `idempotency_key` (UUID v4) and store it with the queued transaction.
2. Show a `PENDING_SYNC` status badge on any offline-created transaction.
3. On reconnect, replay the queue in order. The server's idempotency check prevents
   double-processing if the connection dropped mid-request.
4. Transfer state transitions (APPROVE, DISPATCH, RECEIVE) must NOT be queued offline —
   they require server-side approval chain validation. Show an error if attempted offline.

---

## 9. Permission Matrix for This Module

Taken directly from PRD v4.0 §14 / CLAUDE.md §13. These actions must be used exactly
as named in `permissions/registry.py`:

| Action ID | Action name | Roles that have it | ABAC scope |
|---|---|---|---|
| #40 | VIEW_WAREHOUSE_INVENTORY | SA, TA, NM, RM, WM, Auditor (R) | warehouse_id |
| #41 | ADD_RECEIVE_STOCK | WM only | warehouse_id |
| #43 | TRANSFER_STOCK | SA, NM, RM, WM | scope |
| #44 | RESERVE_INVENTORY | SA, NM, RM, WM | availability |
| #48 | VIEW_STOCK_HISTORY | SA, TA, NM, RM, WM, Auditor (R) | tenant |
| APPROVE_TRANSFER | (cascade by value) | WM → RM → NM by threshold | approval_threshold |
| RECEIVE_TRANSFER | destination WM | WM at destination warehouse_id | warehouse_id |

Transfer approval cascades by quantity/value threshold as configured per tenant in
`tenants.approval_thresholds`. Read the threshold config before routing the approval.

---

## 10. Error Handling

| Scenario | HTTP status | Error code |
|---|---|---|
| Duplicate idempotency key | 409 | `DUPLICATE_TRANSACTION` |
| Insufficient stock | 422 | `INSUFFICIENT_STOCK` |
| Invalid state transition | 422 | `INVALID_STATE_TRANSITION` |
| Source = destination on transfer | 400 | `INVALID_TRANSFER_LOCATIONS` |
| Quantity ≤ 0 | 422 | `INVALID_QUANTITY` |
| Missing permission | 403 | `PERMISSION_DENIED` |
| RLS tenant mismatch | 403 | `TENANT_ISOLATION_VIOLATION` |
| Read replica unavailable | 503 | `READ_REPLICA_UNAVAILABLE` — fall back to primary read only as last resort, log alert |

All errors must be returned in the standard envelope:
```json
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Insufficient stock at source warehouse",
    "details": {
      "product_id": "...",
      "warehouse_id": "...",
      "requested": 50,
      "available": 12
    }
  }
}
```

---

## 11. Testing Requirements

Per CLAUDE.md §21, the following test cases are mandatory before this workstream
is considered complete.

### 11.1 Unit Tests — `pytest`

```
tests/unit/services/test_balance_service.py
  - test_receive_increases_on_hand
  - test_receive_decrements_in_transit_when_transfer_in
  - test_issue_decreases_on_hand
  - test_issue_raises_insufficient_stock_when_short
  - test_issue_selects_correct_lot_per_dispatch_strategy
  - test_issue_rejects_zero_quantity

tests/unit/services/test_transfer_service.py
  - test_valid_transition_draft_to_submitted
  - test_valid_transition_submitted_to_approved
  - test_valid_transition_approved_to_in_transit
  - test_valid_transition_in_transit_to_received
  - test_invalid_transition_draft_to_in_transit_raises_422
  - test_invalid_transition_received_to_draft_raises_422
  - test_approved_transition_deducts_source_balance
  - test_received_transition_credits_destination_balance
  - test_cancelled_from_approved_reverses_balance

tests/unit/repositories/test_ledger_repo.py
  - test_duplicate_idempotency_key_raises_409
  - test_record_transaction_writes_outbox_in_same_transaction
  - test_balance_never_goes_below_zero_without_override
```

### 11.2 Integration Tests — `pytest-asyncio` + `httpx`

```
tests/integration/api/test_receiving.py
  - test_post_receive_returns_201_and_updates_balance
  - test_post_receive_is_idempotent_on_duplicate_key
  - test_post_receive_rejects_unauthenticated

tests/integration/api/test_issuing.py
  - test_post_issue_deducts_balance_and_returns_201
  - test_post_issue_returns_422_when_insufficient_stock
  - test_post_issue_rejects_wrong_warehouse_role

tests/integration/api/test_transfers.py
  - test_full_happy_path_draft_through_closed
  - test_approve_by_insufficient_role_returns_403
  - test_receive_credits_destination_on_RECEIVED_transition
  - test_discrepancy_qty_computed_correctly_on_partial_receipt
  - test_cancel_in_transit_reverses_source_balance
```

### 11.3 NFR Assertions

```
tests/performance/test_balance_query_latency.py
  - assert P95 response time < 500ms for GET /v1/inventory/balances
    with 10,000 balance rows in the read replica (NFR-2 from CLAUDE.md §23)
```

---

## 12. Definition of Done

This workstream is complete when ALL of the following are true:

- [ ] All Alembic migrations run cleanly on a fresh database
- [ ] All 115 permission actions for this module are registered in `permissions/registry.py`
- [ ] `record_transaction()` is the only path that mutates `inventory_balances`
- [ ] Every endpoint has a matching OpenAPI schema auto-generated by FastAPI
- [ ] TypeScript types are auto-generated from the OpenAPI spec in CI
- [ ] All unit and integration tests pass with zero skips
- [ ] P95 balance query latency < 500ms confirmed against the read replica
- [ ] Transfer state machine rejects all invalid transitions with HTTP 422
- [ ] Outbox rows for every transaction are written in the same DB commit
- [ ] No hardcoded strings in JSX — all text uses i18n keys
- [ ] Offline queue correctly replays issue/receive transactions on reconnect
- [ ] Transfer status actions correctly blocked from offline queue
- [ ] RLS policies verified: cross-tenant query returns 0 rows, not an error
- [ ] PR passes CI: ruff, mypy strict, TypeScript strict, all tests, permission drift check

---

## 13. Related CLAUDE.md Sections — Read Before Starting Each Area

| Task | CLAUDE.md section |
|---|---|
| Any stock mutation | §14 — Inventory Ledger — Immutable Rules |
| Transfer state machine | §17 — Workflow State Machines |
| Dispatch lot selection | §16 — Dispatch Strategy Engine |
| Any permission check | §13 — Permission System — RBAC + ABAC |
| Outbox event writing | §8 — Transactional Outbox Pattern |
| Any DB schema change | §7 — Database Schema & Conventions |
| API endpoint shape | §19 — API Conventions |
| Offline queue | §18 — Offline Sync Strategy |
| i18n string keys | §12 — Localization |
| Test structure | §21 — Testing Requirements |
| CI gates | §22 — CI/CD — GitHub Actions |

---

*SMART Inventory Platform · Claude Code Prompt · Stock Balance Module · May 2026*
*Derived from: PRD v4.0 · SOW v1.4 · CLAUDE.md v1*