import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.utils.responses import ErrorResponse, ErrorDetail
from routers import (
    adjust,
    alerts,
    analytics,
    audit_log,
    count,
    dispatch,
    issue,
    lot_settings,
    lots,
    receive,
    reports,
    sync,
    transfer,
    transfer_requests,
)
from shared.utils.env_guard import assert_safe_environment


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(
    title="SMART Inventory Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(alerts.router, prefix="/api/v1/inventory/alerts", tags=["alerts"])
app.include_router(audit_log.router, prefix="/api/v1/audit-log", tags=["audit-log"])
app.include_router(receive.router, prefix="/api/v1/inventory/receive", tags=["receive"])
app.include_router(sync.router, prefix="/api/v1/inventory/sync", tags=["sync"])
app.include_router(issue.router, prefix="/api/v1/inventory/issues", tags=["issue"])
app.include_router(transfer.router, prefix="/api/v1/inventory/transfers", tags=["transfer"])
app.include_router(adjust.router, prefix="/api/v1/inventory/adjustments", tags=["adjustment"])
app.include_router(count.router, prefix="/api/v1/inventory/counts", tags=["count"])
app.include_router(analytics.router, prefix="/api/v1/inventory/analytics", tags=["analytics"])
app.include_router(
    transfer_requests.router,
    prefix="/api/v1/inventory/transfer-requests",
    tags=["transfer-requests"],
)
app.include_router(lot_settings.router, prefix="/api/v1/inventory", tags=["lot-settings"])
app.include_router(lots.router, prefix="/api/v1/inventory/lots", tags=["lots"])
app.include_router(reports.router, prefix="/api/v1/inventory/reports", tags=["reports"])
app.include_router(dispatch.router, prefix="/api/v1/inventory/dispatch", tags=["dispatch"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(code="INTERNAL_ERROR", message=str(exc))
        ).model_dump(),
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory"}
