"""Seed product:discontinue and product:reactivate permissions for TA and SA roles.

Revision ID: 045
Revises: 044
Create Date: 2026-06-06
"""

from __future__ import annotations
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None

_INSERTS = [
    ("TA", "product:discontinue", "FULL"),
    ("TA", "product:reactivate", "FULL"),
    ("SA", "product:discontinue", "FULL"),
    ("SA", "product:reactivate", "FULL"),
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
