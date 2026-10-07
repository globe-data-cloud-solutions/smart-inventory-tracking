from contextlib import asynccontextmanager
from fastapi import FastAPI
from routers import orders
from shared.utils.env_guard import assert_safe_environment


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART Order Service", version="1.0.0", lifespan=lifespan)
app.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "order"}
