"""Analytics Service — AI pipeline, forecasting, reports. ALL queries use read replica."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers import forecasts, reports
from shared.utils.env_guard import assert_safe_environment


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART Analytics Service", version="1.0.0", lifespan=lifespan)
app.include_router(forecasts.router, prefix="/api/v1/analytics/forecasts", tags=["forecasts"])
app.include_router(reports.router,   prefix="/api/v1/analytics/reports",   tags=["reports"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "analytics"}
