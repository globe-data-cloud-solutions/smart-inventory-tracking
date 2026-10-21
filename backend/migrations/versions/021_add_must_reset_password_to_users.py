"""add must_reset_password to users

Revision ID: 021
Revises: 020
Create Date: 2026-05-27

"""

from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_reset_password", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_reset_password")
