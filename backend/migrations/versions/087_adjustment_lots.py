"""087 — lot columns on adjustment_orders.

An adjustment on a batch-tracked product now names the lot it posts against.
A removal picks an existing lot (lot_id). An addition picks an existing lot,
enters a new lot number (lot_number + expiry_date), or asks for an auto lot
(auto_lot).

A new lot is created only at posting, never while the adjustment is a DRAFT or
PENDING_APPROVAL — lot_number / expiry_date / auto_lot hold what the user
entered until then. At posting lot_id is set to the lot that was actually
posted.

lot_number has the same length as stock_lots.lot_number (VARCHAR(100)).

RLS is already enabled on adjustment_orders (tenant_isolation policy) — no
policy is added here.

Revision ID: 087
Revises:     086
Create Date: 2026-10-13

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE adjustment_orders
            ADD COLUMN lot_id       UUID NULL REFERENCES stock_lots(id),
            ADD COLUMN lot_number   VARCHAR(100) NULL,
            ADD COLUMN expiry_date  DATE NULL,
            ADD COLUMN auto_lot     BOOLEAN NOT NULL DEFAULT false,
            ADD CONSTRAINT ck_adjustment_orders_auto_lot_no_number
                CHECK (NOT (auto_lot AND lot_number IS NOT NULL))
        """
    )
    op.execute(
        "CREATE INDEX ix_adjustment_orders_tenant_lot "
        "ON adjustment_orders (tenant_id, lot_id)"
    )
    op.execute(
        "COMMENT ON COLUMN adjustment_orders.lot_number IS "
        "'New lot number entered by the user. The lot is created only at posting.'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_adjustment_orders_tenant_lot")
    op.execute(
        """
        ALTER TABLE adjustment_orders
            DROP CONSTRAINT IF EXISTS ck_adjustment_orders_auto_lot_no_number,
            DROP COLUMN IF EXISTS auto_lot,
            DROP COLUMN IF EXISTS expiry_date,
            DROP COLUMN IF EXISTS lot_number,
            DROP COLUMN IF EXISTS lot_id
        """
    )
