"""Notification Service — alert delivery via Celery outbox workers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers import notifications
from shared.outbox.worker import register_handler
from shared.outbox.schemas import InventoryUpdatedPayload
from shared.utils.env_guard import assert_safe_environment


@register_handler("InventoryUpdated")
async def handle_inventory_updated(payload: InventoryUpdatedPayload, tenant_id: str) -> None:
    """Example: check reorder points, fire low-stock alert if needed."""
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART Notification Service", version="1.0.0", lifespan=lifespan)
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "notification"}
