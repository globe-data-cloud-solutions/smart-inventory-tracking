"""Unit tests for shared.utils.env_guard.assert_safe_environment."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared.utils.env_guard import assert_safe_environment

GOOD_SECRET = "0123456789abcdef" * 4  # 64 chars, 22 distinct
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _clear_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI_V4", raising=False)
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI", raising=False)
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)
    monkeypatch.delenv("EMAIL_DELIVERY_MODE", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    for key in list(__import__("os").environ):
        if key.startswith("RATE_LIMIT_"):
            monkeypatch.delenv(key, raising=False)


def test_local_on_ecs_metadata_v4_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4")
    with pytest.raises(RuntimeError):
        assert_safe_environment()


def test_local_on_ecs_execution_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
    with pytest.raises(RuntimeError):
        assert_safe_environment()


def test_local_without_ecs_vars_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "local")
    assert_safe_environment()


def test_unset_environment_off_ecs_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert_safe_environment()


def test_dev_with_good_config_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "log")
    assert_safe_environment()


def test_short_jwt_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError, match="64 characters"):
        assert_safe_environment()


def test_repetitive_jwt_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    with pytest.raises(RuntimeError, match="distinct characters"):
        assert_safe_environment()


def test_rate_limit_override_raises_and_names_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("RATE_LIMIT_SIGNUP", "100/3600")
    with pytest.raises(RuntimeError, match="RATE_LIMIT_SIGNUP"):
        assert_safe_environment()


def test_jwt_expiry_over_60_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "61")
    with pytest.raises(RuntimeError, match="JWT_EXPIRE_MINUTES"):
        assert_safe_environment()


def test_jwt_expiry_non_integer_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "abc")
    with pytest.raises(RuntimeError, match="JWT_EXPIRE_MINUTES"):
        assert_safe_environment()


def test_stage_with_log_email_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "stage")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "log")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")
    with pytest.raises(RuntimeError, match="EMAIL_DELIVERY_MODE"):
        assert_safe_environment()


def test_prod_with_ses_and_empty_email_from_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "ses")
    monkeypatch.setenv("EMAIL_FROM", "")
    with pytest.raises(RuntimeError, match="EMAIL_FROM"):
        assert_safe_environment()


def test_prod_fully_good_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "ses")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@example.com")
    assert_safe_environment()


def test_on_ecs_with_unset_environment_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4")
    with pytest.raises(RuntimeError, match="ENVIRONMENT must be one of dev"):
        assert_safe_environment()


def test_multiple_problems_combined_in_one_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JWT_SECRET", "short")
    monkeypatch.setenv("RATE_LIMIT_SIGNUP", "1/1")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "480")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "log")
    with pytest.raises(RuntimeError) as exc_info:
        assert_safe_environment()
    msg = str(exc_info.value)
    assert "64 characters" in msg
    assert "RATE_LIMIT_SIGNUP" in msg
    assert "JWT_EXPIRE_MINUTES" in msg
    assert "EMAIL_DELIVERY_MODE" in msg
    assert "EMAIL_FROM" in msg


def test_jwt_secret_value_never_in_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_guard_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    secret = "s3cr3t-value-that-must-never-leak-into-logs-or-errors-anywhere12"
    monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "500")
    with pytest.raises(RuntimeError) as exc_info:
        assert_safe_environment()
    assert secret not in str(exc_info.value)


def test_main_module_unsafe_config_exits_1_with_fatal_on_stderr() -> None:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("RATE_LIMIT_"):
            del env[key]
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["ENVIRONMENT"] = "prod"
    env["JWT_SECRET"] = "short"
    env.pop("EMAIL_DELIVERY_MODE", None)
    env.pop("EMAIL_FROM", None)
    result = subprocess.run(
        [sys.executable, "-m", "shared.utils.env_guard"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "FATAL: unsafe production config" in result.stderr


def test_main_module_unset_environment_exits_0() -> None:
    env = dict(os.environ)
    env.pop("ENVIRONMENT", None)
    for key in list(env):
        if key.startswith("ECS_CONTAINER_METADATA_URI") or key.startswith("AWS_EXECUTION_ENV"):
            del env[key]
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-m", "shared.utils.env_guard"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
