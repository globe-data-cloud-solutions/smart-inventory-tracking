"""036 — add resolved_approval_steps and current_approval_step to transfer_orders

Stores the dynamically-resolved approval chain (from Session 6) directly on the
transfer order row so approval-info queries don't re-run resolution on every call.

Revision ID: 036
Revises:     035
Create Date: 2026-05-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transfer_orders",
        sa.Column(
            "resolved_approval_steps",
            postgresql.JSONB(),
            nullable=True,
            comment="Dynamic approval chain resolved when transfer enters PENDING_APPROVAL",
        ),
    )
    op.add_column(
        "transfer_orders",
        sa.Column(
            "current_approval_step",
            sa.Integer(),
            server_default="1",
            nullable=True,
            comment="1-indexed pointer into resolved_approval_steps; advances as steps complete",
        ),
    )


def downgrade() -> None:
    op.drop_column("transfer_orders", "current_approval_step")
    op.drop_column("transfer_orders", "resolved_approval_steps")
