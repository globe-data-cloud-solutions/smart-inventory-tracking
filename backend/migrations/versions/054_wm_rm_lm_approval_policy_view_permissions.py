"""054 — Grant WM/RM/LM read-only view permissions for the Approval Policies page.

tenant:self_approval_view, adjustment_approval_rule:view, and
transfer_approval_rule:view were previously TA/SA/NM-only (and RM for the
transfer rule). The new read-only Approval Policies reference page
("Your Approval Limits") shows every role its own self-approval and
adjustment-approval thresholds — WM/RM/LM need VIEW access to render
Section 1. Manage/edit permissions on these tables remain TA/SA/NM-only
and are unchanged.

Revision ID: 054
Revises: 053
Create Date: 2026-06-15
"""

from __future__ import annotations
from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None

_INSERTS = [
    ("WM", "tenant:self_approval_view"),
    ("WM", "adjustment_approval_rule:view"),
    ("WM", "transfer_approval_rule:view"),
    ("RM", "tenant:self_approval_view"),
    ("RM", "adjustment_approval_rule:view"),
    ("LM", "tenant:self_approval_view"),
    ("LM", "adjustment_approval_rule:view"),
    ("LM", "transfer_approval_rule:view"),
]


def upgrade() -> None:
    for role_code, action_id in _INSERTS:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('{role_code}', '{action_id}', 'FULL', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for role_code, action_id in _INSERTS:
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = '{role_code}' AND action_id = '{action_id}'"
        )
