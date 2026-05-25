"""Add missing role permissions: adjustment:list for TA/NM, inventory:issue for TA/NM.

Revision ID: 008
Revises: 007
Create Date: 2026-05-24
"""
from __future__ import annotations

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

# Rows to insert: (role_code, action_id, grant_type)
_INSERTS = [
    # TA — adjustment:list (was present in seed_permissions but missing from migration)
    ("TA", "adjustment:list",  "FULL"),
    # NM — adjustment:list
    ("NM", "adjustment:list",  "FULL"),
    # TA — inventory:issue (NM/RM/WM already had it; TA was missing)
    ("TA", "inventory:issue",  "FULL"),
    # NM — inventory:issue
    ("NM", "inventory:issue",  "FULL"),
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
            f"""
            DELETE FROM role_permissions
            WHERE role_code = '{role_code}' AND action_id = '{action_id}'
            """
        )
