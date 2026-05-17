"""initial schema — Phase 0 required tables

Revision ID: 001
Revises:
Create Date: 2026-05-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ENUMs are created implicitly by op.create_table via SQLAlchemy's
    # _on_table_create mechanism.  The memo system (_check_for_name_in_memos)
    # ensures each type is emitted only once even when used in multiple tables.
    # Do NOT add explicit op.execute("CREATE TYPE ...") — that causes a
    # duplicate-type error because op.create_table already handles it.

    # ── tenants ───────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("organisation_type",
                  sa.Enum("PRODUCER", "RETAILER", "HYBRID", name="organisation_type"),
                  nullable=False),
        sa.Column("parent_tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_flags", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("sku_cap", sa.Integer, nullable=True),
        sa.Column("approval_thresholds", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("default_locale",
                  sa.Enum("en", "am", "or", name="supported_locale"),
                  nullable=False, server_default="en"),
        sa.Column("onboarding_complete", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )

    # ── users ─────────────────────────────────────────────────────────────
    # role_code and supported_locale are already in the DB from the tenants table above.
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("cognito_sub", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role",
                  sa.Enum("SA","TA","NM","RM","WM","LM","SA_GT","RT","AU","SYS",
                          name="role_code"),
                  nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("locale",
                  sa.Enum("en","am","or", name="supported_locale"),
                  nullable=False, server_default="en"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_users_tenant", "users", ["tenant_id"])
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON users "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── product_categories ────────────────────────────────────────────────
    op.create_table(
        "product_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_categories.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_categories_tenant", "product_categories", ["tenant_id"])
    op.execute("ALTER TABLE product_categories ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_categories "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── products ──────────────────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_categories.id"), nullable=True),
        sa.Column("barcode", sa.String(100), nullable=True),
        sa.Column("unit_of_measure", sa.String(50), nullable=False),
        sa.Column("batch_tracking", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("expiry_tracking", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reorder_point", sa.Numeric(15, 4), nullable=True),
        sa.Column("attributes", postgresql.JSONB, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_products_tenant_sku", "products", ["tenant_id", "sku"])
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX idx_products_name_trgm ON products "
        "USING gin (name gin_trgm_ops)"
    )
    op.execute("ALTER TABLE products ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON products "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── inventory_transactions (partitioned by transaction_date) ──────────
    # Uses raw SQL because op.create_table doesn't support PARTITION BY.
    # The transaction_type enum will be created by the raw DDL below.
    op.execute("CREATE TYPE transaction_type AS ENUM "
               "('RECEIVE','TRANSFER_OUT','TRANSFER_IN','ISSUE',"
               "'ADJUSTMENT','RESERVE','RELEASE','RETURN','COUNT_VARIANCE')")
    op.execute("CREATE TYPE transfer_status AS ENUM "
               "('DRAFT','SUBMITTED','APPROVED','IN_TRANSIT','RECEIVED','CLOSED','REJECTED','CANCELLED')")
    op.execute(
        """
        CREATE TABLE inventory_transactions (
            id               UUID NOT NULL DEFAULT gen_random_uuid(),
            transaction_date DATE NOT NULL,
            tenant_id        UUID NOT NULL,
            type             transaction_type NOT NULL,
            product_id       UUID NOT NULL,
            warehouse_id     UUID NOT NULL,
            quantity         NUMERIC(15,4) NOT NULL,
            unit_cost        NUMERIC(15,4),
            lot_number       VARCHAR(100),
            expiry_date      DATE,
            idempotency_key  VARCHAR(255) NOT NULL,
            reference_id     UUID,
            source           VARCHAR(20) DEFAULT 'WEB',
            created_by       UUID NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, transaction_date)
        ) PARTITION BY RANGE (transaction_date)
        """
    )
    op.create_index(
        "idx_inv_tx_tenant_product",
        "inventory_transactions",
        ["tenant_id", "product_id", "transaction_date"],
    )
    op.execute("ALTER TABLE inventory_transactions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON inventory_transactions "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── inventory_transaction_keys ────────────────────────────────────────
    op.create_table(
        "inventory_transaction_keys",
        sa.Column("idempotency_key", sa.String(255), primary_key=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )

    # ── inventory_balances ────────────────────────────────────────────────
    op.create_table(
        "inventory_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(15, 4), nullable=False, server_default="0"),
        sa.Column("lot_number", sa.String(100), nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_balances_tenant_product_warehouse",
        "inventory_balances",
        ["tenant_id", "product_id", "warehouse_id"],
        unique=True,
        postgresql_where=sa.text("lot_number IS NULL"),
    )
    op.execute("ALTER TABLE inventory_balances ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON inventory_balances "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── dispatch_strategy_configs ─────────────────────────────────────────
    op.create_table(
        "dispatch_strategy_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy",
                  sa.Enum("FEFO","FIFO","LIFO", name="dispatch_strategy"),
                  nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("configured_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_dispatch_scope",
        "dispatch_strategy_configs",
        ["tenant_id", "scope", "scope_id"],
        unique=True,
    )
    op.execute("ALTER TABLE dispatch_strategy_configs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON dispatch_strategy_configs "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── outbox ────────────────────────────────────────────────────────────
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("payload_ver", sa.String(10), nullable=False, server_default="1.0"),
        sa.Column("status",
                  sa.Enum("PENDING","PROCESSING","PROCESSED","FAILED",
                          name="outbox_status"),
                  nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_outbox_pending", "outbox", ["status", "created_at"],
        postgresql_where=sa.text("status IN ('PENDING','FAILED')")
    )

    # pg_notify trigger
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_outbox() RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('outbox_insert', NEW.id::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER outbox_notify AFTER INSERT ON outbox "
        "FOR EACH ROW EXECUTE FUNCTION notify_outbox()"
    )

    # ── audit_logs ────────────────────────────────────────────────────────
    # role_code is already created by the users table above.
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role",
                  sa.Enum("SA","TA","NM","RM","WM","LM","SA_GT","RT","AU","SYS",
                          name="role_code"),
                  nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("abac_context", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
    )
    op.create_index("idx_audit_tenant_ts", "audit_logs", ["tenant_id", "timestamp"])
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_select ON audit_logs FOR SELECT "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    # Immutability rules — NEVER remove these
    op.execute("CREATE RULE no_update_audit AS ON UPDATE TO audit_logs DO INSTEAD NOTHING")
    op.execute("CREATE RULE no_delete_audit AS ON DELETE TO audit_logs DO INSTEAD NOTHING")

    # ── role_permissions ──────────────────────────────────────────────────
    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_code", sa.String(10), nullable=False),
        sa.Column("action_id", sa.String(100), nullable=False),
        sa.Column("grant_type",
                  sa.Enum("FULL","CONDITIONAL","READ_ONLY", name="grant_type"),
                  nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_role_permissions_role_action",
        "role_permissions",
        ["role_code", "action_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("role_permissions")
    op.execute("DROP TYPE IF EXISTS grant_type")
    op.execute("DROP RULE IF EXISTS no_delete_audit ON audit_logs")
    op.execute("DROP RULE IF EXISTS no_update_audit ON audit_logs")
    op.drop_table("audit_logs")
    op.execute("DROP TRIGGER IF EXISTS outbox_notify ON outbox")
    op.execute("DROP FUNCTION IF EXISTS notify_outbox()")
    op.drop_table("outbox")
    op.execute("DROP TYPE IF EXISTS outbox_status")
    op.drop_table("dispatch_strategy_configs")
    op.execute("DROP TYPE IF EXISTS dispatch_strategy")
    op.drop_table("inventory_balances")
    op.drop_table("inventory_transaction_keys")
    op.execute("DROP TABLE IF EXISTS inventory_transactions")
    op.execute("DROP TYPE IF EXISTS transfer_status")
    op.execute("DROP TYPE IF EXISTS transaction_type")
    op.drop_table("products")
    op.drop_table("product_categories")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS role_code")
    op.execute("DROP TYPE IF EXISTS supported_locale")
    op.drop_table("tenants")
    op.execute("DROP TYPE IF EXISTS organisation_type")
