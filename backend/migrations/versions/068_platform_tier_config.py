"""068 — Platform tier configuration table.

Stores SA-editable default warehouse and user limits per plan tier.
Seeded with the original hardcoded defaults. When a SA changes a tier's
defaults the new values apply to all subsequent tenant creations and
plan changes — existing tenant caps (stored on the tenant row) are not
retroactively changed.

Revision ID: 068
Revises:     067
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_tier_config (
            tier           VARCHAR(20) PRIMARY KEY,
            max_warehouses INTEGER,      -- NULL = unlimited
            max_users      INTEGER,      -- NULL = unlimited
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_id  UUID          -- actor who last changed it
        )
        """
    )
    # Seed with the original hardcoded defaults so the system is immediately consistent.
    op.execute(
        "INSERT INTO platform_tier_config (tier, max_warehouses, max_users) VALUES "
        "('STARTER', 3, 5), ('GROWTH', 10, 25), ('ENTERPRISE', NULL, NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_tier_config")
