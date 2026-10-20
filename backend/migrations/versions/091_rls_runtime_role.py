"""091 — Non-owner runtime role: grants, NULLIF + SA policies, audit INSERT,
partition and tenant_contacts/activity RLS, pre-auth SECURITY DEFINER functions.

Session 20 / S20b (D1-D11). Until now the app connected as the table owner,
which bypasses RLS (FORCE was only on four tables), so tenant_isolation was
never really exercised. From here the app connects as the runtime role
(RUNTIME_DB_ROLE, default smart_runtime: non-superuser, NOBYPASSRLS) and
migrations keep running as the owner (MIGRATION_DATABASE_URL).

    1. Gate: the runtime role must already exist (created by the db-bootstrap
       task in AWS, by hand locally). The migration never creates roles.
    2. Runtime gets DML on all tables and USAGE/SELECT on all sequences, plus
       default privileges for objects later migrations create (no FOR ROLE:
       applies to objects created by the migration role).
    3. tenant_isolation everywhere becomes
         tenant_id = NULLIF(app.current_tenant_id, '')::uuid OR app.is_sa = 'on'
       with the same WITH CHECK. NULLIF: an empty tenant (reset context,
       system jobs) matches nothing instead of failing the uuid cast. is_sa:
       SA requests and system jobs see across tenants (D2, D3).
    4. audit_logs: audit_select gets the new expression, new audit_insert
       WITH CHECK — an INSERT must carry the caller's own tenant (D4).
       The no_update/no_delete RULEs are untouched.
    5. NO FORCE on products, warehouses, inventory_balances,
       inventory_transactions (D8): FORCE would also bind the owner, which
       the SECURITY DEFINER functions below rely on not being bound.
    6. Every inventory_transactions partition gets RLS + tenant_isolation (D9),
       so a direct query on a child table is isolated like the parent.
    7. tenant_contacts and tenant_activity_log get RLS (D10). outbox stays
       global by design: the Celery worker polls across tenants.
    8. Pre-auth lookups (D6): login, password change/reset, email verification
       run before any tenant context exists. Each is a SECURITY DEFINER SQL
       function owned by the migration role, copied statement-for-statement
       from auth.py / email_verification.py, EXECUTE granted only to runtime.

Downgrade restores the original expression, drops the functions, revokes the
grants and default privileges, and disables the RLS this added. It does NOT
re-add FORCE.
"""

import os
import re

from alembic import op

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.environ.get("RUNTIME_DB_ROLE", "smart_runtime")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise RuntimeError(
            f"Migration 091: RUNTIME_DB_ROLE {role!r} is not a valid role name"
        )
    return role


# Shared with scripts/create_partitions.py and shared/outbox/worker.py
# (_ensure_future_partitions), which must create the same policy on new partitions.
V_EXPR = (
    "(tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid "
    "OR COALESCE(current_setting('app.is_sa', true), '') = 'on')"
)
_OLD_EXPR = "(tenant_id = (current_setting('app.current_tenant_id', true))::uuid)"

_FORCE_DRIFT_TABLES = (
    "products",
    "warehouses",
    "inventory_balances",
    "inventory_transactions",
)
_D10_TABLES = ("tenant_contacts", "tenant_activity_log")

_USER_COLUMNS = """
    id uuid, email character varying(320), full_name character varying(255),
    tenant_id uuid, password_hash character varying(255), must_reset_password boolean,
    system_role character varying(10), is_active boolean,
    email_verified_at timestamp with time zone, is_account_owner boolean,
    tenant_slug character varying(100), tenant_active boolean, tenant_status tenant_status
"""

# (signature, DDL). Each body is the statement it replaces, with :params -> p_params.
_FUNCTIONS: list[tuple[str, str]] = [
    (
        "auth_user_by_email(text)",
        f"""
        CREATE FUNCTION auth_user_by_email(p_email text)
        RETURNS TABLE ({_USER_COLUMNS})
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            SELECT u.id, u.email, u.full_name, u.tenant_id,
                   u.password_hash, u.must_reset_password,
                   u.system_role, u.is_active, u.email_verified_at,
                   u.is_account_owner,
                   t.slug AS tenant_slug,
                   t.is_active AS tenant_active, t.status AS tenant_status
            FROM   users u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            WHERE  lower(u.email) = lower(p_email)
            LIMIT  1
        $f$
        """,
    ),
    (
        "auth_user_by_id(uuid)",
        f"""
        CREATE FUNCTION auth_user_by_id(p_user_id uuid)
        RETURNS TABLE ({_USER_COLUMNS})
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            SELECT u.id, u.email, u.full_name, u.tenant_id,
                   u.password_hash, u.must_reset_password,
                   u.system_role, u.is_active, u.email_verified_at,
                   u.is_account_owner,
                   t.slug AS tenant_slug,
                   t.is_active AS tenant_active, t.status AS tenant_status
            FROM   users u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            WHERE  u.id = p_user_id
            LIMIT  1
        $f$
        """,
    ),
    (
        "auth_active_user_id(text)",
        """
        CREATE FUNCTION auth_active_user_id(p_email text)
        RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            SELECT id FROM users WHERE lower(email) = p_email AND is_active = true
        $f$
        """,
    ),
    (
        "auth_active_unverified_user_id(text)",
        """
        CREATE FUNCTION auth_active_unverified_user_id(p_email text)
        RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            SELECT id FROM users
            WHERE lower(email) = p_email AND is_active = true AND email_verified_at IS NULL
        $f$
        """,
    ),
    (
        "auth_user_email_by_id(uuid)",
        """
        CREATE FUNCTION auth_user_email_by_id(p_user_id uuid)
        RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            SELECT email::text FROM users WHERE id = p_user_id
        $f$
        """,
    ),
    (
        "auth_latest_terms_version(uuid)",
        """
        CREATE FUNCTION auth_latest_terms_version(p_tenant_id uuid)
        RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            SELECT terms_version::text FROM terms_acceptances
            WHERE tenant_id = p_tenant_id ORDER BY accepted_at DESC LIMIT 1
        $f$
        """,
    ),
    (
        "auth_mark_email_verified(uuid)",
        """
        CREATE FUNCTION auth_mark_email_verified(p_user_id uuid)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            UPDATE users SET email_verified_at = now()
            WHERE id = p_user_id AND email_verified_at IS NULL
        $f$
        """,
    ),
    (
        "auth_update_password(uuid, text)",
        """
        CREATE FUNCTION auth_update_password(p_user_id uuid, p_hash text)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            UPDATE users SET password_hash = p_hash, must_reset_password = false,
                   updated_at = now() WHERE id = p_user_id
        $f$
        """,
    ),
    (
        "auth_apply_password_reset(uuid, text)",
        """
        CREATE FUNCTION auth_apply_password_reset(p_user_id uuid, p_hash text)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
        AS $f$
            UPDATE users SET password_hash = p_hash, must_reset_password = false,
                   email_verified_at = COALESCE(email_verified_at, now()), updated_at = now()
            WHERE id = p_user_id
        $f$
        """,
    ),
]


