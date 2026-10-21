"""060 — unique constraint on tenant_hierarchy_config(tenant_id, level_name)

Fixes gap G1: renaming a level to a name already used by another level in
the same tenant previously succeeded silently (200) — there was no
uniqueness constraint on the name column, only on (tenant_id, level_number)
from migration 012. The application layer (routers/hierarchy.py) now catches
the resulting UniqueViolationError and returns 422 DUPLICATE_LEVEL_NAME.

Note: the column is named `level_name` (not `name`) — see migration 012.
The constraint name uq_hierarchy_config_tenant_name is kept as specified.

Also adds a standalone index on tenant_id (idx_hier_config_tenant from
migration 012 is a composite (tenant_id, level_number) index, which already
satisfies tenant_id-leading lookups — this index is added defensively per
spec, using IF NOT EXISTS since it may already be covered).

Revision ID: 060
Revises:     059
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_hierarchy_config "
        "ADD CONSTRAINT uq_hierarchy_config_tenant_name UNIQUE (tenant_id, level_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hierarchy_config_tenant_id "
        "ON tenant_hierarchy_config (tenant_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hierarchy_config_tenant_id")
    op.execute(
        "ALTER TABLE tenant_hierarchy_config "
        "DROP CONSTRAINT IF EXISTS uq_hierarchy_config_tenant_name"
    )
