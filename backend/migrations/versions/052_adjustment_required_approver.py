"""052 — Required-approver columns on adjustment_orders (MATRIX 1).

When a Design-B product override routes an ADJUSTMENT to a specific
approver position (check_product_override / _apply_product_override_flag),
the resolved approver was never persisted, so approve_adjustment() only
checked RBAC (adjustment:approve) — any RM/NM could approve an
override-routed adjustment regardless of who the override designated.

Adds the resolved-approver snapshot fields so transition_adjustment()
(PENDING_APPROVAL step) can record WHO must approve, and the APPROVED
transition + GET /adjustments/{id}/approval-info can enforce/report it.

Revision ID: 052
Revises:     051
Create Date: 2026-06-14

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE adjustment_orders
            ADD COLUMN IF NOT EXISTS required_approver_position_id UUID REFERENCES positions(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS required_approver_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS required_approver_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS approver_escalated BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE adjustment_orders
            DROP COLUMN IF EXISTS approver_escalated,
            DROP COLUMN IF EXISTS required_approver_name,
            DROP COLUMN IF EXISTS required_approver_user_id,
            DROP COLUMN IF EXISTS required_approver_position_id
    """)
