"""add approval_rule table

Phase 0 required table — configurable per-tenant approval routing.
Specifies which role must approve each transaction type based on quantity bands.

NEVER skip this migration on a tenant with existing transfer data — the
approval workflow depends on this table being present before any transfers
are submitted.

Revision ID: 006
Revises: 005
Create Date: 2026-05-17

Round-trip tested: alembic upgrade head → downgrade -1 → upgrade head
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_rule",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        # VARCHAR — avoids re-declaring the transaction_type ENUM in a later
        # migration.  Validated at the application layer and by the CHECK below.
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "transaction_type IN ('PULL','PUSH','SISTER','ADJUSTMENT')",
            name="ck_approval_rule_tx_type",
        ),
        # NULL min_quantity means "applies from 0"
        sa.Column("min_quantity", sa.Numeric(15, 4), nullable=True),
        # NULL max_quantity means "no upper bound"
        sa.Column("max_quantity", sa.Numeric(15, 4), nullable=True),
        # role_code enum already exists from migration 001.  Use String(10)
        # (same pattern as role_permissions.role_code) to avoid re-creating
        # an already-existing ENUM type in a later migration.
        sa.Column(
            "approver_role",
            sa.String(10),
            nullable=False,
        ),
        # approval_order supports multi-step approval chains on the same band
        sa.Column(
            "approval_order",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "idx_approval_rule_tenant",
        "approval_rule",
        ["tenant_id", "transaction_type"],
    )

    # Row-Level Security — same pattern as every other tenant-scoped table
    op.execute("ALTER TABLE approval_rule ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON approval_rule "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON approval_rule")
    op.execute("ALTER TABLE approval_rule DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_approval_rule_tenant", table_name="approval_rule")
    op.drop_table("approval_rule")
