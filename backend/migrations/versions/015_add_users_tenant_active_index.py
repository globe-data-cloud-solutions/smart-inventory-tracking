"""Add composite index (tenant_id, is_active) to users for faster personnel page queries.

users.is_active already exists in migration 001. This migration adds only the
composite index so filtered queries by tenant + active status use an index scan.

Revision ID: 015
Revises: 014
Create Date: 2026-05-26
"""

from __future__ import annotations

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index may already exist if this migration is replayed on a partially-migrated DB;
    # op.create_index with if_not_exists=True handles that safely.
    op.create_index(
        "idx_users_tenant_active",
        "users",
        ["tenant_id", "is_active"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_users_tenant_active", table_name="users")
