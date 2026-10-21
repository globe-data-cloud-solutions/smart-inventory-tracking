"""seed_permissions.py, seed_dev_sample.py and bootstrap_sa_account.py refuse to
fall back to DATABASE_URL (the runtime role) outside ENVIRONMENT=local.

No DB: the connect call in each script is replaced with one that records the
URL it was given and stops the script there.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

import migrations.bootstrap_sa_account as bootstrap_sa_account
import migrations.seed_dev_sample as seed_dev_sample

_SCRIPTS_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

import seed_permissions  # noqa: E402

pytestmark = pytest.mark.unit

RUNTIME_URL = "postgresql://runtime@localhost/smart"


class _Connected(Exception):
    """Raised by the fake connect so the script stops right after choosing a URL."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


def _runtime_url_only(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", RUNTIME_URL)
    monkeypatch.setenv("ENVIRONMENT", environment)


def _fake_engine(url: str):
    raise _Connected(url)


async def _fake_asyncpg_connect(**kwargs):
    raise _Connected(f"{kwargs.get('user')}@{kwargs.get('host')}")


def _assert_refused(exc: pytest.ExceptionInfo[SystemExit], prog: str) -> None:
    assert exc.value.code not in (0, None)
    assert str(exc.value.code).startswith(f"{prog}: ")
    assert "MIGRATION_DATABASE_URL" in str(exc.value.code)


class TestSeedPermissions:

    async def test_dev_without_migration_url_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _runtime_url_only(monkeypatch, "dev")
        monkeypatch.setattr(seed_permissions, "create_async_engine", _fake_engine)
        with pytest.raises(SystemExit) as exc:
            await seed_permissions.seed()
        _assert_refused(exc, "seed_permissions")

    async def test_local_falls_back_to_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _runtime_url_only(monkeypatch, "local")
        monkeypatch.setattr(seed_permissions, "create_async_engine", _fake_engine)
        with pytest.raises(_Connected) as exc:
            await seed_permissions.seed()
        assert exc.value.url == RUNTIME_URL


class TestSeedDevSample:

    @pytest.fixture(autouse=True)
    def _seed_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEED_ENABLED", "true")
        monkeypatch.setenv("SEED_SA_PASSWORD", "fake-sa-password")
        monkeypatch.setenv("SEED_SAMPLE_PASSWORD", "fake-sample-password")
        monkeypatch.setattr(seed_dev_sample.asyncpg, "connect", _fake_asyncpg_connect)

    async def test_dev_without_migration_url_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _runtime_url_only(monkeypatch, "dev")
        with pytest.raises(SystemExit) as exc:
            await seed_dev_sample.main()
        _assert_refused(exc, "seed_dev_sample")

    async def test_local_falls_back_to_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _runtime_url_only(monkeypatch, "local")
        with pytest.raises(_Connected) as exc:
            await seed_dev_sample.main()
        assert exc.value.url == "runtime@localhost"


class TestBootstrapSaAccount:

    @pytest.fixture(autouse=True)
    def _sa_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SA_EMAIL_SECRET_NAME", "fake/email/secret")
        monkeypatch.setenv("SA_PASSWORD_SECRET_NAME", "fake/password/secret")
        monkeypatch.setattr(bootstrap_sa_account.sys, "argv", ["bootstrap_sa_account.py"])
        monkeypatch.setattr(bootstrap_sa_account, "_get_secret_value", lambda name: "fake-value")

    async def test_dev_without_migration_url_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _runtime_url_only(monkeypatch, "dev")
        bootstrap_mock = AsyncMock(return_value=True)
        with patch.object(bootstrap_sa_account, "bootstrap", bootstrap_mock):
            with pytest.raises(SystemExit) as exc:
                await bootstrap_sa_account.main()
        _assert_refused(exc, "bootstrap_sa_account")
        bootstrap_mock.assert_not_awaited()

    async def test_local_falls_back_to_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _runtime_url_only(monkeypatch, "local")
        bootstrap_mock = AsyncMock(return_value=True)
        with patch.object(bootstrap_sa_account, "bootstrap", bootstrap_mock):
            await bootstrap_sa_account.main()
        assert bootstrap_mock.await_args.args[2] == RUNTIME_URL
