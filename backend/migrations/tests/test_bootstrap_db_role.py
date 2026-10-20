"""Unit tests for bootstrap_db_role.py (owner and runtime DB roles).

No real DB — the asyncpg connection is an AsyncMock that records every SQL
statement, so the tests assert on the generated DDL and grants.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import migrations.bootstrap_db_role as bootstrap_db_role

pytestmark = pytest.mark.unit

OWNER = "smart_owner"
RUNTIME = "smart_runtime"
OWNER_PW = "O" * 40
RUNTIME_PW = "R" * 40


def _mock_conn(existing_roles: set[str], executed: list[str]):
    """A fake asyncpg connection that records execute() SQL."""
    conn = AsyncMock()

    async def fetchval(sql, *args):
        if "FROM pg_roles" in sql:
            return 1 if args and args[0] in existing_roles else None
        if "current_database()" in sql:
            return "smart"
        return None

    conn.fetchval = AsyncMock(side_effect=fetchval)

    async def execute(sql, *args, **kwargs):
        executed.append(sql)
        return None

    conn.execute = AsyncMock(side_effect=execute)

    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_cm)
    conn.close = AsyncMock(return_value=None)
    return conn


async def _run(existing_roles: set[str] = frozenset()) -> list[str]:
    executed: list[str] = []
    conn = _mock_conn(set(existing_roles), executed)
    await bootstrap_db_role.bootstrap(conn, OWNER, OWNER_PW, RUNTIME, RUNTIME_PW)
    return executed


def _for(executed: list[str], role: str) -> list[str]:
    return [sql for sql in executed if f'"{role}"' in sql]


class TestRoleCreation:
    async def test_both_roles_created_nobypassrls(self) -> None:
        executed = await _run()
        for role in (OWNER, RUNTIME):
            creates = [s for s in _for(executed, role) if s.startswith("CREATE ROLE")]
            assert len(creates) == 1
            assert "NOBYPASSRLS" in creates[0]
            assert "NOSUPERUSER" in creates[0]
            assert "NOCREATEDB" in creates[0]
            assert "NOCREATEROLE" in creates[0]

    async def test_existing_roles_altered_not_recreated(self) -> None:
        executed = await _run({OWNER, RUNTIME})
        assert not any(s.startswith("CREATE ROLE") for s in executed)
        assert sum(s.startswith("ALTER ROLE") for s in executed) == 2
        # ALTER must not touch attributes the non-superuser master cannot set.
        for sql in executed:
            if sql.startswith("ALTER ROLE"):
                assert "BYPASSRLS" not in sql
                assert "SUPERUSER" not in sql


class TestGrants:
    async def test_owner_gets_create_on_database_and_schema(self) -> None:
        owner_sql = _for(await _run(), OWNER)
        assert 'GRANT CONNECT, CREATE ON DATABASE "smart" TO "smart_owner"' in owner_sql
        assert 'GRANT USAGE, CREATE ON SCHEMA public TO "smart_owner"' in owner_sql

    async def test_runtime_gets_connect_and_usage_only(self) -> None:
        runtime_sql = _for(await _run(), RUNTIME)
        grants = [s for s in runtime_sql if s.startswith("GRANT")]
        assert grants == [
            'GRANT CONNECT ON DATABASE "smart" TO "smart_runtime"',
            'GRANT USAGE ON SCHEMA public TO "smart_runtime"',
        ]
        assert not any("CREATE" in s for s in grants)

    async def test_runtime_create_revoked(self) -> None:
        runtime_sql = _for(await _run({RUNTIME}), RUNTIME)
        assert 'REVOKE CREATE ON DATABASE "smart" FROM "smart_runtime"' in runtime_sql
        assert 'REVOKE CREATE ON SCHEMA public FROM "smart_runtime"' in runtime_sql

    async def test_idempotent_same_statements_on_rerun(self) -> None:
        first = await _run({OWNER, RUNTIME})
        second = await _run({OWNER, RUNTIME})
        assert first == second


class TestValidation:
    async def test_same_owner_and_runtime_role_rejected(self) -> None:
        conn = _mock_conn(set(), [])
        with pytest.raises(SystemExit):
            await bootstrap_db_role.bootstrap(
                conn, RUNTIME, OWNER_PW, RUNTIME, RUNTIME_PW
            )

    def test_owner_role_defaults_to_smart_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OWNER_DB_ROLE", raising=False)
        monkeypatch.setenv("OWNER_DB_PASSWORD", OWNER_PW)
        assert bootstrap_db_role._validated(
            "OWNER_DB_ROLE", "OWNER_DB_PASSWORD", "smart_owner"
        ) == (
            "smart_owner",
            OWNER_PW,
        )

    def test_missing_owner_password_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OWNER_DB_PASSWORD", raising=False)
        with pytest.raises(SystemExit):
            bootstrap_db_role._validated(
                "OWNER_DB_ROLE", "OWNER_DB_PASSWORD", "smart_owner"
            )

    def test_weak_password_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OWNER_DB_PASSWORD", "short'; DROP")
        with pytest.raises(SystemExit):
            bootstrap_db_role._validated(
                "OWNER_DB_ROLE", "OWNER_DB_PASSWORD", "smart_owner"
            )

    def test_invalid_role_name_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RUNTIME_DB_ROLE", 'bad"role')
        monkeypatch.setenv("RUNTIME_DB_PASSWORD", RUNTIME_PW)
        with pytest.raises(SystemExit):
            bootstrap_db_role._validated("RUNTIME_DB_ROLE", "RUNTIME_DB_PASSWORD")


class TestMain:
    async def test_main_uses_master_connection_and_never_prints_passwords(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        for k, v in {
            "PGHOST": "db",
            "PGDATABASE": "smart",
            "PGUSER": "master",
            "PGPASSWORD": "m",
            "OWNER_DB_PASSWORD": OWNER_PW,
            "RUNTIME_DB_ROLE": RUNTIME,
            "RUNTIME_DB_PASSWORD": RUNTIME_PW,
        }.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("OWNER_DB_ROLE", raising=False)
        executed: list[str] = []
        conn = _mock_conn(set(), executed)
        connect = AsyncMock(return_value=conn)
        with patch("migrations.bootstrap_db_role.asyncpg.connect", connect):
            await bootstrap_db_role.main()
        assert connect.await_args.kwargs["user"] == "master"
        out = capsys.readouterr().out
        assert OWNER_PW not in out and RUNTIME_PW not in out
        assert any('CREATE ROLE "smart_owner"' in s for s in executed)
