"""040 — widen status columns from VARCHAR(20) to VARCHAR(30)

PENDING_SOURCE_CONFIRM is 22 characters — exceeds the original VARCHAR(20)
limit on transfer_orders.status, causing all SISTER transfers to fail with
asyncpg StringDataRightTruncation when entering PENDING_SOURCE_CONFIRM.

Tables fixed:
  transfer_orders.status   — needs VARCHAR(30) for PENDING_SOURCE_CONFIRM (22)
  adjustment_orders.status — VARCHAR(20) is sufficient for current values
                              (max: PENDING_APPROVAL = 16) but widened
                              defensively to avoid the same class of bug.

Revision ID: 040
Revises:     039
Create Date: 2026-06-03
"""
from __future__ import annotations

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transfer_orders ALTER COLUMN status TYPE VARCHAR(30)")
    op.execute("ALTER TABLE adjustment_orders ALTER COLUMN status TYPE VARCHAR(30)")


def downgrade() -> None:
    # Only safe if no status values exceed 20 chars at downgrade time.
    # PENDING_SOURCE_CONFIRM (22) must not be present when reverting.
    op.execute("ALTER TABLE transfer_orders ALTER COLUMN status TYPE VARCHAR(20)")
    op.execute("ALTER TABLE adjustment_orders ALTER COLUMN status TYPE VARCHAR(20)")
