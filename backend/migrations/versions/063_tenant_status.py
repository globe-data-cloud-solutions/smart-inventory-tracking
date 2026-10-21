"""063 — Add tenant_status column to tenants.

Introduces a tenant_status ENUM ('ACTIVE','SUSPENDED','DEACTIVATED') and a
status column on tenants, backfilled from the existing is_active boolean.
is_active is left in place for backward compatibility — not dropped here.

Revision ID: 063
Revises:     062
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE tenant_status AS ENUM ('ACTIVE', 'SUSPENDED', 'DEACTIVATED')"
    )
    op.execute(
        "ALTER TABLE tenants ADD COLUMN status tenant_status NOT NULL DEFAULT 'ACTIVE'"
    )
    op.execute("UPDATE tenants SET status = 'ACTIVE' WHERE is_active = true")
    op.execute("UPDATE tenants SET status = 'DEACTIVATED' WHERE is_active = false")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN status")
    op.execute("DROP TYPE tenant_status")
