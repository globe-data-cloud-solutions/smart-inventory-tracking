"""D7: every API route on every service app carries @require_permission
(endpoint.__permission__) or is on the reviewed public allowlist.

ci_drift_check.py checks router source with ast; this checks the assembled
FastAPI apps, so a route added outside routers/ or wrapped in a way that drops
the marker is caught too. Each service is loaded in its own subprocess: the
services share top-level module names (main, routers, schemas, ...), so
importing two in one process would shadow each other.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# shared.db.session (pulled in by the permissions middleware) and the Celery
# app read these at import time; values are placeholders, nothing connects.
_FAKE_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://fake:fake@localhost:5432/fake",
    "DATABASE_READ_URL": "postgresql+asyncpg://fake:fake@localhost:5432/fake",
    "JWT_SECRET": "test-secret-for-route-gating",
    "JWT_SECRET_KEY": "test-secret-for-route-gating",
    "ENVIRONMENT": "local",
    "CELERY_BROKER_URL": "redis://localhost:6379/1",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
}
for _k, _v in _FAKE_ENV.items():
    os.environ.setdefault(_k, _v)

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from shared.permissions.tests.route_gating_allowlist import (
    ALLOWLIST,
    HEALTH_PATH,
)

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[3]
SERVICES = [
    "analytics", "auth", "inventory", "logistics", "notification",
    "order", "product", "sync", "tenant",
]


def find_ungated(routes: list[dict]) -> list[str]:
    """routes: [{"methods": [...], "path": str, "gated": bool}] -> violations."""
    out: list[str] = []
    for r in routes:
        if r["gated"] or r["path"] == HEALTH_PATH:
            continue
        for method in sorted(r["methods"]):
            if method in ("HEAD", "OPTIONS"):
                continue
            if (method, r["path"]) not in ALLOWLIST:
                out.append(f"{method} {r['path']} ({r['endpoint']})")
    return out


def describe_app(app: FastAPI) -> list[dict]:
    return [
        {
            "methods": sorted(route.methods or ()),
            "path": route.path,
            "endpoint": f"{route.endpoint.__module__}.{route.endpoint.__name__}",
            "gated": hasattr(route.endpoint, "__permission__"),
        }
        for route in app.routes
        if isinstance(route, APIRoute)
    ]


_CHILD = r"""
import json, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from fastapi.routing import APIRoute
from main import app
print(json.dumps([
    {"methods": sorted(r.methods or ()), "path": r.path,
     "endpoint": f"{r.endpoint.__module__}.{r.endpoint.__name__}",
     "gated": hasattr(r.endpoint, "__permission__")}
    for r in app.routes if isinstance(r, APIRoute)
]))
"""


def _service_routes(service: str) -> list[dict]:
    root = BACKEND / "services" / f"{service}-service"
    env = {**_FAKE_ENV, **os.environ}
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(root), str(BACKEND)],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"{service}-service failed to import:\n{proc.stderr[-2000:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_walker_reports_ungated_route() -> None:
    from shared.permissions.middleware import require_permission
    from shared.permissions.registry import ALL_PERMISSIONS

    app = FastAPI()

    @app.get("/api/v1/leaky")
    async def leaky() -> dict:
        return {}

    @app.get("/api/v1/gated")
    @require_permission(ALL_PERMISSIONS[0])
    async def gated() -> dict:
        return {}

    @app.get(HEALTH_PATH)
    async def health() -> dict:
        return {}

    violations = find_ungated(describe_app(app))
    assert len(violations) == 1
    assert violations[0].startswith("GET /api/v1/leaky ")


@pytest.mark.parametrize("service", SERVICES)
def test_every_route_gated(service: str) -> None:
    routes = _service_routes(service)
    assert routes, f"{service}-service exposes no API routes"
    violations = find_ungated(routes)
    assert not violations, f"{service}-service ungated routes:\n" + "\n".join(violations)
