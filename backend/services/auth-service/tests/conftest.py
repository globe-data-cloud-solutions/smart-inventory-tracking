"""Auth-service test configuration.

Sets required env vars BEFORE any app module is imported.
sys.path manipulation is intentionally done per test-module (see test_auth.py)
to avoid shadowing other services' identically-named packages (services/, routers/).
"""
from __future__ import annotations

import os

os.environ["JWT_SECRET"]          = "test-secret-for-unit-tests"
os.environ["JWT_SECRET_KEY"]      = "test-secret-for-unit-tests"
os.environ["ENVIRONMENT"]         = "local"
os.environ["JWT_ALGORITHM"]       = "HS256"
os.environ["JWT_EXPIRE_MINUTES"]  = "60"
