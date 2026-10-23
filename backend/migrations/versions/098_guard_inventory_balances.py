"""098 — database guard on inventory_balances (RB-8 bug 5, 2026-10-23).

inventory_balances is a computed read model. CLAUDE.md says the only permitted
writer is _update_running_balance() in ledger_repo.py, but until now nothing in
the database enforced that: no RULE, no trigger.

This migration adds a BEFORE UPDATE OR DELETE row trigger. It raises unless the
current transaction has set the transaction-local flag app.balance_writer = 'on'.
_update_running_balance() sets the flag before its upsert; delete_tenant.py sets
it for the dev-only purge. Seed scripts only INSERT and are not affected.

Limits, stated plainly: this guards against mistakes and bypasses in application
code. It is not a security boundary. Any database session can run
set_config('app.balance_writer', 'on', true). Code review still applies.

Revision ID: 098
Revises: 097
"""

from __future__ import annotations

from alembic import op

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_inventory_balances_write()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF current_setting('app.balance_writer', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION
                    'inventory_balances is written only by _update_running_balance() (app.balance_writer not set)'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_balances_write_guard ON inventory_balances"
    )
    op.execute(
        """
        CREATE TRIGGER inventory_balances_write_guard
            BEFORE UPDATE OR DELETE ON inventory_balances
            FOR EACH ROW EXECUTE FUNCTION guard_inventory_balances_write()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_balances_write_guard ON inventory_balances"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_inventory_balances_write()")
