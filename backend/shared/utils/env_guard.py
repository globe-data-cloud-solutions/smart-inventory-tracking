import os


def assert_safe_environment() -> None:
    """Refuse to start if ENVIRONMENT=local on AWS ECS (local enables the
    password-optional dev_email login shortcut in auth-service)."""
    env = os.environ.get("ENVIRONMENT", "")
    on_ecs = bool(os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
                  or os.environ.get("ECS_CONTAINER_METADATA_URI")
                  or os.environ.get("AWS_EXECUTION_ENV", "").startswith("AWS_ECS"))
    if env == "local" and on_ecs:
        raise RuntimeError("FATAL: ENVIRONMENT=local is forbidden on ECS — refusing to start")
