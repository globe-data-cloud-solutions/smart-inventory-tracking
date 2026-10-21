"""077 — Drop migration_072_flags_backup.

migration_072_flags_backup was a one-off backup table from migration 072.
Its 23 rows were exported to docs/archive/migration_072_flags_backup.json
before this migration ran — downgrade recreates the empty table shape
only; row data lives in that JSON file, not in this migration.

No RLS changes.

Revision ID: 077
Revises:     076
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS migration_072_flags_backup")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE migration_072_flags_backup (
            tenant_id      UUID NOT NULL PRIMARY KEY REFERENCES tenants(id),
            feature_flags  JSONB NOT NULL
        )
        """
    )
