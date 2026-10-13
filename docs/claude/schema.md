## 7. Database — PostgreSQL Schema & Conventions

### Column rules for every table

```
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID NOT NULL                       — on every tenant-scoped table
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
created_by      UUID                                — on all transactional tables
is_active       BOOLEAN NOT NULL DEFAULT true       — soft delete, never hard-delete
```

### Index rule — `tenant_id` leads every composite index

```sql
-- CORRECT
CREATE INDEX idx_products_tenant_sku ON products (tenant_id, sku);
-- WRONG — tenant_id not leading
CREATE INDEX idx_products_sku ON products (sku);
```

### Product SKU generation — `sku` vs `sku_override`

```
SKUs are server-generated from type_code + sequence. The sku field in POST /products
is ignored. Use sku_override to supply a custom SKU — this is the only path that
triggers the uq_products_tenant_sku uniqueness check.
```

### RLS — apply to every tenant-scoped table in the same migration

```sql
ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <table_name>
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

### Set RLS context before every query

```python
# backend/shared/db/rls.py
async def set_rls_context(session: AsyncSession, tenant_id: str, user_id: str) -> None:
    """Must be called at the start of every request handler. Without this, RLS blocks all queries."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id',:tid,true),"
             "set_config('app.current_user_id',:uid,true)"),
        {"tid": tenant_id, "uid": user_id}
    )
```

### Core schema — Phase 0 required tables

```sql
CREATE TYPE organisation_type AS ENUM ('PRODUCER', 'RETAILER', 'HYBRID');
CREATE TYPE transaction_type  AS ENUM (
  'RECEIVE','TRANSFER_OUT','TRANSFER_IN','ISSUE',
  'ADJUSTMENT','RESERVE','RELEASE','RETURN','COUNT_VARIANCE');
CREATE TYPE dispatch_strategy AS ENUM ('FEFO','FIFO','LIFO');
-- IMTS enhancement: type-specific transfer statuses replace the single transfer_status enum
CREATE TYPE pull_status AS ENUM (
  'DRAFT','PENDING_REVIEW','PENDING_APPROVAL','APPROVED','ISSUED',
  'IN_TRANSIT','PARTIALLY_RECEIVED','RECEIVED','COMPLETED','REJECTED','CANCELLED');
CREATE TYPE push_status AS ENUM (
  'DRAFT','PENDING_APPROVAL','APPROVED','ADVISED','ISSUED',
  'IN_TRANSIT','PARTIALLY_RECEIVED','RECEIVED','COMPLETED','REJECTED','CANCELLED');
CREATE TYPE sister_status AS ENUM (
  'DRAFT','PENDING_SOURCE_CONFIRM','PENDING_DEST_CONFIRM','PENDING_APPROVAL',
  'APPROVED','ISSUED','IN_TRANSIT','PARTIALLY_RECEIVED','RECEIVED','COMPLETED',
  'REJECTED','CANCELLED');
CREATE TYPE adjustment_status AS ENUM ('DRAFT','PENDING_APPROVAL','APPROVED','POSTED','REJECTED');
-- Legacy kept for backward compatibility during migration
CREATE TYPE transfer_status   AS ENUM (
  'DRAFT','SUBMITTED','APPROVED','IN_TRANSIT','RECEIVED','CLOSED','REJECTED','CANCELLED');
-- IMTS: org node relationship types
CREATE TYPE node_relationship AS ENUM ('PRIMARY_REPORTS_TO','SUPPLY_FROM','DISTRIBUTE_TO');
CREATE TYPE role_code         AS ENUM ('SA','TA','NM','RM','WM','LM','SA_GT','RT','AU','SYS');
CREATE TYPE grant_type        AS ENUM ('FULL','CONDITIONAL','READ_ONLY');
CREATE TYPE outbox_status     AS ENUM ('PENDING','PROCESSING','PROCESSED','FAILED');
CREATE TYPE supported_locale  AS ENUM ('en','am','or');

-- Tenants — parent_tenant_id is Phase 4 placeholder, NEVER DROP THIS COLUMN
CREATE TABLE tenants (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                VARCHAR(255) NOT NULL,
  organisation_type   organisation_type NOT NULL,
  parent_tenant_id    UUID REFERENCES tenants(id),   -- Phase 4 franchise — NEVER DROP
  plan_id             UUID NOT NULL,
  feature_flags       JSONB NOT NULL DEFAULT '{}',
  sku_cap             INTEGER,                        -- NULL = unlimited (RETAILER)
  approval_thresholds JSONB NOT NULL DEFAULT '{}',
  default_locale      supported_locale NOT NULL DEFAULT 'en',
  onboarding_complete BOOLEAN NOT NULL DEFAULT false,
  is_active           BOOLEAN NOT NULL DEFAULT true,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- inventory_transactions — MUST be partitioned from Phase 0
CREATE TABLE inventory_transactions (
  id               UUID NOT NULL DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL,
  transaction_date DATE NOT NULL,
  type             transaction_type NOT NULL,
  product_id       UUID NOT NULL,
  warehouse_id     UUID NOT NULL,         -- maps to organization_node.id (IMTS: facility_id)
  quantity         NUMERIC(15,4) NOT NULL,
  unit_cost        NUMERIC(15,4),
  lot_number       VARCHAR(100),
  expiry_date      DATE,
  idempotency_key  VARCHAR(255) NOT NULL,
  reference_id     UUID,
  -- IMTS: parent_transfer_id links split-request legs to their parent record
  parent_transfer_id UUID REFERENCES inventory_transactions(id),
  -- IMTS: estimated vs actual arrival tracking (required for In Transit overdue alerts)
  estimated_arrival_date DATE,
  actual_arrival_date    DATE,
  source           VARCHAR(20) DEFAULT 'WEB',
  created_by       UUID NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, transaction_date)
) PARTITION BY RANGE (transaction_date);

CREATE TABLE inventory_transaction_keys (
  idempotency_key VARCHAR(255) PRIMARY KEY,
  transaction_id  UUID NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_inv_tx_tenant_product
  ON inventory_transactions (tenant_id, product_id, transaction_date);

-- Outbox — replaces Kafka topics
CREATE TABLE outbox (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL,
  event_type   VARCHAR(100) NOT NULL,
  payload      JSONB NOT NULL,
  payload_ver  VARCHAR(10) NOT NULL DEFAULT '1.0',
  status       outbox_status NOT NULL DEFAULT 'PENDING',
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);
CREATE INDEX idx_outbox_pending ON outbox (status, created_at)
  WHERE status IN ('PENDING','FAILED');

-- NOTIFY trigger — wakes Celery workers immediately on INSERT
CREATE OR REPLACE FUNCTION notify_outbox() RETURNS TRIGGER AS $$
BEGIN
  PERFORM pg_notify('outbox_insert', NEW.id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outbox_notify AFTER INSERT ON outbox
  FOR EACH ROW EXECUTE FUNCTION notify_outbox();

-- ── warehouse_stock — COMPUTED READ MODEL (never write directly from application code) ─
--
-- CRITICAL: warehouse_stock is a materialised read model derived entirely from
-- inventory_transactions INSERTs. Application code NEVER issues:
--   UPDATE warehouse_stock SET on_hand = …
-- Doing so bypasses the immutable ledger, breaks audit trails, and violates Business Rule #2.
--
-- How balances are maintained:
--   1. record_transaction() INSERTs a row into inventory_transactions (the ledger).
--   2. update_running_balance() is called in the same DB transaction and issues
--      UPDATE warehouse_stock SET … only from within ledger_repo.py.
--   3. No other code path may touch warehouse_stock columns directly.
--   4. warehouse_stock is queried (SELECT) freely for dashboards and balance checks.
--
-- The IMTS warehouse_stock table referenced in IMTS §13.2 is this same table.
-- It is NOT an independent mutable store. It is a denormalised read cache of ledger state.
CREATE TABLE warehouse_stock (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  facility_id    UUID NOT NULL REFERENCES organization_node(id),
  product_id     UUID NOT NULL,
  on_hand        NUMERIC(15,4) NOT NULL DEFAULT 0,
  reserved       NUMERIC(15,4) NOT NULL DEFAULT 0,
  in_transit_in  NUMERIC(15,4) NOT NULL DEFAULT 0,
  in_transit_out NUMERIC(15,4) NOT NULL DEFAULT 0,
  -- available is always computed: on_hand - reserved. Never stored separately.
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, facility_id, product_id)
);
CREATE INDEX idx_wstock_tenant_facility ON warehouse_stock (tenant_id, facility_id);
ALTER TABLE warehouse_stock ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON warehouse_stock
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
-- Prevent any direct UPDATE from outside ledger_repo.py at the DB level (defence in depth)
-- Note: update_running_balance() in ledger_repo.py uses a privileged session role that
-- bypasses this check. All other application sessions are denied direct writes.
CREATE RULE no_direct_stock_update AS ON UPDATE TO warehouse_stock
  WHERE current_setting('app.ledger_write_allowed', true) IS DISTINCT FROM 'true'
  DO INSTEAD NOTHING;
CREATE TABLE dispatch_strategy_configs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES tenants(id),
  scope          VARCHAR(20) NOT NULL CHECK (scope IN ('PRODUCT','CATEGORY')),
  scope_id       UUID NOT NULL,
  strategy       dispatch_strategy NOT NULL,
  effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
  configured_by  UUID NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_dispatch_scope
  ON dispatch_strategy_configs (tenant_id, scope, scope_id);

-- Audit logs — append-only
CREATE TABLE audit_logs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id       UUID,
  role          role_code,
  action        VARCHAR(100) NOT NULL,
  resource_type VARCHAR(100),
  resource_id   UUID,
  decision      VARCHAR(20) NOT NULL,
  reason        TEXT,
  abac_context  JSONB,
  ip_address    INET,
  request_id    VARCHAR(100)
);
CREATE INDEX idx_audit_tenant_ts ON audit_logs (tenant_id, timestamp);
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_select ON audit_logs FOR SELECT
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
-- Immutability — these rules must NEVER be removed
CREATE RULE no_update_audit AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE no_delete_audit AS ON DELETE TO audit_logs DO INSTEAD NOTHING;

-- ── IMTS: Organisational Hierarchy Tables ─────────────────────────────────────

-- Tenant hierarchy configuration — supports 2-to-5 level org structures per tenant
CREATE TABLE tenant_hierarchy_config (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id),
  level        INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
  label        VARCHAR(100) NOT NULL,   -- e.g. 'Main Production', 'Region', 'Warehouse'
  code         VARCHAR(20) NOT NULL,    -- e.g. 'MAIN', 'REG', 'WH'
  is_mandatory BOOLEAN NOT NULL DEFAULT false,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, level)
);
CREATE INDEX idx_hier_config_tenant ON tenant_hierarchy_config (tenant_id);
ALTER TABLE tenant_hierarchy_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenant_hierarchy_config
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- Organisation nodes — each facility (MWH, RWH, WH, Sub-WH) is a node
-- warehouse_id in JWT payload maps to organization_node.id regardless of hierarchy level
CREATE TABLE organization_node (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES tenants(id),
  name             VARCHAR(255) NOT NULL,
  code             VARCHAR(50) NOT NULL,
  hierarchy_level  INTEGER NOT NULL,   -- references tenant_hierarchy_config.level
  is_active        BOOLEAN NOT NULL DEFAULT true,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_org_node_tenant ON organization_node (tenant_id, hierarchy_level);
ALTER TABLE organization_node ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON organization_node
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- Org node relationships — separates reporting from supply network topology
-- A facility can report to one parent but receive stock from multiple sources
CREATE TABLE org_node_hierarchy (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id),
  from_node_id      UUID NOT NULL REFERENCES organization_node(id),
  to_node_id        UUID NOT NULL REFERENCES organization_node(id),
  relationship_type node_relationship NOT NULL,
  is_preferred      BOOLEAN NOT NULL DEFAULT false,  -- preferred supply source
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_org_hier_from ON org_node_hierarchy (tenant_id, from_node_id, relationship_type);
CREATE INDEX idx_org_hier_to   ON org_node_hierarchy (tenant_id, to_node_id, relationship_type);
ALTER TABLE org_node_hierarchy ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON org_node_hierarchy
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── IMTS: Configurable Approval Workflow Tables ───────────────────────────────

-- approval_rule — per-tenant, per-transaction-type, threshold-based routing config
CREATE TABLE approval_rule (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id),
  transaction_type  VARCHAR(20) NOT NULL,   -- 'PULL','PUSH','SISTER','DAMAGE','EXCESS'
  min_quantity      NUMERIC(15,4),           -- NULL = applies to any quantity
  max_quantity      NUMERIC(15,4),           -- NULL = no upper bound
  approver_role     role_code NOT NULL,
  approval_order    INTEGER NOT NULL DEFAULT 1,
  is_active         BOOLEAN NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approval_rule_tenant ON approval_rule (tenant_id, transaction_type);
ALTER TABLE approval_rule ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON approval_rule
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- approval_history — full audit trail of every approval action on every transaction
CREATE TABLE approval_history (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES tenants(id),
  transaction_id   UUID NOT NULL,
  approval_rule_id UUID REFERENCES approval_rule(id),
  approver_id      UUID NOT NULL,
  approver_role    role_code NOT NULL,
  action           VARCHAR(20) NOT NULL,  -- 'APPROVED','REJECTED','ESCALATED','AUTO_APPROVED'
  notes            TEXT,
  actioned_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approval_hist_tx ON approval_history (tenant_id, transaction_id);
ALTER TABLE approval_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON approval_history
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
-- Approval history is append-only — no UPDATE or DELETE permitted
CREATE RULE no_update_approval_hist AS ON UPDATE TO approval_history DO INSTEAD NOTHING;
CREATE RULE no_delete_approval_hist AS ON DELETE TO approval_history DO INSTEAD NOTHING;

-- ── IMTS: Enhanced Stock Threshold Table ─────────────────────────────────────
-- Replaces the implied per-product threshold concept with an explicit table
-- including preferred and secondary source facility references
CREATE TABLE stock_threshold (
  id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                  UUID NOT NULL REFERENCES tenants(id),
  facility_id                UUID NOT NULL REFERENCES organization_node(id),
  product_id                 UUID NOT NULL,
  max_threshold              NUMERIC(15,4) NOT NULL,
  reorder_point              NUMERIC(15,4) NOT NULL,
  min_threshold              NUMERIC(15,4) NOT NULL,
  preferred_source_id        UUID REFERENCES organization_node(id),  -- IMTS: preferred source
  secondary_source_id        UUID REFERENCES organization_node(id),  -- IMTS: fallback source
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, facility_id, product_id)
);
CREATE INDEX idx_threshold_tenant_facility ON stock_threshold (tenant_id, facility_id);
ALTER TABLE stock_threshold ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stock_threshold
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── lot_allocation_overrides (migration 083) ─────────────────────────────────
-- One row per dispatch where the user's lot selection differed from the engine's
-- suggestion. Append-only BY CODE: dispatch_service.record_override() is the only
-- writer and no update/delete function exists (no PostgreSQL RULE on this table).
CREATE TABLE lot_allocation_overrides (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL,
  product_id     UUID NOT NULL REFERENCES products(id),
  warehouse_id   UUID NOT NULL,
  strategy       dispatch_strategy NOT NULL,     -- existing enum
  movement_type  VARCHAR(30) NOT NULL,           -- e.g. ISSUE, TRANSFER, ADJUSTMENT
  reference_id   UUID,                           -- the movement/transfer id, set by the caller
  requested_qty  NUMERIC(15,4) NOT NULL CHECK (requested_qty > 0),
  suggested      JSONB NOT NULL,                 -- [{lot_id, lot_number, quantity}] engine order
  chosen         JSONB NOT NULL,                 -- [{lot_id, lot_number, quantity}] user choice
  reason         TEXT,                           -- required by code for FEFO overrides
  overridden_by  UUID NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_lot_allocation_overrides_tenant_product_created
  ON lot_allocation_overrides (tenant_id, product_id, created_at);
ALTER TABLE lot_allocation_overrides ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON lot_allocation_overrides
  USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

### Alembic migration rules

```
Every migration must:
  1. Have a descriptive name:  alembic revision --autogenerate -m "add_dispatch_strategy_configs"
  2. Implement both upgrade() and downgrade()
  3. Be tested: alembic upgrade head → downgrade -1 → upgrade head
  4. Include RLS policy if the table is tenant-scoped
  5. Include composite indexes with tenant_id as the leading column
```

