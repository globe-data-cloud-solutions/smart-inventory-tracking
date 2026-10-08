"""Single source of the current terms-of-service version.

Read at call time (never cached at import time) so a runtime override of
TERMS_VERSION on the service start command takes effect for every request,
including signup validation and login's re-acceptance check.
"""
import os


def get_terms_version() -> str:
    return os.environ.get("TERMS_VERSION", "2026-10")
