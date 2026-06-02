"""038 — add TRANSIT_OUT, TRANSIT_IN, TRANSIT_CLEAR, TRANSFER_REVERSAL to transaction_type enum

The inventory ledger uses four transaction types that were added to the
application code (ledger_repo.py / inventory_service.py) but never added
to the transaction_type PostgreSQL enum.  Without these values any attempt
to write a ledger entry at the ISSUED, IN_TRANSIT, or RECEIVED transfer
states raises an asyncpg.InvalidTextRepresentationError.

  TRANSIT_OUT      — physical dispatch audit entry (APPROVED→ISSUED);
                     written again at ISSUED→IN_TRANSIT to confirm transit.
                     Balance-neutral: on_hand was already deducted at APPROVED.
  TRANSIT_IN       — destination receives confirmation of inbound stock
                     (ISSUED→IN_TRANSIT).  Balance-neutral.
  TRANSIT_CLEAR    — clears both source and destination in-transit markers
                     when the transfer reaches RECEIVED.  Balance-neutral.
  TRANSFER_REVERSAL — restores source on_hand when an APPROVED or ADVISED
                     transfer is cancelled before being dispatched.

All four are classified as balance-neutral or reversal types in
ledger_repo._BALANCE_NEUTRAL_TYPES / _TRANSFER_LEDGER_TYPES.

Note: ALTER TYPE ... ADD VALUE cannot be rolled back in PostgreSQL —
downgrade() is intentionally a no-op.  To remove these values a full
enum re-creation would be required.

Revision ID: 038
Revises:     037
Create Date: 2026-06-02
"""
from __future__ import annotations

from alembic import op

revision      = "038"
down_revision = "037"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # IF NOT EXISTS prevents failure when the value was already added manually
    # (e.g., during local dev via psql ALTER TYPE).
    op.execute("ALTER TYPE transaction_type ADD VALUE IF NOT EXISTS 'TRANSIT_OUT'")
    op.execute("ALTER TYPE transaction_type ADD VALUE IF NOT EXISTS 'TRANSIT_IN'")
    op.execute("ALTER TYPE transaction_type ADD VALUE IF NOT EXISTS 'TRANSIT_CLEAR'")
    op.execute("ALTER TYPE transaction_type ADD VALUE IF NOT EXISTS 'TRANSFER_REVERSAL'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without recreating the
    # type.  Any attempt to do so would require a table rewrite and is not safe
    # to automate.  Accept the orphaned values — they are unused until upgrade()
    # runs again.
    pass
