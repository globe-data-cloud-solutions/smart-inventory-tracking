"""033 — transfer_approval_rules

Fine-grained approval routing rules per transfer type, supporting
quantity/value thresholds, source/destination level filters, and
multi-step approval chains stored as JSONB.

Revision ID: 033
Revises:     032
Create Date: 2026-05-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_approval_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transfer_type_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_level", sa.Integer(), nullable=True),
        sa.Column("destination_level", sa.Integer(), nullable=True),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("destination_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity_min", sa.Numeric(15, 4),
                  server_default="0", nullable=False),
        sa.Column("quantity_max", sa.Numeric(15, 4), nullable=True),
        sa.Column("value_min", sa.Numeric(15, 4),
                  server_default="0", nullable=False),
        sa.Column("value_max", sa.Numeric(15, 4), nullable=True),
        sa.Column("threshold_type", sa.String(20),
                  server_default="QUANTITY", nullable=False),
        sa.Column("currency", sa.String(3), server_default="ETB", nullable=True),
        sa.Column("approval_steps", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["transfer_type_config_id"], ["transfer_type_config.id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["organization_node.id"]),
        sa.ForeignKeyConstraint(["destination_node_id"], ["organization_node.id"]),
        sa.CheckConstraint(
            "threshold_type IN ('QUANTITY','VALUE','EITHER','BOTH')",
            name="transfer_approval_rules_threshold_check",
        ),
    )
    op.create_index(
        "idx_transfer_approval_rules_type",
        "transfer_approval_rules",
        ["transfer_type_config_id", "source_level", "destination_level"],
    )
    op.execute("ALTER TABLE transfer_approval_rules ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON transfer_approval_rules "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("transfer_approval_rules")
