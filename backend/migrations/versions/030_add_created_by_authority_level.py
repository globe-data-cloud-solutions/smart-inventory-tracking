"""add created_by_authority_level to transfer_orders

Stores the authority level of the user who created each transfer at the time
of creation. Used by the approval service escalation logic: if the required
approver has the same or lower authority than the requester, the requirement
is escalated one level up so requesters cannot approve their own transfers.

Revision ID: 030
Revises:     029
Create Date: 2026-05-30

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transfer_orders",
        sa.Column(
            "created_by_authority_level",
            sa.Integer(),
            nullable=True,
            server_default="4",
            comment="ROLE_AUTHORITY_LEVEL of the creating user (lower = higher authority). "
            "NULL on pre-migration rows; treated as 4 (WM) for backward compat.",
        ),
    )


def downgrade() -> None:
    op.drop_column("transfer_orders", "created_by_authority_level")
