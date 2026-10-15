"""089 — tenants.near_expiry_days + TA report:dispatch_summary grant.

near_expiry_days is the number of days before expiry at which a lot shows as
EXPIRING (Lots page, expiry alerts, dashboard card). Set by the TA through
PUT /inventory/lots/expiry-settings. INTEGER NOT NULL DEFAULT 30, CHECK 1..365.

It is a column, not a feature_flags key: shared/plans/catalog.py
apply_package_to_tenant REPLACES feature_flags on every plan change and
validates it against a fixed code set, so a key there would be lost.

Grant (report:dispatch_summary, FULL): TA. ON CONFLICT DO NOTHING; downgrade
deletes exactly this one row.

No new table, so no RLS policy is added here.

Revision ID: 089
Revises:     088
Create Date: 2026-10-14

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenants
            ADD COLUMN near_expiry_days INTEGER NOT NULL DEFAULT 30
                CONSTRAINT ck_tenants_near_expiry_days
                CHECK (near_expiry_days BETWEEN 1 AND 365)
        """
    )
    op.execute(
        "COMMENT ON COLUMN tenants.near_expiry_days IS "
        "'Days before expiry at which a lot shows as EXPIRING (Lots page, expiry "
        "alerts, dashboard card). Set by the TA.'"
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
        VALUES ('TA', 'report:dispatch_summary', 'FULL', true)
        ON CONFLICT (role_code, action_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions "
        "WHERE role_code = 'TA' AND action_id = 'report:dispatch_summary'"
    )
    op.execute("ALTER TABLE tenants DROP CONSTRAINT ck_tenants_near_expiry_days")
    op.execute("ALTER TABLE tenants DROP COLUMN near_expiry_days")
