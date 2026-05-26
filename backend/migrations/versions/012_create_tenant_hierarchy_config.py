"""Create tenant_hierarchy_config table — configurable org hierarchy levels per tenant.

Revision ID: 012
Revises: 011
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_hierarchy_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("level_number", sa.Integer, nullable=False),
        sa.Column("level_name", sa.String(100), nullable=False, server_default="Level"),
        # VARCHAR — role codes are a PostgreSQL ENUM, not a standalone table
        sa.Column("default_role_code", sa.String(20), nullable=True),
        sa.Column("role_display_label", sa.String(100), nullable=True),
        sa.Column("is_stock_holding", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("level_number BETWEEN 1 AND 5", name="chk_level_number_range"),
        sa.UniqueConstraint("tenant_id", "level_number", name="uq_tenant_level"),
    )
    op.create_index("idx_hier_config_tenant", "tenant_hierarchy_config",
                    ["tenant_id", "level_number"])
    op.execute("ALTER TABLE tenant_hierarchy_config ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_hierarchy_config "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_hierarchy_config")
    op.drop_index("idx_hier_config_tenant", table_name="tenant_hierarchy_config")
    op.drop_table("tenant_hierarchy_config")
