"""080 — Platform contact details (public read, SA edit, audited).

Adds a single-row platform_contact table: support_email/phone/whatsapp,
bilingual address/hours/note, updated_at/updated_by. Platform-level — like
the 070 package catalog tables (platform_tier_config, package_prices,
platform_config_log), this is NOT tenant-scoped: no tenant_id column, no
RLS policy. It is global configuration the SA maintains once, not
per-tenant data.

Revision ID: 080
Revises:     079
Create Date: 2026-10-11
"""

from __future__ import annotations

from alembic import op

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_contact (
            id             SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            support_email  VARCHAR(255),
            phone          VARCHAR(30),
            whatsapp       VARCHAR(30),
            address_en     TEXT,
            address_am     TEXT,
            hours_en       VARCHAR(200),
            hours_am       VARCHAR(200),
            note_en        VARCHAR(300),
            note_am        VARCHAR(300),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by     UUID
        )
        """
    )
    op.execute("INSERT INTO platform_contact (id) VALUES (1)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_contact")
