"""051 — Grant NM adjustment:submit permission.

NM (HQ Director / National Manager) was missing adjustment:submit in
role_permissions, while RM and WM already had it (and seed_permissions.py's
NM block had every other adjustment:* action except submit). This caused
every NM-initiated adjustment submission to fail with 403 RBAC_DENIED
before any ABAC / product-override routing logic ran.

Revision ID: 051
Revises: 050
Create Date: 2026-06-14
"""
from __future__ import annotations
from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
        VALUES ('NM', 'adjustment:submit', 'FULL', true)
        ON CONFLICT (role_code, action_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE role_code = 'NM' AND action_id = 'adjustment:submit'"
    )
