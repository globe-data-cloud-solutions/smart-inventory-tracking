"""Sync Service — retired (RB-10).

The offline queue drain moved to inventory-service (POST /api/v1/inventory/sync/batch),
where it posts through the same service methods as the online screens. This service
no longer serves any route. Kept only until the AWS deployment is retired by Alex.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.utils.env_guard import assert_safe_environment


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART Sync Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "sync"}
