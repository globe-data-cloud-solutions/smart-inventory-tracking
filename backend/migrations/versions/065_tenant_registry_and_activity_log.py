"""065 — Tenant registry columns + tenant_activity_log table.

Adds contact/contract columns to tenants and creates an append-only
tenant_activity_log table for SA audit trail. Also registers two new
platform-only permissions in registry.py (done as a companion code change).

Revision ID: 065
Revises:     064
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Contact / contract columns on tenants
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_name  VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255)"
    )
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50)")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contract_start DATE")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contract_end   DATE")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notes          TEXT")

    # 2. Append-only SA activity log — no RLS; access enforced at the API layer
    op.execute(
        """
        CREATE TABLE tenant_activity_log (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL REFERENCES tenants(id),
            actor_id    UUID NOT NULL,
            actor_email VARCHAR(255),
            action      VARCHAR(50) NOT NULL,
            old_value   TEXT,
            new_value   TEXT,
            note        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_tal_tenant_created "
        "ON tenant_activity_log (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE RULE no_update_tal AS ON UPDATE TO tenant_activity_log DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE no_delete_tal AS ON DELETE TO tenant_activity_log DO INSTEAD NOTHING"
    )


def downgrade() -> None:
    # Drop rules first (they depend on the table), then the table itself.
    # DROP TABLE alone would also cascade-drop the rules, but explicit ordering
    # makes the intent clear and matches the upgrade steps in reverse.
    op.execute("DROP RULE IF EXISTS no_delete_tal ON tenant_activity_log")
    op.execute("DROP RULE IF EXISTS no_update_tal ON tenant_activity_log")
    op.execute("DROP TABLE IF EXISTS tenant_activity_log")

    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS contact_name")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS contact_email")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS contact_phone")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS contract_start")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS contract_end")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS notes")
