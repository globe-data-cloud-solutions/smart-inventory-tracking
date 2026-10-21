"""056 — Grant transfer_type:view to TA/NM/RM/WM/LM for the Approval Policies page.

GET /{tenant_id}/transfer-types is required by Section 1 ("Your Approval
Limits") of the new Approval Policies reference page to show the tenant's
custom transfer-type display names (e.g. "Request Stock" instead of "PULL")
to every role. Previously transfer_type:view was granted only to SA (via the
catch-all ALL_PERMISSIONS grant) — TA and the NM/RM/WM/LM roles that
initiate transfers had no read access to this configuration. This is a
read-only grant; transfer_type:manage (configuration) remains
unchanged (SA-only) and is out of scope here.

Revision ID: 056
Revises: 055
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

_ROLES = ["TA", "NM", "RM", "WM", "LM"]


def upgrade() -> None:
    for role_code in _ROLES:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('{role_code}', 'transfer_type:view', 'FULL', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for role_code in _ROLES:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = '{role_code}' AND action_id = 'transfer_type:view'"
        )
