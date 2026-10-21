"""070 — Plan catalog, price history, config log, signup foundations.

Extends platform_tier_config from a bare limits table into the package
catalog: display name, sku_cap, explicit feature flags (all 9, since a
missing flag is treated as "allowed" by check_plan()), public visibility,
and sort order. Existing tenant plan_tier/max_*/sku_cap/feature_flags
values on the tenants table are NOT touched by this migration.

Adds two new platform-level (not tenant-scoped, no RLS) tables:
  - package_prices: append-only price history per tier + billing period.
  - platform_config_log: append-only audit of SA changes to the catalog.

Adds signup foundations:
  - users.is_account_owner, backfilled to the oldest active TA per tenant.
  - a global case-insensitive unique index on users.email, guarded by an
    explicit pre-check that raises a readable exception (listing the
    offending emails) instead of a raw index-violation error if a target
    database still has duplicates.
  - tenants.signup_source, defaulted to 'SA' for all existing rows.

Revision ID: 070
Revises:     069
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── A) users ─────────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE users ADD COLUMN is_account_owner BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        """
        UPDATE users u SET is_account_owner = true
        FROM (
            SELECT DISTINCT ON (tenant_id) id
            FROM users
            WHERE system_role = 'TA' AND is_active
            ORDER BY tenant_id, created_at, id
        ) o
        WHERE u.id = o.id
        """
    )
    # Guard: fail with a readable message (not a raw unique-violation) if a
    # target database still has case-insensitive duplicate emails.
    op.execute(
        """
        DO $$
        DECLARE
            dup_list TEXT;
        BEGIN
            SELECT string_agg(format('%s (count=%s)', email, cnt), ', ')
            INTO dup_list
            FROM (
                SELECT lower(email) AS email, count(*) AS cnt
                FROM users
                GROUP BY lower(email)
                HAVING count(*) > 1
            ) d;

            IF dup_list IS NOT NULL THEN
                RAISE EXCEPTION
                    'Migration 070 cannot create uq_users_email_lower: '
                    'duplicate case-insensitive emails exist: %. '
                    'Resolve as a data fix (deactivate/rename the duplicate, '
                    'never hard-delete per CLAUDE.md) before retrying this migration.',
                    dup_list;
            END IF;
        END $$;
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))")

    # ── B) tenants ───────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE tenants ADD COLUMN signup_source VARCHAR(20) NOT NULL DEFAULT 'SA' "
        "CHECK (signup_source IN ('SA', 'SELF_SIGNUP'))"
    )

    # ── C) platform_tier_config → package catalog ───────────────────────
    op.execute("ALTER TABLE platform_tier_config ADD COLUMN display_name VARCHAR(50)")
    op.execute("ALTER TABLE platform_tier_config ADD COLUMN sku_cap INTEGER")
    op.execute(
        "ALTER TABLE platform_tier_config ADD COLUMN feature_flags JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE platform_tier_config ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE platform_tier_config ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
    )
    # Ensure all three rows exist (fresh/AWS databases included) before updating them.
    op.execute(
        "INSERT INTO platform_tier_config (tier, max_warehouses, max_users) VALUES "
        "('STARTER', 3, 5), ('GROWTH', 10, 25), ('ENTERPRISE', NULL, NULL) "
        "ON CONFLICT (tier) DO NOTHING"
    )
    op.execute(
        """
        UPDATE platform_tier_config SET
            display_name = 'Starter',
            sku_cap = 500,
            sort_order = 1,
            feature_flags = '{
                "CORE_INVENTORY": true, "TRANSFERS_PULL_PUSH": true, "LOT_TRACEABILITY": true,
                "TRANSFERS_SISTER": false, "LOGISTICS": false, "AUDIT_EXPORT": false,
                "CUSTOM_BRANDING": false, "AI_ANALYTICS": false, "API_ACCESS": false
            }'::jsonb
        WHERE tier = 'STARTER'
        """
    )
    op.execute(
        """
        UPDATE platform_tier_config SET
            display_name = 'Growth',
            sku_cap = 1500,
            sort_order = 2,
            feature_flags = '{
                "CORE_INVENTORY": true, "TRANSFERS_PULL_PUSH": true, "LOT_TRACEABILITY": true,
                "TRANSFERS_SISTER": true, "LOGISTICS": true, "AUDIT_EXPORT": true,
                "CUSTOM_BRANDING": true, "AI_ANALYTICS": false, "API_ACCESS": false
            }'::jsonb
        WHERE tier = 'GROWTH'
        """
    )
    op.execute(
        """
        UPDATE platform_tier_config SET
            display_name = 'Enterprise',
            sku_cap = NULL,
            sort_order = 3,
            feature_flags = '{
                "CORE_INVENTORY": true, "TRANSFERS_PULL_PUSH": true, "LOT_TRACEABILITY": true,
                "TRANSFERS_SISTER": true, "LOGISTICS": true, "AUDIT_EXPORT": true,
                "CUSTOM_BRANDING": true, "AI_ANALYTICS": true, "API_ACCESS": true
            }'::jsonb
        WHERE tier = 'ENTERPRISE'
        """
    )

    # ── D) package_prices — platform-level, append-only ──────────────────
    op.execute(
        """
        CREATE TABLE package_prices (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tier            VARCHAR(20) NOT NULL REFERENCES platform_tier_config(tier),
            billing_period  VARCHAR(10) NOT NULL CHECK (billing_period IN ('MONTHLY', 'ANNUAL')),
            currency        CHAR(3)     NOT NULL DEFAULT 'ETB',
            amount          NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
            effective_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason          TEXT        NOT NULL CHECK (length(trim(reason)) > 0),
            created_by      UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_package_prices_current "
        "ON package_prices (tier, billing_period, effective_from DESC)"
    )
    op.execute(
        "CREATE RULE no_update_package_prices AS ON UPDATE TO package_prices DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE no_delete_package_prices AS ON DELETE TO package_prices DO INSTEAD NOTHING"
    )
    op.execute(
        """
        INSERT INTO package_prices (tier, billing_period, currency, amount, reason) VALUES
            ('STARTER',    'MONTHLY', 'ETB', 100.00,  'Initial sample pricing — to be revised before launch'),
            ('STARTER',    'ANNUAL',  'ETB', 1000.00, 'Initial sample pricing — to be revised before launch'),
            ('GROWTH',     'MONTHLY', 'ETB', 200.00,  'Initial sample pricing — to be revised before launch'),
            ('GROWTH',     'ANNUAL',  'ETB', 2000.00, 'Initial sample pricing — to be revised before launch'),
            ('ENTERPRISE', 'MONTHLY', 'ETB', 300.00,  'Initial sample pricing — to be revised before launch'),
            ('ENTERPRISE', 'ANNUAL',  'ETB', 3000.00, 'Initial sample pricing — to be revised before launch')
        """
    )

    # ── E) platform_config_log — platform-level, append-only ─────────────
    op.execute(
        """
        CREATE TABLE platform_config_log (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type  VARCHAR(30)  NOT NULL,
            entity_key   VARCHAR(100) NOT NULL,
            field        VARCHAR(50),
            old_value    TEXT,
            new_value    TEXT,
            reason       TEXT,
            actor_id     UUID,
            actor_email  VARCHAR(255),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_platform_config_log_entity "
        "ON platform_config_log (entity_type, entity_key, created_at DESC)"
    )
    op.execute(
        "CREATE RULE no_update_platform_config_log AS ON UPDATE TO platform_config_log DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE no_delete_platform_config_log AS ON DELETE TO platform_config_log DO INSTEAD NOTHING"
    )
    op.execute(
        """
        INSERT INTO platform_config_log (entity_type, entity_key, field, new_value, reason)
        SELECT 'PACKAGE', tier, 'catalog',
               jsonb_build_object(
                   'display_name', display_name,
                   'max_warehouses', max_warehouses,
                   'max_users', max_users,
                   'sku_cap', sku_cap,
                   'feature_flags', feature_flags
               )::text,
               'Migration 070 — initial catalog'
        FROM platform_tier_config
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP RULE IF EXISTS no_delete_platform_config_log ON platform_config_log"
    )
    op.execute(
        "DROP RULE IF EXISTS no_update_platform_config_log ON platform_config_log"
    )
    op.execute("DROP TABLE IF EXISTS platform_config_log")

    op.execute("DROP RULE IF EXISTS no_delete_package_prices ON package_prices")
    op.execute("DROP RULE IF EXISTS no_update_package_prices ON package_prices")
    op.execute("DROP TABLE IF EXISTS package_prices")

    op.execute("ALTER TABLE platform_tier_config DROP COLUMN IF EXISTS sort_order")
    op.execute("ALTER TABLE platform_tier_config DROP COLUMN IF EXISTS is_public")
    op.execute("ALTER TABLE platform_tier_config DROP COLUMN IF EXISTS feature_flags")
    op.execute("ALTER TABLE platform_tier_config DROP COLUMN IF EXISTS sku_cap")
    op.execute("ALTER TABLE platform_tier_config DROP COLUMN IF EXISTS display_name")

    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS signup_source")

    op.execute("DROP INDEX IF EXISTS uq_users_email_lower")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_account_owner")
