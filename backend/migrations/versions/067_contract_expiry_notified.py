"""067 — Add contract_expiry_notified to tenants.

Tracks which pre-expiry alert milestones have already been dispatched for each
tenant so the daily Celery beat task never double-fires the same alert.
Stored as a JSONB array of strings, e.g. ["90d", "30d", "14d"].

Revision ID: 067
Revises:     066
Create Date: 2026-06-29
"""
from __future__ import annotations

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants "
        "ADD COLUMN IF NOT EXISTS contract_expiry_notified JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS contract_expiry_notified")
