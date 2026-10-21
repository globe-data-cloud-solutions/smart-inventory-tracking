"""Add source_factory_id to products — factory-specific product scoping (PRD-APPENDIX §B3).

NULL = standard product, pullable from any node with available stock.
SET  = product locked to the home factory's subtree; backend raises INVALID_SOURCE_FACTORY
       (HTTP 422) if source is outside the factory subtree.

Revision ID: 014
Revises: 013
Create Date: 2026-05-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "source_factory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_node.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_products_source_factory",
        "products",
        ["tenant_id", "source_factory_id"],
        postgresql_where=sa.text("source_factory_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_products_source_factory", table_name="products")
    op.drop_column("products", "source_factory_id")
