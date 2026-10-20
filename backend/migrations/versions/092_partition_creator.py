"""092 — ensure_inventory_partition(date): partition creator with tenant RLS (D12).

Session 20 / S20b (D12). Since 091 the app and the Celery worker connect as
the runtime role (RUNTIME_DB_ROLE, default smart_runtime), which does not own
inventory_transactions and so cannot CREATE a partition or ALTER it to add RLS.
Monthly partition maintenance (shared/outbox/worker.py
_ensure_future_partitions, scripts/create_partitions.py) therefore goes
through this SECURITY DEFINER function, owned by the migration role.

ensure_inventory_partition(p_month):
    - partition = inventory_transactions_YYYY_MM for the month containing
      p_month, range [first of month, first of next month)
    - created only if it does not exist yet (same statement the worker and
      script used; neither created indexes, so none are created here)
    - always, existing or new: ENABLE ROW LEVEL SECURITY and a fresh
      tenant_isolation policy with the 091 expression (USING + WITH CHECK)

EXECUTE is revoked from PUBLIC and granted only to the runtime role.
Downgrade drops the function; it never drops a partition.
"""
import os
import re

from alembic import op

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.environ.get("RUNTIME_DB_ROLE", "smart_runtime")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise RuntimeError(f"Migration 092: RUNTIME_DB_ROLE {role!r} is not a valid role name")
    return role


# Copied from migration 091 (V_EXPR) — the tenant_isolation expression every
# inventory_transactions partition carries.
V_EXPR = (
    "(tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid "
    "OR COALESCE(current_setting('app.is_sa', true), '') = 'on')"
)

_SIGNATURE = "ensure_inventory_partition(date)"


def upgrade() -> None:
    role = _runtime_role()

    op.execute(f"""
        CREATE OR REPLACE FUNCTION ensure_inventory_partition(p_month date)
        RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $fn$
        DECLARE
            v_expr  text := $e${V_EXPR}$e$;
            v_start date := date_trunc('month', p_month)::date;
            v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
            v_name  text := format('inventory_transactions_%s', to_char(v_start, 'YYYY_MM'));
        BEGIN
            IF to_regclass(v_name) IS NULL THEN
                EXECUTE format(
                    'CREATE TABLE %I PARTITION OF inventory_transactions '
                    'FOR VALUES FROM (%L) TO (%L)',
                    v_name, v_start, v_end
                );
            END IF;
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', v_name);
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', v_name);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I USING %s WITH CHECK %s',
                v_name, v_expr, v_expr
            );
        END
        $fn$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO "{role}"')


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {_SIGNATURE}")
