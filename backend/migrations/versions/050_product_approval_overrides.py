"""extend product_approval_minimums with Design-B per-product approval overrides

Adds threshold-based, position-routed overrides alongside the existing
min_authority_level authority-floor mechanism (migration 028).  Both
mechanisms coexist:

  - min_authority_level   (028, UNCHANGED) — authority floor used by
                           approval_service.resolve_approval() Step 1 and
                           inventory_service._check_can_approve() to gate
                           WHO may click Approve.
  - threshold_type / qty_threshold / value_threshold / approver_position_id /
    note / is_active (NEW) — Design-B override consulted by
    check_product_override() to decide whether self-approval and normal
    position routing are bypassed entirely in favour of a named approver
    position.

min_authority_level is relaxed to nullable so a row can exist purely as a
Design-B override with no authority-floor value set.

Also adds product_override_applied to transfer_orders and adjustment_orders
so the UI/audit trail can show when a transaction was routed via override.

Revision ID: 050
Revises:     049
Create Date: 2026-06-12

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""

from __future__ import annotations

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── product_approval_minimums: relax + extend ────────────────────────────
    op.execute(
        "ALTER TABLE product_approval_minimums "
        "ALTER COLUMN min_authority_level DROP NOT NULL"
    )
    op.execute("""
        ALTER TABLE product_approval_minimums
            ADD COLUMN IF NOT EXISTS threshold_type     VARCHAR(10) NOT NULL DEFAULT 'ALWAYS',
            ADD COLUMN IF NOT EXISTS qty_threshold       NUMERIC(15,4),
            ADD COLUMN IF NOT EXISTS value_threshold     NUMERIC(15,4),
            ADD COLUMN IF NOT EXISTS approver_position_id UUID REFERENCES positions(id),
            ADD COLUMN IF NOT EXISTS note                TEXT,
            ADD COLUMN IF NOT EXISTS is_active           BOOLEAN NOT NULL DEFAULT TRUE
    """)
    op.execute("""
        ALTER TABLE product_approval_minimums
            ADD CONSTRAINT ck_pam_threshold_type
            CHECK (threshold_type IN ('ALWAYS', 'QUANTITY', 'VALUE'))
    """)

    op.execute("""
        CREATE INDEX idx_pam_active
        ON product_approval_minimums (tenant_id, product_id)
        WHERE is_active = TRUE
    """)

    # ── transfer_orders / adjustment_orders: override-applied flag ───────────
    op.execute("""
        ALTER TABLE transfer_orders
            ADD COLUMN IF NOT EXISTS product_override_applied BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE adjustment_orders
            ADD COLUMN IF NOT EXISTS product_override_applied BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE adjustment_orders
            DROP COLUMN IF EXISTS product_override_applied
    """)
    op.execute("""
        ALTER TABLE transfer_orders
            DROP COLUMN IF EXISTS product_override_applied
    """)

    op.execute("DROP INDEX IF EXISTS idx_pam_active")

    op.execute("""
        ALTER TABLE product_approval_minimums
            DROP CONSTRAINT IF EXISTS ck_pam_threshold_type
    """)
    op.execute("""
        ALTER TABLE product_approval_minimums
            DROP COLUMN IF EXISTS is_active,
            DROP COLUMN IF EXISTS note,
            DROP COLUMN IF EXISTS approver_position_id,
            DROP COLUMN IF EXISTS value_threshold,
            DROP COLUMN IF EXISTS qty_threshold,
            DROP COLUMN IF EXISTS threshold_type
    """)

    # Restore NOT NULL — safe only if no NULL rows were inserted since upgrade.
    op.execute(
        "ALTER TABLE product_approval_minimums "
        "ALTER COLUMN min_authority_level SET NOT NULL"
    )
