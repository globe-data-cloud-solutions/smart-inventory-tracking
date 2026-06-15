"""057 — Grant product:list/product:view to LM for the Approval Policies page.

Section 2 ("Controlled Products") of the new Approval Policies reference
page is visible to every role and fetches GET /api/v1/products/ to list
products with is_controlled=true and their approval_overrides. WM/RM/NM/TA/SA
already have product:list; LM (Logistics Manager) did not. This is a
read-only grant — product management remains unchanged.

Revision ID: 057
Revises: 056
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for action_id in ("product:list", "product:view"):
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
            VALUES ('LM', '{action_id}', 'FULL', true)
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    for action_id in ("product:list", "product:view"):
        op.execute(
            f"DELETE FROM role_permissions WHERE role_code = 'LM' AND action_id = '{action_id}'"
        )
