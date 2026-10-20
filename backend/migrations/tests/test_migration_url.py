"""Unit tests for migration_url.py: migrations run as the owner role.

DATABASE_URL (runtime role) is only an acceptable fallback for local dev.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from migrations.migration_url import migration_database_url

pytestmark = pytest.mark.unit

OWNER_URL = "postgresql+asyncpg://smart_owner:x@db:5432/smart"
RUNTIME_URL = "postgresql+asyncpg://smart_runtime:x@db:5432/smart"


class TestMigrationDatabaseUrl:
    @pytest.mark.parametrize("env", ["local", "dev", "stage", "prod", ""])
    def test_owner_url_used_when_set(self, env: str) -> None:
        environ = {
            "ENVIRONMENT": env,
            "MIGRATION_DATABASE_URL": OWNER_URL,
            "DATABASE_URL": RUNTIME_URL,
        }
        assert migration_database_url(environ) == OWNER_URL

    def test_local_falls_back_to_database_url(self) -> None:
        assert (
            migration_database_url(
                {"ENVIRONMENT": "local", "DATABASE_URL": RUNTIME_URL}
            )
            == RUNTIME_URL
        )

    @pytest.mark.parametrize("env", ["dev", "stage", "prod", "", "LOCAL"])
    def test_no_fallback_outside_local(self, env: str) -> None:
        with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL is required"):
            migration_database_url({"ENVIRONMENT": env, "DATABASE_URL": RUNTIME_URL})

    def test_unset_environment_does_not_fall_back(self) -> None:
        with pytest.raises(RuntimeError):
            migration_database_url({"DATABASE_URL": RUNTIME_URL})

    def test_empty_owner_url_treated_as_unset(self) -> None:
        with pytest.raises(RuntimeError):
            migration_database_url(
                {
                    "ENVIRONMENT": "dev",
                    "MIGRATION_DATABASE_URL": "",
                    "DATABASE_URL": RUNTIME_URL,
                }
            )

    def test_local_with_no_url_at_all_raises(self) -> None:
        with pytest.raises(RuntimeError):
            migration_database_url({"ENVIRONMENT": "local"})

    def test_env_py_uses_resolver(self) -> None:
        env_py = (Path(__file__).resolve().parents[1] / "env.py").read_text(
            encoding="utf-8"
        )
        assert "migration_database_url(os.environ)" in env_py
        assert 'os.environ["DATABASE_URL"]' not in env_py
