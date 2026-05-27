"""Add password_hash column to users table — local dev authentication.

Allows API-created users (not Cognito) to authenticate via bcrypt password
in the dev_email bypass path. Column is nullable so existing rows are
unaffected; Cognito users leave it NULL and continue to use Cognito.

Revision ID: 018
Revises: 017
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
