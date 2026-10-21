"""086 — transfer_discrepancies.

One row per shortfall found at receipt: a transfer line (non-batch) or one lot
of a line (batch) where the destination received less than the source sent.
The row is record-only — TRANSFER_IN credits the received quantity and the
missing quantity lives here and nowhere else.

Append-only BY CODE: the service layer exposes an INSERT path only — there is
no update/delete function. No PostgreSQL RULE is added here.

Status is OPEN. Resolution (write-off / return) comes in a later phase.

Revision ID: 086
Revises:     085
Create Date: 2026-10-13

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""

from __future__ import annotations

from alembic import op

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transfer_discrepancies (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL,
            transfer_order_id  UUID NOT NULL REFERENCES transfer_orders(id),
            transfer_line_id   UUID NOT NULL REFERENCES transfer_order_lines(id),
            product_id         UUID NOT NULL REFERENCES products(id),
            lot_id             UUID NULL REFERENCES stock_lots(id),
            to_warehouse_id    UUID NOT NULL,
            sent_quantity      NUMERIC(15,4) NOT NULL CHECK (sent_quantity > 0),
            received_quantity  NUMERIC(15,4) NOT NULL CHECK (received_quantity >= 0),
            missing_quantity   NUMERIC(15,4) NOT NULL CHECK (missing_quantity > 0),
            reason             VARCHAR(20) NOT NULL
                               CHECK (reason IN ('SHORT','DAMAGED','WRONG_LOT')),
            note               TEXT NULL,
            status             VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN')),
            created_by         UUID NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (received_quantity + missing_quantity = sent_quantity)
        )
        """
    )
    # One row per (line, lot); a NULL lot (non-batch line) counts as one value.
    op.execute(
        "CREATE UNIQUE INDEX uq_transfer_discrepancies_line_lot "
        "ON transfer_discrepancies "
        "(transfer_line_id, COALESCE(lot_id, '00000000-0000-0000-0000-000000000000'::uuid))"
    )
    op.execute(
        "CREATE INDEX idx_transfer_discrepancies_tenant_order "
        "ON transfer_discrepancies (tenant_id, transfer_order_id)"
    )
    op.execute(
        "CREATE INDEX idx_transfer_discrepancies_tenant_status "
        "ON transfer_discrepancies (tenant_id, status)"
    )
    op.execute("ALTER TABLE transfer_discrepancies ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON transfer_discrepancies "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    op.execute(
        "COMMENT ON TABLE transfer_discrepancies IS "
        "'One row per shortfall found at transfer receipt (per line, or per lot of a "
        "batch line). Record-only: TRANSFER_IN credits the received quantity and the "
        "missing quantity lives here. Status OPEN until a later phase resolves it.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transfer_discrepancies")
