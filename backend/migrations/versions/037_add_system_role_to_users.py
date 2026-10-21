"""037 — add system_role to users for tenant-admin accounts

TA (Tenant Admin) users are system-level accounts that manage a tenant but
do not hold a position in the org hierarchy.  This column lets the auth
service issue JWT role=TA claims for users who have no primary position.

Only 'TA' is allowed; SA accounts use tenant_id IS NULL instead.

Revision ID: 037
Revises:     036
Create Date: 2026-05-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "system_role",
            sa.String(10),
            nullable=True,
            comment="Set to 'TA' for tenant-admin accounts that have no position in the "
            "org hierarchy. NULL for all other users (role comes from positions).",
        ),
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT chk_system_role "
        "CHECK (system_role IS NULL OR system_role = 'TA')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS chk_system_role")
    op.drop_column("users", "system_role")
