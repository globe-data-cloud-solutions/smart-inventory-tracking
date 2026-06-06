"""046 — Self-approval policy tables and value-tracking columns (P2 infrastructure).

Creates:
  - self_approval_policies: per-tenant, per-role policy controlling which transfer
    types and quantity/value limits a role can self-approve.
  - adjustment_approval_rules: configurable per-tenant, per-role routing rules for
    adjustment approvals, supporting both global and per-reason-code modes.

Adds columns:
  - adjustment_orders: unit_price_at_submission, total_value, is_self_approved
  - transfer_orders:   is_self_approved

Revision ID: 046
Revises: 045
Create Date: 2026-06-06
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── self_approval_policies ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE self_approval_policies (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            role_code       VARCHAR(10) NOT NULL,
            level_number    INTEGER NOT NULL,
            transfer_types  VARCHAR(20)[] NOT NULL
                                DEFAULT ARRAY['PULL','PUSH','SISTER']::VARCHAR(20)[],
            threshold_type  VARCHAR(10) NOT NULL DEFAULT 'QUANTITY'
                                CHECK (threshold_type IN ('QUANTITY','VALUE','EITHER')),
            qty_limit       DECIMAL(15,4),
            value_limit     DECIMAL(15,2),
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by      UUID REFERENCES users(id),
            UNIQUE (tenant_id, role_code, level_number)
        )
    """)

    op.execute("ALTER TABLE self_approval_policies ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON self_approval_policies
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    """)
    op.execute("""
        CREATE INDEX idx_self_approval_tenant_role
        ON self_approval_policies (tenant_id, role_code, level_number)
        WHERE is_active = TRUE
    """)

    # ── adjustment_approval_rules ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE adjustment_approval_rules (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            role_code           VARCHAR(10) NOT NULL,
            level_number        INTEGER NOT NULL,
            mode                VARCHAR(10) NOT NULL DEFAULT 'GLOBAL'
                                    CHECK (mode IN ('GLOBAL','PER_CODE')),
            reason_code         VARCHAR(50),
            threshold_type      VARCHAR(10) NOT NULL DEFAULT 'QUANTITY'
                                    CHECK (threshold_type IN ('QUANTITY','VALUE','EITHER')),
            qty_limit           DECIMAL(15,4),
            value_limit         DECIMAL(15,2),
            approver_role_code  VARCHAR(10),
            priority            INTEGER NOT NULL DEFAULT 10,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by          UUID REFERENCES users(id)
        )
    """)

    # UNIQUE per tenant+role+level+reason_code — COALESCE maps NULL → '' so that
    # a single catch-all row (reason_code IS NULL) cannot be duplicated per slot.
    op.execute("""
        CREATE UNIQUE INDEX idx_adj_approval_unique
        ON adjustment_approval_rules (tenant_id, role_code, level_number,
                                      COALESCE(reason_code, ''))
    """)

    op.execute("ALTER TABLE adjustment_approval_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON adjustment_approval_rules
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    """)
    op.execute("""
        CREATE INDEX idx_adj_approval_tenant_role
        ON adjustment_approval_rules (tenant_id, role_code, level_number, priority)
        WHERE is_active = TRUE
    """)

    # ── adjustment_orders: value-tracking + self-approval flag ────────────────
    op.execute("""
        ALTER TABLE adjustment_orders
            ADD COLUMN IF NOT EXISTS unit_price_at_submission DECIMAL(15,2),
            ADD COLUMN IF NOT EXISTS total_value              DECIMAL(15,2),
            ADD COLUMN IF NOT EXISTS is_self_approved         BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # ── transfer_orders: self-approval flag ───────────────────────────────────
    # total_value already exists on this table — only add the new flag.
    op.execute("""
        ALTER TABLE transfer_orders
            ADD COLUMN IF NOT EXISTS is_self_approved BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    # Remove columns first (no table drops blocked by FK)
    op.execute("""
        ALTER TABLE transfer_orders
            DROP COLUMN IF EXISTS is_self_approved
    """)
    op.execute("""
        ALTER TABLE adjustment_orders
            DROP COLUMN IF EXISTS is_self_approved,
            DROP COLUMN IF EXISTS total_value,
            DROP COLUMN IF EXISTS unit_price_at_submission
    """)

    # Drop tables (policies and indexes cascade with the table)
    op.execute("DROP TABLE IF EXISTS adjustment_approval_rules")
    op.execute("DROP TABLE IF EXISTS self_approval_policies")
