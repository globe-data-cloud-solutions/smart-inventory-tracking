"""041 — unique idempotency constraint on adjustment_orders + audit:view_logs grants for NM/RM

Adds:
  1. Partial UNIQUE index on adjustment_orders(tenant_id, idempotency_key)
     WHERE idempotency_key IS NOT NULL — prevents double-submit from creating
     two separate adjustment orders for the same logical operation.
  2. role_permissions rows giving NM and RM read access to audit:view_logs.
"""

from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Idempotency unique index on adjustment_orders
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_adjustment_idempotency
        ON adjustment_orders (tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    # 2. Grant NM and RM read access to audit:view_logs so managers can
    #    inspect the audit trail for their own tenant.
    op.execute("""
        INSERT INTO role_permissions (role_code, action_id, grant_type)
        VALUES
            ('NM', 'audit:view_logs', 'FULL'),
            ('RM', 'audit:view_logs', 'FULL')
        ON CONFLICT (role_code, action_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_adjustment_idempotency")
    op.execute("""
        DELETE FROM role_permissions
        WHERE role_code IN ('NM', 'RM') AND action_id = 'audit:view_logs'
    """)
