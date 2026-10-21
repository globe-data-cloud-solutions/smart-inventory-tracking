"""039 — partial unique index on positions (node_id, title) WHERE is_active

The full unique constraint uq_positions_node_title blocks recreation of a
soft-deleted position with the same title at the same node, because the
deleted row (is_active=false) still occupies the constraint slot.

Replace with a partial unique index that only covers active rows, so:
  - Two active positions with the same title at the same node → blocked ✓
  - Recreating a deleted position name → allowed ✓

Revision ID: 039
Revises:     038
Create Date: 2026-06-02
"""

from __future__ import annotations

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_positions_node_title", "positions")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_positions_node_title_active
        ON positions (node_id, title)
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_positions_node_title_active")
    op.create_unique_constraint(
        "uq_positions_node_title", "positions", ["node_id", "title"]
    )
