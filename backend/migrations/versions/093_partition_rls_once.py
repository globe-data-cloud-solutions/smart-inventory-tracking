"""093 — ensure_inventory_partition(date): apply RLS and policy only when missing.

Session 20 / S20b (D12 lock fix). The 092 body ran ENABLE ROW LEVEL SECURITY
and DROP/CREATE POLICY tenant_isolation on every call, so each worker run took
an ACCESS EXCLUSIVE lock on partitions that already had both. This revision
replaces the function body only:
    - partition CREATE unchanged from 092
    - ENABLE ROW LEVEL SECURITY only if relrowsecurity is false
    - CREATE POLICY tenant_isolation only if the partition has no such policy

Same signature, language, SECURITY DEFINER and search_path. CREATE OR REPLACE
keeps the existing owner and EXECUTE grants from 092, so none are re-issued.
Downgrade restores the unconditional 092 body; it never drops a partition.
"""

from alembic import op

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


# Copied from migration 091 (V_EXPR) — the tenant_isolation expression every
# inventory_transactions partition carries.
V_EXPR = (
    "(tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid "
    "OR COALESCE(current_setting('app.is_sa', true), '') = 'on')"
)


def upgrade() -> None:
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
            IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = v_name::regclass) THEN
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', v_name);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_policy p
                WHERE p.polrelid = v_name::regclass AND p.polname = 'tenant_isolation'
            ) THEN
                EXECUTE format(
                    'CREATE POLICY tenant_isolation ON %I USING %s WITH CHECK %s',
                    v_name, v_expr, v_expr
                );
            END IF;
        END
        $fn$
    """)


def downgrade() -> None:
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
