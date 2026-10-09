import os

# assert_safe_environment() refuses to start a service with an unsafe production
# config. Rules (docs/claude/ci-cd.md §6):
#   a. ENVIRONMENT=local on ECS is always forbidden (password-optional dev_email
#      login shortcut must never run on a real deployment target).
#   b. ENVIRONMENT unset and not on ECS: exempt (unit tests / tooling).
#   c. On ECS, ENVIRONMENT must be one of dev | stage | prod.
#   d. For dev/stage/prod (or any ECS run):
#       - JWT secret (JWT_SECRET or JWT_SECRET_KEY), if set, must be >= 64 chars
#         and have >= 10 distinct characters.
#       - no RATE_LIMIT_* override env vars (local/test only, see ci-cd.md §6).
#       - JWT_EXPIRE_MINUTES (default "60") must be an int in [1, 60].
#   e. stage/prod additionally require EMAIL_DELIVERY_MODE=ses and a non-empty
#      EMAIL_FROM (log mode writes raw verify/reset tokens to logs; disabled
#      breaks verify/reset entirely).
# All problems found are collected and raised together in a single error.
# Secret values are never included in the error message.


def assert_safe_environment() -> None:
    env = os.environ.get("ENVIRONMENT", "")
    on_ecs = bool(os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
                  or os.environ.get("ECS_CONTAINER_METADATA_URI")
                  or os.environ.get("AWS_EXECUTION_ENV", "").startswith("AWS_ECS"))

    if env == "local":
        if on_ecs:
            raise RuntimeError(
                "FATAL: unsafe production config — refusing to start: "
                "ENVIRONMENT=local is forbidden on ECS"
            )
        return

    if env == "" and not on_ecs:
        return

    problems: list[str] = []

    if on_ecs and env not in ("dev", "stage", "prod"):
        problems.append(f"ENVIRONMENT must be one of dev|stage|prod on ECS, got {env!r}")

    jwt_secret = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY")
    if jwt_secret:
        if len(jwt_secret) < 64:
            problems.append("JWT_SECRET (or JWT_SECRET_KEY) must be at least 64 characters")
        if len(set(jwt_secret)) < 10:
            problems.append("JWT_SECRET (or JWT_SECRET_KEY) must have at least 10 distinct characters")

    rate_limit_keys = sorted(k for k in os.environ if k.startswith("RATE_LIMIT_"))
    if rate_limit_keys:
        problems.append(
            "RATE_LIMIT_* overrides are local/test only, found: " + ", ".join(rate_limit_keys)
        )

    expire_raw = os.environ.get("JWT_EXPIRE_MINUTES", "60")
    try:
        expire_minutes = int(expire_raw)
    except ValueError:
        problems.append(f"JWT_EXPIRE_MINUTES must be an integer, got {expire_raw!r}")
    else:
        if expire_minutes < 1 or expire_minutes > 60:
            problems.append(f"JWT_EXPIRE_MINUTES must be between 1 and 60, got {expire_minutes}")

    if env in ("stage", "prod"):
        if os.environ.get("EMAIL_DELIVERY_MODE") != "ses":
            problems.append(
                "EMAIL_DELIVERY_MODE must be 'ses' in stage/prod "
                "(log writes raw verify/reset tokens to logs; disabled breaks verify/reset)"
            )
        if not os.environ.get("EMAIL_FROM"):
            problems.append("EMAIL_FROM must be set in stage/prod")

    if problems:
        raise RuntimeError(
            "FATAL: unsafe production config — refusing to start: " + "; ".join(problems)
        )
