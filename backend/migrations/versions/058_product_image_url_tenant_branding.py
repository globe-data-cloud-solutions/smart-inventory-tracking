"""058 — Add image_url to products; logo_url + banner_url to tenants.

Also registers upload permissions for product images and tenant branding.

Revision ID: 058
Revises: 057
Create Date: 2026-06-16
"""
from __future__ import annotations

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url TEXT NULL")
    op.execute("ALTER TABLE tenants  ADD COLUMN IF NOT EXISTS logo_url   TEXT NULL")
    op.execute("ALTER TABLE tenants  ADD COLUMN IF NOT EXISTS banner_url TEXT NULL")

    for action_id, roles in [
        ("product:upload_image",   ["TA", "NM"]),
        ("tenant:upload_branding", ["TA"]),
    ]:
        for role in roles:
            op.execute(
                f"""
                INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
                VALUES ('{role}', '{action_id}', 'FULL', true)
                ON CONFLICT (role_code, action_id) DO NOTHING
                """
            )


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS image_url")
    op.execute("ALTER TABLE tenants  DROP COLUMN IF EXISTS logo_url")
    op.execute("ALTER TABLE tenants  DROP COLUMN IF EXISTS banner_url")

    for action_id in ("product:upload_image", "tenant:upload_branding"):
        op.execute(f"DELETE FROM role_permissions WHERE action_id = '{action_id}'")
