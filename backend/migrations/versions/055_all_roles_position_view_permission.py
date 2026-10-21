"""055 — Grant position:view to all tenant-scoped roles for the Approval Policies page.

The new Approval Policies reference page's "Your Approval Limits" section
(Section 1) shows every viewer their own position (display label, level
number, and "next approver" via reports_to_title) by querying
GET /{tenant_id}/positions/flat, which requires position:view.

Previously position:view was granted only to SA (via the catch-all
ALL_PERMISSIONS grant) and TA. WM/RM/LM/NM/SA_GT/RT/AU all need read access
to the tenant's position list to render Section 1, which is shown to every
role. This is a read-only grant — position management (create/update)
remains TA/SA-only and is unchanged.

Revision ID: 055
Revises: 054
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None

_ROLES = ["WM", "RM", "LM", "NM", "SA_GT", "RT", "AU"]


def upgrade() -> None:
    for role_code in _ROLES:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('{role_code}', 'position:view', 'FULL', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for role_code in _ROLES:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = '{role_code}' AND action_id = 'position:view'"
        )
