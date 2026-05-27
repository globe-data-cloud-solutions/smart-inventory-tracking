"""add address to organization_node

Revision ID: 020
Revises: 019
Create Date: 2026-05-27

"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_node",
        sa.Column("address", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_node", "address")
