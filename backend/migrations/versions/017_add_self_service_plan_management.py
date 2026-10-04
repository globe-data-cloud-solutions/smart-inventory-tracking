"""Add self-service plan management columns and plan_changes audit table.

Option C: Hybrid self-service signup + plan management
- Tenants can sign up via public endpoint
- TA can self-service upgrade/renew contracts
- SA gates downgrades and other administrative actions

New columns on tenants:
  - payment_method_id: for storing Stripe/PayPal customer ID (optional MVP)
  - invoice_email: separate billing contact email
  - billing_address: JSONB with address components
  - auto_renew: whether to auto-extend contract on expiry

New table:
  - plan_changes: full audit trail of all plan modifications

Revision ID: 017
Revises: 016
Create Date: 2026-10-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns to tenants table for self-service plan management
    op.add_column(
        "tenants",
        sa.Column(
            "payment_method_id",
            sa.String(255),
            nullable=True,
            comment="Stripe/PayPal customer ID for recurring payments (optional MVP)",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "invoice_email",
            sa.String(255),
            nullable=True,
            comment="Separate billing contact email for invoices",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "billing_address",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment="Billing address: {address_line1, address_line2, city, state_province, postal_code, country}",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "auto_renew",
            sa.Boolean,
            nullable=False,
            server_default="true",
            comment="Auto-extend contract on expiry if payment method on file",
        ),
    )

    # Create plan_changes audit table — tracks all plan modifications
    op.create_table(
        "plan_changes",
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
        sa.Column("old_tier", sa.String(20), nullable=True, comment="Previous plan tier"),
        sa.Column("new_tier", sa.String(20), nullable=False, comment="New plan tier"),
        sa.Column("old_max_warehouses", sa.Integer, nullable=True),
        sa.Column("new_max_warehouses", sa.Integer, nullable=False),
        sa.Column("old_max_users", sa.Integer, nullable=True),
        sa.Column("new_max_users", sa.Integer, nullable=False),
        sa.Column("old_sku_cap", sa.Integer, nullable=True),
        sa.Column("new_sku_cap", sa.Integer, nullable=False),
        sa.Column(
            "initiated_by",
            sa.String(50),
            nullable=False,
            comment="'TA' (tenant admin) | 'SA' (system admin) | 'SYSTEM' (auto-renewal)",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
            comment="'PENDING' | 'APPROVED' | 'APPLIED' | 'FAILED' | 'CANCELLED'",
        ),
        sa.Column("approval_reason", sa.Text, nullable=True, comment="Reason for rejection/approval"),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="SA user who approved (if status=APPROVED)",
        ),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Indexes for plan_changes
    op.create_index("idx_plan_changes_tenant", "plan_changes", ["tenant_id"])
    op.create_index(
        "idx_plan_changes_status",
        "plan_changes",
        ["tenant_id", "status"],
    )
    op.create_index(
        "idx_plan_changes_created",
        "plan_changes",
        ["tenant_id", "created_at"],
    )

    # RLS for plan_changes
    op.execute("ALTER TABLE plan_changes ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON plan_changes "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # plan_changes is append-only — no updates or deletes
    op.execute(
        "CREATE RULE no_update_plan_changes AS ON UPDATE TO plan_changes DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE no_delete_plan_changes AS ON DELETE TO plan_changes DO INSTEAD NOTHING"
    )


def downgrade() -> None:
    # Drop plan_changes rules
    op.execute("DROP RULE IF EXISTS no_delete_plan_changes ON plan_changes")
    op.execute("DROP RULE IF EXISTS no_update_plan_changes ON plan_changes")

    # Drop RLS policy
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON plan_changes")

    # Drop plan_changes indexes and table
    op.drop_index("idx_plan_changes_created", table_name="plan_changes")
    op.drop_index("idx_plan_changes_status", table_name="plan_changes")
    op.drop_index("idx_plan_changes_tenant", table_name="plan_changes")
    op.drop_table("plan_changes")

    # Drop columns from tenants
    op.drop_column("tenants", "auto_renew")
    op.drop_column("tenants", "billing_address")
    op.drop_column("tenants", "invoice_email")
    op.drop_column("tenants", "payment_method_id")
