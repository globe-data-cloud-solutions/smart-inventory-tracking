"""074 — subscriptions.scheduled_tier for renewal-time downgrades.

Downgrade requests do not apply immediately (CLAUDE.md §15 S13): the tenant
keeps its current tier's entitlements for the rest of the paid period, and
the lower tier is applied when that renewal's PERIOD invoice is marked paid.
scheduled_tier / scheduled_at / scheduled_by hold the pending downgrade on
the subscription row until that happens (or the schedule is cancelled).

Revision ID: 074
Revises:     073
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE subscriptions
          ADD COLUMN scheduled_tier VARCHAR(20) NULL REFERENCES platform_tier_config(tier),
          ADD COLUMN scheduled_at   TIMESTAMPTZ NULL,
          ADD COLUMN scheduled_by   UUID NULL,
          ADD CONSTRAINT ck_sub_scheduled_tier_differs CHECK (scheduled_tier IS NULL OR scheduled_tier <> tier),
          ADD CONSTRAINT ck_sub_scheduled_fields_together CHECK ((scheduled_tier IS NULL) = (scheduled_at IS NULL))
        """
    )
    op.execute(
        "COMMENT ON COLUMN subscriptions.scheduled_tier IS "
        "'Downgrade scheduled for next renewal; applied when that renewal PERIOD invoice is marked paid (§15 S13)'"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE subscriptions
          DROP CONSTRAINT IF EXISTS ck_sub_scheduled_tier_differs,
          DROP CONSTRAINT IF EXISTS ck_sub_scheduled_fields_together,
          DROP COLUMN IF EXISTS scheduled_tier,
          DROP COLUMN IF EXISTS scheduled_at,
          DROP COLUMN IF EXISTS scheduled_by
        """
    )
