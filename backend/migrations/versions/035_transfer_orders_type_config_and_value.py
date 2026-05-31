"""035 — add transfer_type_config_id, total_value, currency to transfer_orders

Allows transfer orders to reference a tenant-configured transfer type
(for display name lookup and level-permission validation) and to store
the calculated value for approval threshold evaluation.

Revision ID: 035
Revises:     034
Create Date: 2026-05-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transfer_orders",
        sa.Column(
            "transfer_type_config_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="FK to transfer_type_config — NULL on pre-migration rows",
        ),
    )
    op.add_column(
        "transfer_orders",
        sa.Column("total_value", sa.Numeric(15, 4), nullable=True,
                  comment="qty × unit_price summed across all lines; NULL when unit_price absent"),
    )
    op.add_column(
        "transfer_orders",
        sa.Column("currency", sa.String(3), server_default="ETB", nullable=True),
    )
    op.create_foreign_key(
        "fk_transfer_orders_type_config",
        "transfer_orders", "transfer_type_config",
        ["transfer_type_config_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_transfer_orders_type_config", "transfer_orders", type_="foreignkey")
    op.drop_column("transfer_orders", "currency")
    op.drop_column("transfer_orders", "total_value")
    op.drop_column("transfer_orders", "transfer_type_config_id")
