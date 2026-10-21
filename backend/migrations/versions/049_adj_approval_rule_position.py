"""049 — Add approver_position_id to adjustment_approval_rules.

Allows adjustment approval routing to target a specific tenant-defined
position (resolved to its current PRIMARY holder at approval time) instead
of only a generic role code. Legacy rules with only approver_role_code
continue to use role-based routing.

Revision ID: 049
Revises: 048
Create Date: 2026-06-09
"""

from __future__ import annotations
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE adjustment_approval_rules
        ADD COLUMN approver_position_id UUID REFERENCES positions(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE adjustment_approval_rules
        DROP COLUMN approver_position_id
    """)
