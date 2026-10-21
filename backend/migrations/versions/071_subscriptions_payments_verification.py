"""071 — Subscriptions, payments + line items, email verification, terms acceptance.

Schema + backfill only. No endpoints are added in this migration.

Adds users.email_verified_at (existing accounts backfilled as verified, so
turning verification enforcement on later never locks anyone out) and
email_verification_tokens (platform-level — looked up by token from a public
endpoint before login, so no tenant_id / no RLS; only auth-service touches it).

Adds the tenant-scoped billing tables: subscriptions (one live subscription
per tenant, price snapshot via price_id), payments (15% default VAT, totals
checked, provider-reference idempotency for webhooks), append-only
payment_line_items (PACKAGE now, ADDON reserved for later), and append-only
terms_acceptances.

Backfills one MANUAL ANNUAL subscription per existing tenant from its current
plan_tier and contract dates — deactivated tenants get a CANCELLED
subscription instead of ACTIVE. No payments are backfilled. Tenant rows
themselves are not modified.

RLS convention for the new tenant-scoped tables: ENABLE ROW LEVEL SECURITY +
the standard tenant_isolation policy — no FORCE, since the app role owns
these tables and FORCE would block SA cross-tenant reads (CLAUDE.md §7).

Revision ID: 071
Revises:     070
Create Date: 2026-10-06
"""

from __future__ import annotations

