"""Add transfer_type column to transfer_orders; add product:list/view to WM and RM.

Revision ID: 009
Revises: 008
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add transfer_type column to transfer_orders (default PULL for existing rows)
    op.add_column(
        "transfer_orders",
        sa.Column(
            "transfer_type", sa.String(20), nullable=False, server_default="PULL"
        ),
    )

    # 2. WM: add product:list and product:view (WM receives, issues, transfers products
    #    but had no permission to see the product catalogue — clearly an oversight)
    for action_id in ("product:list", "product:view"):
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type)
            VALUES ('WM', '{action_id}', 'FULL')
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )

    # 3. RM: add product:list and product:view (same reasoning — RM manages inventory)
    for action_id in ("product:list", "product:view"):
        op.execute(
            f"""
            INSERT INTO role_permissions (role_code, action_id, grant_type)
            VALUES ('RM', '{action_id}', 'FULL')
            ON CONFLICT (role_code, action_id) DO NOTHING
            """
        )


def downgrade() -> None:
    op.drop_column("transfer_orders", "transfer_type")

    for role_code in ("WM", "RM"):
        for action_id in ("product:list", "product:view"):
            op.execute(
                f"""
                DELETE FROM role_permissions
                WHERE role_code = '{role_code}' AND action_id = '{action_id}'
                """
            )
