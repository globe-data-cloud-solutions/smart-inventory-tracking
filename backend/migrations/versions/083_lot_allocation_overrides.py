"""083 — lot_allocation_overrides.

One row per dispatch where the user's lot selection differed from the order
the dispatch engine suggested (services/dispatch_service.record_override).

Append-only BY CODE: dispatch_service exposes an INSERT path only — there is
no update/delete function. No PostgreSQL RULE is added here.

strategy reuses the dispatch_strategy enum type created by 001 (do not
re-create it here).

Revision ID: 083
Revises:     082
Create Date: 2026-10-13

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""

from __future__ import annotations

from alembic import op

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE lot_allocation_overrides (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID NOT NULL,
            product_id     UUID NOT NULL REFERENCES products(id),
            warehouse_id   UUID NOT NULL,
            strategy       dispatch_strategy NOT NULL,
            movement_type  VARCHAR(30) NOT NULL,
            reference_id   UUID,
            requested_qty  NUMERIC(15,4) NOT NULL CHECK (requested_qty > 0),
            suggested      JSONB NOT NULL,
            chosen         JSONB NOT NULL,
            reason         TEXT,
            overridden_by  UUID NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_lot_allocation_overrides_tenant_product_created "
        "ON lot_allocation_overrides (tenant_id, product_id, created_at)"
    )
    op.execute("ALTER TABLE lot_allocation_overrides ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON lot_allocation_overrides "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lot_allocation_overrides")
