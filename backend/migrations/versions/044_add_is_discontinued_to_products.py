"""Add is_discontinued column to products table.

Revision ID: 044
Revises: 043
Create Date: 2026-06-06
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_discontinued", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_tenant_active "
        "ON products (tenant_id, is_discontinued) WHERE is_discontinued = FALSE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_tenant_active")
    op.drop_column("products", "is_discontinued")
