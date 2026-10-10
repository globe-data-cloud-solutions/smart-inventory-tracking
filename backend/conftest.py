import os
from unittest.mock import AsyncMock

import pytest

# backend/shared/db/session.py (and shared/cache/redis_client.py) read these
# env vars at IMPORT time, not at call time — any test module that transitively
# imports shared.db.session fails at collection if they are unset, even when
# the test itself never touches a real database or Redis connection.
# Obviously-fake localhost defaults let collection succeed; a real value from
# .env (or any other source) always wins since setdefault() never overwrites
# an already-set variable.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fake:fake@localhost:5432/fake")
os.environ.setdefault("DATABASE_READ_URL", "postgresql+asyncpg://fake:fake@localhost:5432/fake")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(autouse=True)
def _default_contract_stage_active(monkeypatch):
    """require_permission()'s READ_ONLY gate (shared/permissions/middleware.py)
    calls shared.billing.contract_stage.get_tenant_contract_stage() for every
    non-exempt write action, issuing its own db.execute() before a route's own
    handler logic runs. Pre-existing tests build their mock db's
    execute.side_effect as a fixed queue for the HANDLER's own queries only —
    an extra unplanned call shifts that queue and breaks them.

    Default every test to an ACTIVE tenant (no gate query hits the db) so this
    stays test-infrastructure plumbing; tests that want to exercise GRACE /
    EXPIRING / READ_ONLY behaviour patch get_tenant_contract_stage explicitly
    within their own `with patch(...)` block, which overrides this for its
    duration.
    """
    import shared.billing.contract_stage as contract_stage

    monkeypatch.setattr(
        contract_stage,
        "get_tenant_contract_stage",
        AsyncMock(return_value={
            "stage": "ACTIVE", "contract_end": None, "read_only_since": None,
        }),
    )
