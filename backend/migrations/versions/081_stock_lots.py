"""081 — stock_lots, lot_balances, and lot-aware product flags.

Adds a normalized lot model alongside the existing inventory_balances table:
  stock_lots    — one row per (tenant, product, lot_number); immutable identity
                  (lot_number, expiry_date, first_received_at — never changed
                  when the lot moves between warehouses).
  lot_balances  — one row per (tenant, lot_id, warehouse_id); the per-warehouse
                  on-hand quantity for that lot. Same RLS + tenant-leading-index
                  pattern as inventory_balances (001).

Both tables are additive: this migration does NOT touch the existing
lot-as-extra-row convention in inventory_balances (lot_number column there,
used today by dispatch_service.select_lots). That path is untouched by this
migration; reconciling the two lot representations is a later session's work.

inventory_transactions gets a nullable lot_id (no FK — partitioned table,
can't easily FK to it; lot_number/expiry_date columns already exist there
since 001).

products gets:
  - track_expiry: distinct from the existing expiry_tracking column.
    NOTE: products.expiry_tracking (001) already serves this purpose and is
    live in dispatch_service.resolve_strategy(). Rather than add a duplicate,
    ambiguous flag, this migration reuses expiry_tracking for the new
    ck_products_expiry_needs_batch constraint instead of adding track_expiry.
  - dispatch_strategy, using the existing dispatch_strategy enum
    (create_type=False — the type already exists from 001's
    dispatch_strategy_configs.strategy column).

dispatch_strategy_configs is commented ARCHIVED per this session's brief —
superseded by products.dispatch_strategy — but not dropped (existing rows
and dispatch_service.py's scope-lookup path still read it).

Revision ID: 081
Revises:     080
Create Date: 2026-10-12

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── stock_lots ────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE stock_lots (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL,
            product_id         UUID NOT NULL REFERENCES products(id),
            lot_number         VARCHAR(100) NOT NULL,
            expiry_date        DATE,
            first_received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_opening         BOOLEAN NOT NULL DEFAULT false,
            created_by         UUID NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, product_id, lot_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_stock_lots_tenant_product_expiry ON stock_lots "
        "(tenant_id, product_id, expiry_date)"
    )
    op.execute("ALTER TABLE stock_lots ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON stock_lots "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── lot_balances ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE lot_balances (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL,
            lot_id        UUID NOT NULL REFERENCES stock_lots(id),
            product_id    UUID NOT NULL,
            warehouse_id  UUID NOT NULL,
            quantity      NUMERIC(15,4) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, lot_id, warehouse_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_lot_balances_tenant_product_warehouse ON lot_balances "
        "(tenant_id, product_id, warehouse_id)"
    )
    op.execute("ALTER TABLE lot_balances ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON lot_balances "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── inventory_transactions: lot_id (no FK — partitioned table) ─────────
    op.execute("ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS lot_id UUID")

    # ── products: lot-aware flags ───────────────────────────────────────────
    # dispatch_strategy reuses the dispatch_strategy enum type created by 001
    # (create_type=False — do not re-create it here).
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS dispatch_strategy dispatch_strategy"
    )
    op.execute(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_products_expiry_needs_batch') THEN "
        "    ALTER TABLE products ADD CONSTRAINT ck_products_expiry_needs_batch "
        "    CHECK (NOT expiry_tracking OR batch_tracking); "
        "  END IF; "
        "END $$"
    )

    # ── dispatch_strategy_configs: mark archived, superseded by the column above
    op.execute(
        "COMMENT ON TABLE dispatch_strategy_configs IS "
        "'ARCHIVED (081): unused; superseded by products.dispatch_strategy. Do not use.'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON TABLE dispatch_strategy_configs IS NULL")
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS ck_products_expiry_needs_batch")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS dispatch_strategy")
    op.execute("ALTER TABLE inventory_transactions DROP COLUMN IF EXISTS lot_id")
    op.execute("DROP TABLE IF EXISTS lot_balances")
    op.execute("DROP TABLE IF EXISTS stock_lots")
