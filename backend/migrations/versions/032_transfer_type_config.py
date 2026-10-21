"""032 — transfer_type_config and transfer_type_level_permissions

Tenant-configurable transfer type display names and which hierarchy levels
may initiate vs receive each type.

Revision ID: 032
Revises:     031
Create Date: 2026-05-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── transfer_type_config ──────────────────────────────────────────────────
    op.create_table(
        "transfer_type_config",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("underlying_type", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.CheckConstraint(
            "underlying_type IN ('PULL','PUSH','SISTER')",
            name="transfer_type_config_underlying_check",
        ),
        sa.UniqueConstraint(
            "tenant_id", "underlying_type", name="uq_transfer_type_config_tenant_type"
        ),
    )
    op.execute("ALTER TABLE transfer_type_config ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON transfer_type_config "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── transfer_type_level_permissions ──────────────────────────────────────
    op.create_table(
        "transfer_type_level_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "transfer_type_config_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("level_number", sa.Integer(), nullable=False),
        sa.Column("can_initiate", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("can_receive", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["transfer_type_config_id"], ["transfer_type_config.id"]
        ),
        sa.CheckConstraint(
            "level_number BETWEEN 1 AND 5",
            name="transfer_type_level_permissions_level_check",
        ),
        sa.UniqueConstraint(
            "transfer_type_config_id", "level_number", name="uq_ttlp_type_level"
        ),
    )
    op.execute("ALTER TABLE transfer_type_level_permissions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON transfer_type_level_permissions "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("transfer_type_level_permissions")
    op.drop_table("transfer_type_config")
