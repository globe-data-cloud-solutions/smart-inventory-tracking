"""069 — Add industry column to tenants table.

The onboarding wizard has always collected an 'industry' field (Step 1)
but never persisted it — the column was missing. This migration adds it
as a nullable VARCHAR so existing rows are unaffected and the field can
now be saved during wizard creation and edited via the SA admin panel.

Revision ID: 069
Revises:     068
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS industry VARCHAR(100)")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS industry")
