"""064 — Add plan_tier ENUM, max_warehouses, max_users to tenants table.

Revision ID: 064
Revises:     063
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE plan_tier AS ENUM ('STARTER', 'GROWTH', 'ENTERPRISE')")
    op.execute(
        "ALTER TABLE tenants ADD COLUMN plan_tier plan_tier NOT NULL DEFAULT 'ENTERPRISE'"
    )
    op.execute("ALTER TABLE tenants ADD COLUMN max_warehouses INTEGER")
    op.execute("ALTER TABLE tenants ADD COLUMN max_users INTEGER")
    op.execute(
        "UPDATE tenants SET plan_tier = 'ENTERPRISE', max_warehouses = NULL, max_users = NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN max_users")
    op.execute("ALTER TABLE tenants DROP COLUMN max_warehouses")
    op.execute("ALTER TABLE tenants DROP COLUMN plan_tier")
    op.execute("DROP TYPE plan_tier")
