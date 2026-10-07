"""072 — Add-on catalog, append-only add-on prices, tenant add-ons.

Per-tenant feature overrides become add-ons (free OVERRIDE or priced
PURCHASED) that survive plan changes and appear on invoices (CLAUDE.md §15
S10). Three new tables:

  platform_addons  — platform-level catalog (no tenant_id, no RLS), one row
                      per feature flag that is NOT true in every package tier
                      (i.e. could plausibly be sold/granted as an add-on).
  addon_prices      — append-only (same shape/rules as package_prices):
                      SA sets a MONTHLY/ANNUAL price per add-on; no seed rows.
  tenant_addons      — tenant-scoped, RLS. One row per grant: OVERRIDE (free,
                      amount=0, SA-granted) or PURCHASED (priced, billed on
                      invoices). status ACTIVE/CANCELLED — never deleted.

Backfill (2026-10-07 recon): the recon query that looks for per-tenant
feature_flags overrides against their package found ZERO genuine true/false
overrides anywhere in the dataset (active or probe tenants) — every apparent
mismatch was a MISSING key in a tenant's feature_flags JSONB, not an explicit
override. The backfill INSERT below is kept as the general-purpose rule
(ON-override -> free tenant_addons row, present-and-differing key reset to
the package value) rather than hardcoding "nothing to backfill" — it is
expected, and confirmed, to affect 0 rows against current data.

Normalisation (separate from the override backfill above): 4 active tenants
(t01, t08, tenant-07, tenant-6-p2t) have incomplete feature_flags JSONB —
keys entirely missing, not false. Every tenant with plan_tier IS NOT NULL has
any MISSING key filled with that tenant's package value; a key that is
already PRESENT (whatever its value) is never touched. No tenant currently
has plan_tier IS NULL (checked at migration-authoring time); if one exists at
upgrade time it is left untouched by this step.

A dedicated backup table (migration_072_flags_backup) snapshots every touched
tenant's feature_flags BEFORE any write in this migration, so downgrade()
restores the exact prior JSON regardless of which of the steps above actually
changed it.

payment_line_items (071) gets a new nullable addon_price_id column, FK'd to
addon_prices, alongside its existing price_id (FK'd to package_prices,
untouched). A CHECK constraint ties each column to the row's own item_type
so a PACKAGE line always has price_id set and addon_price_id NULL, and an
ADDON line the reverse — the DB enforces referential integrity against
whichever price table actually applies, instead of relaxing price_id to
point at either table ambiguously.

Revision ID: 072
Revises:     071
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def _refuse_if_addon_lines_exist() -> None:
    """payment_line_items is append-only — downgrade cannot delete ADDON rows
    (071's no_update_/no_delete_payment_line_items RULEs silently no-op any
    attempt) and must not strip addon_price_id out from under them either,
    since that is their only price reference. Raises instead of silently
    producing orphaned/under-constrained rows."""
    bind = op.get_bind()
    count = bind.execute(
        text("SELECT count(*) FROM payment_line_items WHERE item_type = 'ADDON'")
    ).scalar()
    if count:
        raise RuntimeError(
            f"072 downgrade blocked: {count} ADDON invoice lines exist; "
            "payment_line_items is append-only"
        )


def upgrade() -> None:
    # ── A) platform_addons — platform-level catalog, no tenant_id, no RLS ────
    op.execute(
        """
        CREATE TABLE platform_addons (
            code          VARCHAR(50) PRIMARY KEY,
            display_name  VARCHAR(60) NOT NULL,
            description   TEXT,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            is_public     BOOLEAN NOT NULL DEFAULT false,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_id UUID
        )
        """
    )
    # code must be one of shared.plans.catalog.KNOWN_FEATURE_FLAGS — validated
    # in the API layer (PATCH /platform/addons/{code}), not a DB constraint,
    # since KNOWN_FEATURE_FLAGS is the single source of valid flag codes.
    # Seeded: every flag that is NOT `true` in every package tier (STARTER,
    # GROWTH, ENTERPRISE) as of this migration — CORE_INVENTORY,
    # LOT_TRACEABILITY and TRANSFERS_PULL_PUSH are true in all three and so
    # are excluded (nothing to sell as an add-on).
    op.execute(
        """
        INSERT INTO platform_addons (code, display_name, description, is_active, is_public, sort_order) VALUES
          ('LOGISTICS',        'Logistics & Fleet Management', 'Manage drivers, vehicles, and delivery routes', true, false, 1),
          ('AUDIT_EXPORT',     'Audit Log Export',              'Export audit logs for compliance and record-keeping', true, false, 2),
          ('CUSTOM_BRANDING',  'Custom Branding',                'Add your logo, banner, and custom colors', true, false, 3),
          ('TRANSFERS_SISTER', 'Sister Transfers',               'Lateral transfers between facilities at the same level', true, false, 4),
          ('AI_ANALYTICS',     'AI Forecasting & Analytics',     'Demand forecasting, replenishment recommendations, and insights', true, false, 5),
          ('API_ACCESS',       'API Access',                     'Integrate SMART with your external systems via REST API', true, false, 6)
        """
    )

    # ── B) addon_prices — append-only, same shape/rules as package_prices ────
    op.execute(
        """
        CREATE TABLE addon_prices (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            addon_code      VARCHAR(50) NOT NULL REFERENCES platform_addons(code),
            billing_period  VARCHAR(10) NOT NULL CHECK (billing_period IN ('MONTHLY', 'ANNUAL')),
            currency        CHAR(3) NOT NULL DEFAULT 'ETB',
            amount          NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
            effective_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason          TEXT NOT NULL CHECK (length(trim(reason)) > 0),
            created_by      UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_addon_prices_current "
        "ON addon_prices (addon_code, billing_period, effective_from DESC)"
    )
    op.execute("CREATE RULE no_update_addon_prices AS ON UPDATE TO addon_prices DO INSTEAD NOTHING")
    op.execute("CREATE RULE no_delete_addon_prices AS ON DELETE TO addon_prices DO INSTEAD NOTHING")
    # No seed prices — SA sets them via POST /platform/addons/{code}/prices (S10-3).

    # ── B2) payment_line_items grows a second, distinct FK column for ADDON
    #      lines rather than relaxing price_id's existing FK to package_prices.
    #      price_id (071) is untouched — a PACKAGE line still sets it and only
    #      it. addon_price_id is new, nullable, FK'd to addon_prices — an
    #      ADDON line sets only this one. The CHECK enforces exactly one of
    #      the two is set, matching the row's own item_type, so the DB itself
    #      rejects a line item with the wrong kind of price reference (or both,
    #      or neither) — referential integrity for both price tables at once.
    op.execute(
        "ALTER TABLE payment_line_items ADD COLUMN addon_price_id UUID NULL REFERENCES addon_prices(id)"
    )
    op.execute(
        """
        ALTER TABLE payment_line_items ADD CONSTRAINT chk_line_item_price_ref CHECK (
          (item_type = 'PACKAGE' AND price_id IS NOT NULL AND addon_price_id IS NULL) OR
          (item_type = 'ADDON'   AND addon_price_id IS NOT NULL AND price_id IS NULL)
        )
        """
    )

    # ── C) tenant_addons — tenant-scoped, RLS (no FORCE — app role owns these
    #      rows and FORCE would block SA cross-tenant reads, CLAUDE.md §7) ────
    op.execute(
        """
        CREATE TABLE tenant_addons (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL REFERENCES tenants(id),
            addon_code    VARCHAR(50) NOT NULL REFERENCES platform_addons(code),
            source        VARCHAR(10) NOT NULL CHECK (source IN ('OVERRIDE', 'PURCHASED')),
            status        VARCHAR(10) NOT NULL CHECK (status IN ('ACTIVE', 'CANCELLED')),
            price_id      UUID REFERENCES addon_prices(id),
            amount        NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
            starts_on     DATE NOT NULL DEFAULT CURRENT_DATE,
            ends_on       DATE,
            note          TEXT,
            created_by    UUID,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            cancelled_at  TIMESTAMPTZ,
            cancelled_by  UUID,
            CHECK (source <> 'OVERRIDE' OR amount = 0)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_addons_live ON tenant_addons (tenant_id, addon_code) "
        "WHERE status = 'ACTIVE'"
    )
    op.execute("CREATE INDEX idx_tenant_addons_tenant_status ON tenant_addons (tenant_id, status)")
    op.execute("ALTER TABLE tenant_addons ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_addons "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── D) Backup every touched tenant's feature_flags BEFORE any write ──────
    # Restored verbatim in downgrade() regardless of which step below changed it.
    op.execute(
        """
        CREATE TABLE migration_072_flags_backup (
            tenant_id      UUID PRIMARY KEY REFERENCES tenants(id),
            feature_flags  JSONB NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO migration_072_flags_backup (tenant_id, feature_flags)
        SELECT id, feature_flags FROM tenants WHERE plan_tier IS NOT NULL
        """
    )

    # ── E) Override backfill — ON-overrides (present key, tenant=true,
    #      package=false) become free tenant_addons rows; any PRESENT key that
    #      differs from the package (ON or OFF) is then reset to the package
    #      value, since it is now expressed via tenant_addons, not the raw
    #      flags column. Expected to affect 0 rows against current data —
    #      recon confirmed no present key differs from its package anywhere.
    op.execute(
        """
        INSERT INTO tenant_addons (tenant_id, addon_code, source, status, amount, note)
        SELECT t.id, k, 'OVERRIDE', 'ACTIVE', 0, 'backfilled from feature override 072'
        FROM tenants t
        JOIN platform_tier_config p ON p.tier = t.plan_tier::text
        CROSS JOIN LATERAL jsonb_object_keys(p.feature_flags) k
        WHERE t.plan_tier IS NOT NULL
          AND (t.feature_flags ? k)
          AND (t.feature_flags->>k)::bool IS DISTINCT FROM (p.feature_flags->>k)::bool
          AND (t.feature_flags->>k)::bool = true
        """
    )
    op.execute(
        """
        UPDATE tenants t
        SET feature_flags = t.feature_flags || reset.patch
        FROM (
            SELECT t2.id AS tenant_id,
                   jsonb_object_agg(k, (p.feature_flags->>k)::bool) AS patch
            FROM tenants t2
            JOIN platform_tier_config p ON p.tier = t2.plan_tier::text
            CROSS JOIN LATERAL jsonb_object_keys(p.feature_flags) k
            WHERE t2.plan_tier IS NOT NULL
              AND (t2.feature_flags ? k)
              AND (t2.feature_flags->>k)::bool IS DISTINCT FROM (p.feature_flags->>k)::bool
            GROUP BY t2.id
        ) reset
        WHERE reset.tenant_id = t.id
        """
    )

    # ── F) Normalisation — fill MISSING keys only, from the tenant's package.
    #      A key the tenant already has (any value) is never touched: `||`
    #      keeps the right operand's keys, so t.feature_flags always wins over
    #      p.feature_flags for any key present on both sides.
    op.execute(
        """
        UPDATE tenants t
        SET feature_flags = p.feature_flags || t.feature_flags
        FROM platform_tier_config p
        WHERE p.tier = t.plan_tier::text
          AND t.plan_tier IS NOT NULL
        """
    )


def downgrade() -> None:
    # payment_line_items is append-only (071's no_update_/no_delete_
    # payment_line_items RULEs) — any ADDON-type rows that exist by the time
    # this runs are real billing history and cannot be deleted (the RULEs
    # silently no-op the attempt) or stripped of their only price reference.
    # Refuse outright rather than drop addon_price_id/the CHECK underneath
    # them. A fresh upgrade path never encounters pre-existing ADDON rows —
    # the feature does not exist before this migration — so this only
    # triggers on a downgrade run after the feature has seen real use.
    _refuse_if_addon_lines_exist()

    op.execute("ALTER TABLE payment_line_items DROP CONSTRAINT IF EXISTS chk_line_item_price_ref")
    op.execute("ALTER TABLE payment_line_items DROP COLUMN IF EXISTS addon_price_id")

    op.execute(
        """
        UPDATE tenants t
        SET feature_flags = b.feature_flags
        FROM migration_072_flags_backup b
        WHERE t.id = b.tenant_id
        """
    )
    op.execute("DROP TABLE IF EXISTS migration_072_flags_backup")

    op.execute("ALTER TABLE tenant_addons DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS tenant_addons")

    op.execute("DROP RULE IF EXISTS no_delete_addon_prices ON addon_prices")
    op.execute("DROP RULE IF EXISTS no_update_addon_prices ON addon_prices")
    op.execute("DROP TABLE IF EXISTS addon_prices")

    op.execute("DROP TABLE IF EXISTS platform_addons")
