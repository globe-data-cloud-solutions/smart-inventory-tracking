"""workflow tables — transfer_orders, adjustment_orders, count_sessions

Revision ID: 002
Revises: 001
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── warehouses ────────────────────────────────────────────────────────
    op.create_table(
        "warehouses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_warehouses_tenant", "warehouses", ["tenant_id"])
    op.execute("ALTER TABLE warehouses ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON warehouses "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── transfer_orders ───────────────────────────────────────────────────
    op.create_table(
        "transfer_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_transfer_orders_tenant", "transfer_orders", ["tenant_id", "status"]
    )
    op.execute("ALTER TABLE transfer_orders ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON transfer_orders "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── transfer_order_lines ──────────────────────────────────────────────
    op.create_table(
        "transfer_order_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "transfer_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transfer_orders.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(15, 4), nullable=False),
        sa.Column("lot_number", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_transfer_lines_order",
        "transfer_order_lines",
        ["tenant_id", "transfer_order_id"],
    )

    # ── adjustment_orders ─────────────────────────────────────────────────
    op.create_table(
        "adjustment_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(15, 4), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_adjustment_orders_tenant", "adjustment_orders", ["tenant_id", "status"]
    )
    op.execute("ALTER TABLE adjustment_orders ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON adjustment_orders "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── count_sessions ────────────────────────────────────────────────────
    op.create_table(
        "count_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_count_sessions_tenant", "count_sessions", ["tenant_id", "warehouse_id"]
    )
    op.execute("ALTER TABLE count_sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON count_sessions "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── dispatch_override_logs ────────────────────────────────────────────
    # Required by CLAUDE.md rule: FEFO override writes to dispatch_override_logs
    op.create_table(
        "dispatch_override_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("overridden_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_strategy", sa.String(10), nullable=False),
        sa.Column("applied_strategy", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_dispatch_overrides_tenant",
        "dispatch_override_logs",
        ["tenant_id", "created_at"],
    )
    op.execute("ALTER TABLE dispatch_override_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON dispatch_override_logs "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("dispatch_override_logs")
    op.drop_table("count_sessions")
    op.drop_table("adjustment_orders")
    op.drop_table("transfer_order_lines")
    op.drop_table("transfer_orders")
    op.drop_table("warehouses")
