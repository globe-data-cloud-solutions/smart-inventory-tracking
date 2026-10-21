"""Add missing role permissions for adjustment cancel/reject actions.

WM can cancel their own DRAFT adjustments.
NM/RM/TA can reject PENDING_APPROVAL adjustments and cancel their own DRAFTs.

Revision ID: 043
Revises: 042
Create Date: 2026-06-06
"""

from __future__ import annotations

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None

# (role_code, action_id, grant_type)
_INSERTS = [
    ("WM", "adjustment:cancel", "FULL"),
    ("NM", "adjustment:cancel", "FULL"),
    ("NM", "adjustment:reject", "FULL"),
    ("RM", "adjustment:cancel", "FULL"),
    ("RM", "adjustment:reject", "FULL"),
    ("TA", "adjustment:cancel", "FULL"),
    ("TA", "adjustment:reject", "FULL"),
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