from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── A) users.email_verified_at ──────────────────────────────────────────
    op.execute("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ NULL")
    op.execute("UPDATE users SET email_verified_at = created_at")

    # ── B) email_verification_tokens — platform-level, no tenant_id / no RLS ─
    op.execute(
        """
        CREATE TABLE email_verification_tokens (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id),
            token_hash  CHAR(64) NOT NULL UNIQUE,
            purpose     VARCHAR(20) NOT NULL DEFAULT 'VERIFY_EMAIL'
                        CHECK (purpose IN ('VERIFY_EMAIL')),
            expires_at  TIMESTAMPTZ NOT NULL,
            used_at     TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_email_verification_tokens_user "
        "ON email_verification_tokens (user_id, created_at DESC)"
    )

    # ── C) subscriptions — tenant-scoped, RLS ────────────────────────────────
    op.execute(
        """
        CREATE TABLE subscriptions (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID NOT NULL REFERENCES tenants(id),
            tier                  VARCHAR(20) NOT NULL REFERENCES platform_tier_config(tier),
            billing_period        VARCHAR(10) NOT NULL CHECK (billing_period IN ('MONTHLY', 'ANNUAL')),
            status                VARCHAR(20) NOT NULL
                                  CHECK (status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE', 'CANCELLED')),
            provider              VARCHAR(20) NOT NULL DEFAULT 'MANUAL' CHECK (provider IN ('MANUAL', 'STUB')),
            price_id              UUID REFERENCES package_prices(id),
            amount                NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
            currency              CHAR(3) NOT NULL DEFAULT 'ETB',
            current_period_start  DATE NOT NULL,
            current_period_end    DATE NOT NULL CHECK (current_period_end > current_period_start),
            cancelled_at          TIMESTAMPTZ,
            created_by            UUID,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_subscriptions_one_live ON subscriptions (tenant_id) "
        "WHERE status IN ('ACTIVE', 'PENDING_PAYMENT', 'PAST_DUE')"
    )
    op.execute(
        "CREATE INDEX idx_subscriptions_tenant_created ON subscriptions (tenant_id, created_at DESC)"
    )
    op.execute("ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON subscriptions "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── D) payments — tenant-scoped, RLS ─────────────────────────────────────
    op.execute(
        """
        CREATE TABLE payments (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL REFERENCES tenants(id),
            subscription_id     UUID NOT NULL REFERENCES subscriptions(id),
            status              VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                                CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'CANCELLED', 'REFUNDED')),
            currency            CHAR(3) NOT NULL DEFAULT 'ETB',
            subtotal            NUMERIC(12,2) NOT NULL CHECK (subtotal >= 0),
            vat_rate            NUMERIC(5,4) NOT NULL DEFAULT 0.15 CHECK (vat_rate >= 0 AND vat_rate < 1),
            vat_amount          NUMERIC(12,2) NOT NULL CHECK (vat_amount >= 0),
            total               NUMERIC(12,2) NOT NULL CHECK (total = subtotal + vat_amount),
            period_start        DATE NOT NULL,
            period_end          DATE NOT NULL CHECK (period_end > period_start),
            provider            VARCHAR(20) NOT NULL DEFAULT 'MANUAL' CHECK (provider IN ('MANUAL', 'STUB')),
            provider_reference  VARCHAR(255),
            paid_at             TIMESTAMPTZ,
            recorded_by         UUID,
            note                TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_payments_tenant_created ON payments (tenant_id, created_at DESC)"
    )
    op.execute("CREATE INDEX idx_payments_subscription ON payments (subscription_id)")
    op.execute(
        "CREATE UNIQUE INDEX uq_payments_provider_reference ON payments (provider, provider_reference) "
        "WHERE provider_reference IS NOT NULL"
    )
    op.execute("ALTER TABLE payments ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON payments "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── E) payment_line_items — tenant-scoped, RLS, append-only ─────────────
    op.execute(
        """
        CREATE TABLE payment_line_items (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL REFERENCES tenants(id),
            payment_id    UUID NOT NULL REFERENCES payments(id),
            item_type     VARCHAR(20) NOT NULL CHECK (item_type IN ('PACKAGE', 'ADDON')),
            item_key      VARCHAR(100) NOT NULL,
            description   TEXT,
            price_id      UUID REFERENCES package_prices(id),
            quantity      INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
            unit_amount   NUMERIC(12,2) NOT NULL CHECK (unit_amount >= 0),
            amount        NUMERIC(12,2) NOT NULL CHECK (amount = unit_amount * quantity),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_payment_line_items_tenant_payment ON payment_line_items (tenant_id, payment_id)"
    )
    op.execute("ALTER TABLE payment_line_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON payment_line_items "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE RULE no_update_payment_line_items AS ON UPDATE TO payment_line_items DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE no_delete_payment_line_items AS ON DELETE TO payment_line_items DO INSTEAD NOTHING"
    )

    # ── F) terms_acceptances — tenant-scoped, RLS, append-only ───────────────
    op.execute(
        """
        CREATE TABLE terms_acceptances (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL REFERENCES tenants(id),
            user_id        UUID NOT NULL REFERENCES users(id),
            terms_version  VARCHAR(20) NOT NULL,
            accepted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            ip_address     INET,
            user_agent     TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_terms_acceptances_tenant_accepted ON terms_acceptances (tenant_id, accepted_at DESC)"
    )
    op.execute("ALTER TABLE terms_acceptances ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON terms_acceptances "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE RULE no_update_terms_acceptances AS ON UPDATE TO terms_acceptances DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE no_delete_terms_acceptances AS ON DELETE TO terms_acceptances DO INSTEAD NOTHING"
    )

    # ── G) Backfill one subscription per existing tenant ─────────────────────
    op.execute(
        """
        INSERT INTO subscriptions (
            tenant_id, tier, billing_period, status, provider, price_id, amount, currency,
            current_period_start, current_period_end, cancelled_at
        )
        SELECT
            t.id,
            t.plan_tier::text,
            'ANNUAL',
            CASE WHEN t.status = 'DEACTIVATED' THEN 'CANCELLED' ELSE 'ACTIVE' END,
            'MANUAL',
            pp.id,
            pp.amount,
            pp.currency,
            d.period_start,
            (CASE
                WHEN d.period_end IS NOT NULL AND d.period_end > d.period_start THEN d.period_end
                ELSE d.period_start + INTERVAL '1 year'
            END)::date,
            CASE WHEN t.status = 'DEACTIVATED' THEN now() ELSE NULL END
        FROM tenants t
        CROSS JOIN LATERAL (
            SELECT
                COALESCE(t.contract_start, t.created_at::date) AS period_start,
                t.contract_end AS period_end
        ) d
        LEFT JOIN LATERAL (
            SELECT pc.id, pc.amount, pc.currency
            FROM package_prices pc
            WHERE pc.tier = t.plan_tier::text
              AND pc.billing_period = 'ANNUAL'
              AND pc.effective_from <= now()
            ORDER BY pc.effective_from DESC
            LIMIT 1
        ) pp ON true
        """
    )


def downgrade() -> None:
    op.execute("DROP RULE IF EXISTS no_delete_terms_acceptances ON terms_acceptances")
    op.execute("DROP RULE IF EXISTS no_update_terms_acceptances ON terms_acceptances")
    op.execute("DROP TABLE IF EXISTS terms_acceptances")

    op.execute("DROP RULE IF EXISTS no_delete_payment_line_items ON payment_line_items")
    op.execute("DROP RULE IF EXISTS no_update_payment_line_items ON payment_line_items")
    op.execute("DROP TABLE IF EXISTS payment_line_items")

    op.execute("DROP TABLE IF EXISTS payments")
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at")
