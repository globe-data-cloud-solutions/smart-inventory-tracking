"""099 — create the current and next two inventory_transactions partitions.

E2E finding F2: a fresh database rejected every receipt with
"no partition of relation inventory_transactions" until scripts/create_partitions.py
was run by hand. Migration 092 defines ensure_inventory_partition(date) but nothing
called it on migrate. This revision calls it for the current month and the next two,
so a new database accepts writes straight after `alembic upgrade head`.

The function is idempotent (it skips a month whose partition exists), so running this
against an environment that already has the partitions changes nothing. Downgrade is a
no-op: dropping a partition would drop ledger rows.

Revision ID: 099
Revises: 098
"""

from alembic import op

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            m date := date_trunc('month', now())::date;
            i int;
        BEGIN
            FOR i IN 0..2 LOOP
                PERFORM ensure_inventory_partition((m + make_interval(months => i))::date);
            END LOOP;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Intentionally empty: partitions hold ledger rows and are never dropped by a migration.
    pass
