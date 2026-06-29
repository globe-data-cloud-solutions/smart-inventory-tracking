"""066 — Tenant contacts table + address fields on tenants.

Adds a tenant_contacts table for structured primary + additional contacts
(replaces the single contact_name/email/phone columns for multi-contact
scenarios). Also adds postal address fields to the tenants table.

Revision ID: 066
Revises:     065
Create Date: 2026-06-29
"""
from __future__ import annotations

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Postal address fields on tenants
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS address_line1  VARCHAR(255)")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS address_line2  VARCHAR(255)")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS city           VARCHAR(100)")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS state_province VARCHAR(100)")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS postal_code    VARCHAR(20)")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS country        VARCHAR(100)")

    # 2. Structured contacts table — replaces the single contact_* columns
    #    for tenants that use the new wizard contacts step. Old columns remain
    #    for backward compatibility.
    op.execute(
        """
        CREATE TABLE tenant_contacts (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL REFERENCES tenants(id),
            is_primary     BOOLEAN NOT NULL DEFAULT false,
            full_name      VARCHAR(255) NOT NULL,
            position_title VARCHAR(255),
            email          VARCHAR(255),
            phone          VARCHAR(50),
            mobile         VARCHAR(50),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_tenant_contacts_tenant "
        "ON tenant_contacts (tenant_id, is_primary)"
    )
    # Enforce exactly one primary contact per tenant at the DB level
    op.execute(
        "CREATE UNIQUE INDEX idx_tenant_contacts_one_primary "
        "ON tenant_contacts (tenant_id) WHERE is_primary = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tenant_contacts_one_primary")
    op.execute("DROP INDEX IF EXISTS idx_tenant_contacts_tenant")
    op.execute("DROP TABLE IF EXISTS tenant_contacts")

    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS address_line1")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS address_line2")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS city")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS state_province")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS postal_code")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS country")
