"""048 — Seed adjustment_approval_rule:view and :manage permissions.

Revision ID: 048
Revises: 047
Create Date: 2026-06-07
"""

from __future__ import annotations
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None

_INSERTS = [
    ("TA", "adjustment_approval_rule:view", "FULL"),
    ("TA", "adjustment_approval_rule:manage", "FULL"),
    ("SA", "adjustment_approval_rule:view", "FULL"),
    ("SA", "adjustment_approval_rule:manage", "FULL"),
    ("NM", "adjustment_approval_rule:view", "FULL"),
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
