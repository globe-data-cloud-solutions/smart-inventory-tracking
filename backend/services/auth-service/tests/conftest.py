"""Auth-service test configuration.

Sets required env vars BEFORE any app module is imported.
sys.path manipulation is intentionally done per test-module (see test_auth.py)
to avoid shadowing other services' identically-named packages (services/, routers/).
"""

from __future__ import annotations

import os

os.environ["JWT_SECRET"] = "test-secret-for-unit-tests"
os.environ["JWT_SECRET_KEY"] = "test-secret-for-unit-tests"
os.environ["ENVIRONMENT"] = "local"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_EXPIRE_MINUTES"] = "60"
# redis.from_url() doesn't connect eagerly — this just satisfies the module-level
# os.environ["REDIS_URL"] read in shared.cache.redis_client. Tests never hit a real
# Redis server: get_redis_client is monkeypatched per-test (see test_auth.py).
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