def upgrade() -> None:
    role = _runtime_role()

    # 1. Gate
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                RAISE EXCEPTION 'Migration 091: runtime role "{role}" does not exist. '
                    'Create it (LOGIN, NOSUPERUSER, NOBYPASSRLS) before upgrading, '
                    'or set RUNTIME_DB_ROLE to the existing runtime role name.';
            END IF;
        END $$;
    """)

    # 2. Grants
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'
    )
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"'
    )
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{role}"'
    )

    # 3. tenant_isolation rewrite (D2, D3)
    op.execute(f"""
        DO $$
        DECLARE
            v_expr text := $e${V_EXPR}$e$;
            r record;
        BEGIN
            FOR r IN
                SELECT tablename FROM pg_policies
                WHERE schemaname = 'public' AND policyname = 'tenant_isolation'
            LOOP
                EXECUTE format('DROP POLICY tenant_isolation ON %I', r.tablename);
                EXECUTE format(
                    'CREATE POLICY tenant_isolation ON %I USING %s WITH CHECK %s',
                    r.tablename, v_expr, v_expr
                );
            END LOOP;
        END $$;
    """)

    # 4. audit_logs (D4)
    op.execute("DROP POLICY audit_select ON audit_logs")
    op.execute(f"CREATE POLICY audit_select ON audit_logs FOR SELECT USING {V_EXPR}")
    op.execute(
        f"CREATE POLICY audit_insert ON audit_logs FOR INSERT WITH CHECK {V_EXPR}"
    )

    # 5. FORCE drift removal (D8)
    for table in _FORCE_DRIFT_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    # 6. Partitions (D9)
    op.execute(f"""
        DO $$
        DECLARE
            v_expr text := $e${V_EXPR}$e$;
            r record;
        BEGIN
            FOR r IN
                SELECT c.relname
                FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
                WHERE i.inhparent = 'inventory_transactions'::regclass
            LOOP
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', r.relname);
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', r.relname);
                EXECUTE format(
                    'CREATE POLICY tenant_isolation ON %I USING %s WITH CHECK %s',
                    r.relname, v_expr, v_expr
                );
            END LOOP;
        END $$;
    """)

    # 7. tenant_contacts, tenant_activity_log (D10); outbox stays global
    for table in _D10_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING {V_EXPR} WITH CHECK {V_EXPR}"
        )
    op.execute(
        "COMMENT ON TABLE outbox IS "
        "'Global by design (D10): the Celery worker polls across tenants.'"
    )

    # 8. Pre-auth SECURITY DEFINER functions (D6)
    for signature, ddl in _FUNCTIONS:
        op.execute(ddl)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f'GRANT EXECUTE ON FUNCTION {signature} TO "{role}"')


def downgrade() -> None:
    role = _runtime_role()

    for signature, _ddl in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")

    op.execute("COMMENT ON TABLE outbox IS NULL")
    for table in _D10_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("""
        DO $$
        DECLARE
            r record;
        BEGIN
            FOR r IN
                SELECT c.relname
                FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
                WHERE i.inhparent = 'inventory_transactions'::regclass
            LOOP
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', r.relname);
                EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', r.relname);
            END LOOP;
        END $$;
    """)

    op.execute("DROP POLICY IF EXISTS audit_insert ON audit_logs")
    op.execute("DROP POLICY audit_select ON audit_logs")
    op.execute(f"CREATE POLICY audit_select ON audit_logs FOR SELECT USING {_OLD_EXPR}")

    op.execute(f"""
        DO $$
        DECLARE
            v_expr text := $e${_OLD_EXPR}$e$;
            r record;
        BEGIN
            FOR r IN
                SELECT tablename FROM pg_policies
                WHERE schemaname = 'public' AND policyname = 'tenant_isolation'
            LOOP
                EXECUTE format('DROP POLICY tenant_isolation ON %I', r.tablename);
                EXECUTE format('CREATE POLICY tenant_isolation ON %I USING %s', r.tablename, v_expr);
            END LOOP;
        END $$;
    """)

    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM "{role}"'
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{role}"'
    )
    op.execute(f'REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM "{role}"')
    op.execute(
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM "{role}"'
    )
