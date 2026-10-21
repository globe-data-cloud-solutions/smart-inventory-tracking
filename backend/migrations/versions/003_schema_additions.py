"""schema additions: warehouse_type, warehouse code, tenant slug,
product reorder_quantity, transfer_orders reference_number

Revision ID: 003
Revises: 002
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── warehouse_type enum + code column ─────────────────────────────────
    op.execute(
        "CREATE TYPE warehouse_type AS ENUM ('FACTORY','REGIONAL','RETAIL','SUBCENTER')"
    )
    op.add_column(
        "warehouses",
        sa.Column(
            "warehouse_type",
            sa.Enum(
                "FACTORY", "REGIONAL", "RETAIL", "SUBCENTER", name="warehouse_type"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "warehouses",
        sa.Column("code", sa.String(50), nullable=True),
    )
    op.create_index(
        "idx_warehouses_tenant_code",
        "warehouses",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL"),
    )

    # ── tenant slug ───────────────────────────────────────────────────────
    op.add_column(
        "tenants",
        sa.Column("slug", sa.String(100), nullable=True),
    )
    op.create_index(
        "idx_tenants_slug",
        "tenants",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("slug IS NOT NULL"),
    )

    # ── product reorder_quantity ──────────────────────────────────────────
    # reorder_point already exists; reorder_quantity is the suggested order size
    op.add_column(
        "products",
        sa.Column("reorder_quantity", sa.Numeric(15, 4), nullable=True),
    )

    # ── transfer_orders reference_number ─────────────────────────────────
    op.add_column(
        "transfer_orders",
        sa.Column("reference_number", sa.String(100), nullable=True),
    )
    op.create_index(
        "idx_transfer_orders_ref",
        "transfer_orders",
        ["tenant_id", "reference_number"],
        unique=True,
        postgresql_where=sa.text("reference_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_transfer_orders_ref", table_name="transfer_orders")
    op.drop_column("transfer_orders", "reference_number")
    op.drop_column("products", "reorder_quantity")
    op.drop_index("idx_tenants_slug", table_name="tenants")
    op.drop_column("tenants", "slug")
    op.drop_index("idx_warehouses_tenant_code", table_name="warehouses")
    op.drop_column("warehouses", "code")
    op.drop_column("warehouses", "warehouse_type")
    op.execute("DROP TYPE warehouse_type")
