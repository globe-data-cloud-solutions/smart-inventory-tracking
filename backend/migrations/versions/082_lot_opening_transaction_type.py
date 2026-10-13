"""082 — add LOT_OPENING to transaction_type enum

Opening-balance capture for a batch-tracked product writes a per-lot
ledger entry (lot_balances) without affecting the product's running
total in inventory_balances, which is seeded separately via RECEIVE/
ADJUSTMENT. LOT_OPENING is lot-only: ledger_repo._LOT_ONLY_TYPES skips
the product-level floor check and _update_running_balance() for it,
while still requiring and crediting a lot.

Note: ALTER TYPE ... ADD VALUE cannot be rolled back in PostgreSQL —
downgrade() is intentionally a no-op, following 038's precedent.

Revision ID: 082
Revises:     081
Create Date: 2026-10-12
"""
from __future__ import annotations

from alembic import op

revision      = "082"
down_revision = "081"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # IF NOT EXISTS prevents failure when the value was already added manually
    # (e.g., during local dev via psql ALTER TYPE).
    op.execute("ALTER TYPE transaction_type ADD VALUE IF NOT EXISTS 'LOT_OPENING'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the
    # type.  Any attempt to do so would require a table rewrite and is not safe
    # to automate.  Accept the orphaned value — it is unused until upgrade()
    # runs again.
    pass
