"""add sku_counter and product fields for SKU auto-generation

Adds to tenants:  sku_prefix VARCHAR(10), sku_counter INTEGER
Adds to products: unit VARCHAR(10), pack_size SMALLINT
Adds constraints: UNIQUE(tenant_id, sku), UNIQUE(tenant_id, LOWER(name)),
                  CHECK pack_size IN (1, 4, 6, 12)

Revision ID: 005
Revises: 004
Create Date: 2026-05-10

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenants: SKU generation fields ────────────────────────────────────
    op.add_column(
        "tenants",
        sa.Column("sku_prefix", sa.String(10), nullable=False, server_default="SKU"),
    )
    op.add_column(
        "tenants",
        sa.Column("sku_counter", sa.Integer, nullable=False, server_default="0"),
    )

    # ── products: unit and pack_size ──────────────────────────────────────
    # DEFAULT values cover any pre-existing rows; constraints enforce future writes.
    op.add_column(
        "products",
        sa.Column("unit", sa.String(10), nullable=False, server_default="KG"),
    )
    op.add_column(
        "products",
        sa.Column("pack_size", sa.SmallInteger, nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_products_pack_size",
        "products",
        "pack_size IN (1, 4, 6, 12)",
    )

    # ── UNIQUE (tenant_id, sku) ───────────────────────────────────────────
    # The existing non-unique index idx_products_tenant_sku must be dropped first.
    op.drop_index("idx_products_tenant_sku", table_name="products")
    op.create_unique_constraint(
        "uq_products_tenant_sku",
        "products",
        ["tenant_id", "sku"],
    )

    # ── UNIQUE (tenant_id, LOWER(name)) — functional unique index ─────────
    op.execute(
        "CREATE UNIQUE INDEX uq_products_tenant_name_lower "
        "ON products (tenant_id, LOWER(name)) WHERE is_active = true"
    )


def downgrade() -> None:
    # Remove functional index first
    op.execute("DROP INDEX IF EXISTS uq_products_tenant_name_lower")

    # Restore the original non-unique index
    op.drop_constraint("uq_products_tenant_sku", "products", type_="unique")
    op.create_index("idx_products_tenant_sku", "products", ["tenant_id", "sku"])

    # Remove CHECK constraint and new columns from products
    op.drop_constraint("ck_products_pack_size", "products", type_="check")
    op.drop_column("products", "pack_size")
    op.drop_column("products", "unit")

    # Remove SKU generation columns from tenants
    op.drop_column("tenants", "sku_counter")
    op.drop_column("tenants", "sku_prefix")
