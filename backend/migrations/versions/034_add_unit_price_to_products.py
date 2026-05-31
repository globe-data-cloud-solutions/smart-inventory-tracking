"""034 — add unit_price and currency to products

Adds monetary value tracking to products so transfer approval rules can
optionally route on value (quantity × unit_price) in addition to quantity.

Revision ID: 034
Revises:     033
Create Date: 2026-05-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("unit_price", sa.Numeric(15, 4), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("currency", sa.String(3), server_default="ETB", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "currency")
    op.drop_column("products", "unit_price")
