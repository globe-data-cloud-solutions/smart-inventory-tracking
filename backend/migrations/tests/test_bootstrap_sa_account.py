"""Unit tests for bootstrap_sa_account.py (stage/prod SA-only bootstrap).

No real DB or AWS — asyncpg.connect and boto3.client are both mocked. The
fake secrets client below matches just the one boto3 method this script
calls (get_secret_value), standing in for moto (not a project dependency).
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import migrations.bootstrap_sa_account as bootstrap_sa_account
from migrations.seed_common import SA_EMAIL

pytestmark = pytest.mark.unit

FAKE_EMAIL = "sa@real-tenant-example.com"
FAKE_PASSWORD = "S3cretSaPassw0rd!"


class _FakeSecretsClient:
    """Stands in for boto3's secretsmanager client: get_secret_value only."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_secret_value(self, SecretId: str) -> dict:
        if SecretId not in self._values:
            raise KeyError(f"no such secret: {SecretId}")
        return {"SecretString": self._values[SecretId]}


def _patch_secrets(email: str = FAKE_EMAIL, password: str = FAKE_PASSWORD):
    fake_client = _FakeSecretsClient({
        "fake/email/secret": email,
        "fake/password/secret": password,
    })
    return patch("boto3.client", return_value=fake_client)


def _mock_conn(existing_emails: set[str], inserted: list[dict]):
    """A fake asyncpg connection + transaction context manager."""
    conn = AsyncMock()

    async def fetchval(sql, *args):
        if "SELECT 1 FROM users WHERE email" in sql:
            return 1 if args and args[0] in existing_emails else None
        return None

    conn.fetchval = AsyncMock(side_effect=fetchval)

    async def execute(sql, *args, **kwargs):
        if "INSERT INTO" in sql and '"users"' in sql:
            import json
            inserted.append(json.loads(args[0]))
        return None

    conn.execute = AsyncMock(side_effect=execute)

    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_cm)
    conn.close = AsyncMock(return_value=None)
    return conn


class TestGetSecretValue:

    def test_fetches_secret_string_by_name(self) -> None:
        with _patch_secrets():
            value = bootstrap_sa_account._get_secret_value("fake/email/secret")
        assert value == FAKE_EMAIL


class TestResolveArg:

    def test_cli_value_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SA_EMAIL_SECRET_NAME", "from-env")
        assert bootstrap_sa_account._resolve_arg("from-cli", "SA_EMAIL_SECRET_NAME", "--x") == "from-cli"

    def test_env_used_when_no_cli_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SA_EMAIL_SECRET_NAME", "from-env")
        assert bootstrap_sa_account._resolve_arg(None, "SA_EMAIL_SECRET_NAME", "--x") == "from-env"

    def test_missing_both_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SA_EMAIL_SECRET_NAME", raising=False)
        with pytest.raises(SystemExit):
            bootstrap_sa_account._resolve_arg(None, "SA_EMAIL_SECRET_NAME", "--x")


class TestBootstrap:

    async def test_creates_sa_when_absent(self) -> None:
        inserted: list[dict] = []
        conn = _mock_conn(existing_emails=set(), inserted=inserted)

        with patch("migrations.bootstrap_sa_account.asyncpg.connect", AsyncMock(return_value=conn)):
            created = await bootstrap_sa_account.bootstrap(FAKE_EMAIL, FAKE_PASSWORD, "postgresql://fake")

        assert created is True
        assert len(inserted) == 1
        assert inserted[0]["email"] == FAKE_EMAIL
        assert inserted[0]["password_hash"] != FAKE_PASSWORD  # hashed, not stored raw

    async def test_existing_sa_is_never_overwritten(self) -> None:
        inserted: list[dict] = []
        conn = _mock_conn(existing_emails={FAKE_EMAIL}, inserted=inserted)

        with patch("migrations.bootstrap_sa_account.asyncpg.connect", AsyncMock(return_value=conn)):
            created = await bootstrap_sa_account.bootstrap(FAKE_EMAIL, FAKE_PASSWORD, "postgresql://fake")

        assert created is False
        assert inserted == []

    async def test_dev_sa_email_constant_untouched_by_this_script(self) -> None:
        # bootstrap_sa_account always uses the secret-provided email, never the
        # hardcoded dev SA_EMAIL constant — confirm it doesn't leak in here.
        inserted: list[dict] = []
        conn = _mock_conn(existing_emails=set(), inserted=inserted)

        with patch("migrations.bootstrap_sa_account.asyncpg.connect", AsyncMock(return_value=conn)):
            await bootstrap_sa_account.bootstrap(FAKE_EMAIL, FAKE_PASSWORD, "postgresql://fake")

        assert inserted[0]["email"] != SA_EMAIL
        assert inserted[0]["email"] == FAKE_EMAIL


class TestNoSecretLeakageInLogs:

    async def test_main_never_prints_email_or_password(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(
            bootstrap_sa_account, "parse_args",
            lambda argv: type("Args", (), {
                "email_secret_name": "fake/email/secret",
                "password_secret_name": "fake/password/secret",
            })(),
        )

        conn = _mock_conn(existing_emails=set(), inserted=[])

        with _patch_secrets(), \
             patch("migrations.bootstrap_sa_account.asyncpg.connect", AsyncMock(return_value=conn)):
            await bootstrap_sa_account.main()

        out = capsys.readouterr().out
        assert FAKE_EMAIL not in out
        assert FAKE_PASSWORD not in out

    def test_caplog_never_contains_secret_values(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG):
            with _patch_secrets():
                bootstrap_sa_account._get_secret_value("fake/password/secret")
        assert FAKE_PASSWORD not in caplog.text
