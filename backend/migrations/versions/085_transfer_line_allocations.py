"""085 — transfer_line_allocations.

One row per lot a transfer line was split into at approval. Lot identity
(number, expiry, first receipt date) stays on stock_lots, so the destination
credits the same lot_id.

Append-only BY CODE: the service layer exposes an INSERT path only — there is
no update/delete function. No PostgreSQL RULE is added here.

override_id points at the lot_allocation_overrides row (083) when the
approver's selection differed from the engine's suggested order.

Revision ID: 085
Revises:     084
Create Date: 2026-10-13

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transfer_line_allocations (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL,
            transfer_order_id  UUID NOT NULL REFERENCES transfer_orders(id),
            transfer_line_id   UUID NOT NULL REFERENCES transfer_order_lines(id),
            product_id         UUID NOT NULL REFERENCES products(id),
            lot_id             UUID NOT NULL REFERENCES stock_lots(id),
            from_warehouse_id  UUID NOT NULL,
            quantity           NUMERIC(15,4) NOT NULL CHECK (quantity > 0),
            is_override        BOOLEAN NOT NULL DEFAULT false,
            override_id        UUID REFERENCES lot_allocation_overrides(id),
            created_by         UUID NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (transfer_line_id, lot_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_transfer_line_allocations_tenant_order "
        "ON transfer_line_allocations (tenant_id, transfer_order_id)"
    )
    op.execute(
        "CREATE INDEX idx_transfer_line_allocations_tenant_lot "
        "ON transfer_line_allocations (tenant_id, lot_id)"
    )
    op.execute("ALTER TABLE transfer_line_allocations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON transfer_line_allocations "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    op.execute(
        "COMMENT ON TABLE transfer_line_allocations IS "
        "'One row per lot a transfer line was split into at approval. Lot identity "
        "(number, expiry, first receipt date) stays on stock_lots, so the destination "
        "credits the same lot_id.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transfer_line_allocations")
