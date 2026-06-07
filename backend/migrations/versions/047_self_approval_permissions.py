"""047 — Seed self-approval policy permissions for TA (manage+view) and NM (view).

Revision ID: 047
Revises: 046
Create Date: 2026-06-06
"""
from __future__ import annotations
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None

_INSERTS = [
    ("TA", "tenant:self_approval_view",   "FULL"),
    ("TA", "tenant:self_approval_manage", "FULL"),
    ("SA", "tenant:self_approval_view",   "FULL"),
    ("SA", "tenant:self_approval_manage", "FULL"),
    ("NM", "tenant:self_approval_view",   "FULL"),
]


def upgrade() -> None:
    for role_code, action_id, grant_type in _INSERTS:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type)
            VALUES ('{role_code}', '{action_id}', '{grant_type}')
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for role_code, action_id, _ in _INSERTS:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = '{role_code}' AND action_id = '{action_id}'"
        )
