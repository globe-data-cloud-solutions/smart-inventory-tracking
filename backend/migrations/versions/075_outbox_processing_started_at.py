"""075 — outbox.processing_started_at for stuck-row recovery.

Set when a worker moves the row to PROCESSING; stuck-row reset uses this,
not created_at.

Revision ID: 075
Revises:     074
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE outbox ADD COLUMN processing_started_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "COMMENT ON COLUMN outbox.processing_started_at IS "
        "'Set when a worker moves the row to PROCESSING; stuck-row reset uses this, not created_at'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE outbox DROP COLUMN processing_started_at")
