"""Sync Service — offline queue drain and conflict resolution."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers import sync
from shared.utils.env_guard import assert_safe_environment


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART Sync Service", version="1.0.0", lifespan=lifespan)
app.include_router(sync.router, prefix="/api/v1/sync", tags=["sync"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "sync"}
