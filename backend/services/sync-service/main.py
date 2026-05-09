"""Sync Service — offline queue drain and conflict resolution."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.sync_service.routers import sync


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Sync Service", version="1.0.0", lifespan=lifespan)
app.include_router(sync.router, prefix="/api/v1/sync", tags=["sync"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "sync"}
