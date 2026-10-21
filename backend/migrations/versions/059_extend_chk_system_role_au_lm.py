"""059 — extend chk_system_role to allow AU and LM

personnel_v2.py's create_user/update_user now accept system_role values of
TA, AU, or LM (the "Assign Tenant-Wide Role" track in the Add User form —
see VALID_DIRECT_SYSTEM_ROLES). The DB-level CHECK constraint added in
migration 037 only allowed NULL or 'TA', so any attempt to create an AU or
LM tenant-wide account passed application validation but failed at INSERT
with a CHECK constraint violation.

This migration widens chk_system_role to match VALID_DIRECT_SYSTEM_ROLES.

Revision ID: 059
Revises:     058
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT chk_system_role")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT chk_system_role "
        "CHECK (system_role IS NULL OR system_role IN ('TA', 'AU', 'LM'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT chk_system_role")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT chk_system_role "
        "CHECK (system_role IS NULL OR system_role = 'TA')"
    )
