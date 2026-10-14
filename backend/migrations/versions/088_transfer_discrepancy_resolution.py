"""088 — transfer discrepancy resolution.

A discrepancy row (086) is inserted OPEN at receipt and may be updated exactly
once, OPEN -> RESOLVED, by the resolve path only
(services/transfer_discrepancies.resolve_discrepancy). This is a deliberate,
documented exception to 086's append-only-by-code rule, like the D1 set-expiry
exception on stock_lots. Every resolution also writes an audit_logs row in the
same transaction. No other update or delete path exists.

Columns added (all NULL while OPEN):

    resolution       WRITTEN_OFF | RETURNED | ARRIVED_LATE | RECEIVED_AS_LOT
    resolved_lot_id  the lot that actually arrived (RECEIVED_AS_LOT only)
    resolution_note  free text (required by the service for WRITTEN_OFF)
    resolved_by      the user who resolved it
    resolved_at      when it was resolved

Status CHECK widens from ('OPEN') to ('OPEN','RESOLVED'). Two CHECKs keep the
resolution columns consistent with the status, two more tie resolved_lot_id
to RECEIVED_AS_LOT (written so an OPEN row with NULL resolution passes).

Grants (transfer:resolve_discrepancy, FULL): TA, NM, RM. ON CONFLICT DO
NOTHING; downgrade deletes exactly these three rows.

Downgrade fails if any RESOLVED row exists (the restored status CHECK only
allows OPEN). That is intended: resolved rows must not be silently lost.

RLS is already enabled on transfer_discrepancies (tenant_isolation policy,
086) — no policy is added here.

Revision ID: 088
Revises:     087
Create Date: 2026-10-14

Round-trip tested: alembic upgrade head -> downgrade -1 -> upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE transfer_discrepancies
            ADD COLUMN resolution      VARCHAR(20) NULL
                CHECK (resolution IN ('WRITTEN_OFF','RETURNED','ARRIVED_LATE','RECEIVED_AS_LOT')),
            ADD COLUMN resolved_lot_id UUID NULL REFERENCES stock_lots(id),
            ADD COLUMN resolution_note TEXT NULL,
            ADD COLUMN resolved_by     UUID NULL,
            ADD COLUMN resolved_at     TIMESTAMPTZ NULL
        """
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "DROP CONSTRAINT transfer_discrepancies_status_check"
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "ADD CONSTRAINT ck_transfer_discrepancies_status "
        "CHECK (status IN ('OPEN','RESOLVED'))"
    )
    op.execute(
        """
        ALTER TABLE transfer_discrepancies
        ADD CONSTRAINT ck_transfer_discrepancies_resolution_state CHECK (
            (status = 'OPEN' AND resolution IS NULL AND resolved_lot_id IS NULL
                AND resolved_by IS NULL AND resolved_at IS NULL)
            OR
            (status = 'RESOLVED' AND resolution IS NOT NULL
                AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)
        )
        """
    )
    # resolved_lot_id set <=> resolution = RECEIVED_AS_LOT, as two CHECKs so a
    # NULL resolution (OPEN row) passes both.
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "ADD CONSTRAINT ck_transfer_discrepancies_resolved_lot "
        "CHECK (resolved_lot_id IS NULL OR resolution = 'RECEIVED_AS_LOT')"
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "ADD CONSTRAINT ck_transfer_discrepancies_resolved_lot_required "
        "CHECK (resolution IS DISTINCT FROM 'RECEIVED_AS_LOT' OR resolved_lot_id IS NOT NULL)"
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_code, action_id, grant_type, is_active)
        VALUES
            ('TA', 'transfer:resolve_discrepancy', 'FULL', true),
            ('NM', 'transfer:resolve_discrepancy', 'FULL', true),
            ('RM', 'transfer:resolve_discrepancy', 'FULL', true)
        ON CONFLICT (role_code, action_id) DO NOTHING
        """
    )
    op.execute(
        "COMMENT ON TABLE transfer_discrepancies IS "
        "'One row per shortfall found at transfer receipt (per line, or per lot of a "
        "batch line). Inserted OPEN at receipt: TRANSFER_IN credits the received "
        "quantity and the missing quantity lives here. Updated exactly once, "
        "OPEN -> RESOLVED, by the resolve path only (WRITTEN_OFF, RETURNED, "
        "ARRIVED_LATE or RECEIVED_AS_LOT), with an audit_logs row in the same "
        "transaction.'"
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE (role_code, action_id) IN (
            ('TA', 'transfer:resolve_discrepancy'),
            ('NM', 'transfer:resolve_discrepancy'),
            ('RM', 'transfer:resolve_discrepancy')
        )
        """
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "DROP CONSTRAINT ck_transfer_discrepancies_resolved_lot_required"
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "DROP CONSTRAINT ck_transfer_discrepancies_resolved_lot"
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "DROP CONSTRAINT ck_transfer_discrepancies_resolution_state"
    )
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "DROP CONSTRAINT ck_transfer_discrepancies_status"
    )
    op.execute(
        """
        ALTER TABLE transfer_discrepancies
            DROP COLUMN resolved_at,
            DROP COLUMN resolved_by,
            DROP COLUMN resolution_note,
            DROP COLUMN resolved_lot_id,
            DROP COLUMN resolution
        """
    )
    # Fails while any RESOLVED row exists — intended.
    op.execute(
        "ALTER TABLE transfer_discrepancies "
        "ADD CONSTRAINT transfer_discrepancies_status_check "
        "CHECK (status IN ('OPEN'))"
    )
    op.execute(
        "COMMENT ON TABLE transfer_discrepancies IS "
        "'One row per shortfall found at transfer receipt (per line, or per lot of a "
        "batch line). Record-only: TRANSFER_IN credits the received quantity and the "
        "missing quantity lives here. Status OPEN until a later phase resolves it.'"
    )
