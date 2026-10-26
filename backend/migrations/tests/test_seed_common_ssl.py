"""connect_kwargs takes the SSL mode from the database URL.

A local Postgres without SSL rejected the seed's hardcoded ssl=require
("rejected SSL upgrade"). The URL's own ?ssl= / ?sslmode= now decides; with
none, only ENVIRONMENT=local relaxes the default to "prefer".
"""

from __future__ import annotations

import pytest
from migrations.seed_common import connect_kwargs

pytestmark = pytest.mark.unit

BASE = "postgresql+asyncpg://smart_owner:p%40ss@db.example:5432/smart_e2e"


def test_aws_style_url_keeps_require(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "dev")
    kw = connect_kwargs(BASE + "?ssl=require")
    assert kw["ssl"] == "require"
    assert kw["database"] == "smart_e2e"
    assert kw["password"] == "p@ss"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?ssl=disable", "disable"),
        ("?sslmode=disable", "disable"),
        ("?ssl=false", "disable"),
        ("?ssl=true", "require"),
        ("?sslmode=verify-full", "verify-full"),
    ],
)
def test_explicit_url_value_wins(
    monkeypatch: pytest.MonkeyPatch, query: str, expected: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "dev")
    assert connect_kwargs(BASE + query)["ssl"] == expected


def test_no_value_outside_local_still_requires_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    assert connect_kwargs(BASE)["ssl"] == "require"


def test_no_value_with_environment_unset_requires_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert connect_kwargs(BASE)["ssl"] == "require"


def test_no_value_on_local_prefers_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    assert connect_kwargs(BASE)["ssl"] == "prefer"
