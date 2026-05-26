"""Create organization_node and org_node_hierarchy tables — IMTS facility hierarchy.

organization_node replaces the flat warehouses table as the canonical facility record.
org_node_hierarchy stores reporting and supply-chain relationships between nodes.
node_relationship ENUM: PRIMARY_REPORTS_TO | SUPPLY_FROM | DISTRIBUTE_TO

Revision ID: 013
Revises: 012
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── organization_node ─────────────────────────────────────────────────
    # Each facility (MWH, RWH, WH, Sub-WH) is a node regardless of level.
    # users.warehouse_id maps to organization_node.id via the JWT claim.
    op.create_table(
        "organization_node",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("hierarchy_level", sa.Integer, nullable=False),
        sa.Column("parent_node_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organization_node.id"), nullable=True),
        sa.Column("is_stock_holding", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_org_node_tenant", "organization_node",
                    ["tenant_id", "hierarchy_level"])
    op.execute("ALTER TABLE organization_node ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON organization_node "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    # ── org_node_hierarchy ────────────────────────────────────────────────
    # Separates reporting relationships from supply network topology.
    # A facility can report to one parent but receive stock from multiple sources.
    op.create_table(
        "org_node_hierarchy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("from_node_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organization_node.id"), nullable=False),
        sa.Column("to_node_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organization_node.id"), nullable=False),
        sa.Column("relationship_type",
                  sa.Enum("PRIMARY_REPORTS_TO", "SUPPLY_FROM", "DISTRIBUTE_TO",
                          name="node_relationship"),
                  nullable=False),
        sa.Column("is_preferred", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_org_hier_from", "org_node_hierarchy",
                    ["tenant_id", "from_node_id", "relationship_type"])
    op.create_index("idx_org_hier_to", "org_node_hierarchy",
                    ["tenant_id", "to_node_id", "relationship_type"])
    op.execute("ALTER TABLE org_node_hierarchy ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON org_node_hierarchy "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON org_node_hierarchy")
    op.drop_index("idx_org_hier_to", table_name="org_node_hierarchy")
    op.drop_index("idx_org_hier_from", table_name="org_node_hierarchy")
    op.drop_table("org_node_hierarchy")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organization_node")
    op.drop_index("idx_org_node_tenant", table_name="organization_node")
    op.drop_table("organization_node")

    op.execute("DROP TYPE IF EXISTS node_relationship")
