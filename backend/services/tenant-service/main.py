import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers import adjustment_approval, billing, hierarchy, personnel_v2, positions, public_signup, self_approval, tenants, transfer_types, wizard


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Tenant Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
    )

app.include_router(public_signup.router,  prefix="/api/v1/tenants", tags=["public-signup"])
app.include_router(billing.router,        prefix="/api/v1/tenants", tags=["billing"])
app.include_router(tenants.router,        prefix="/api/v1/tenants", tags=["tenants"])
app.include_router(wizard.router,         prefix="/api/v1/tenants", tags=["wizard"])
app.include_router(hierarchy.router,      prefix="/api/v1/tenants", tags=["hierarchy"])
app.include_router(positions.router,      prefix="/api/v1/tenants", tags=["positions"])
app.include_router(personnel_v2.router,   prefix="/api/v1/tenants", tags=["personnel"])
app.include_router(transfer_types.router, prefix="/api/v1/tenants", tags=["transfer-types"])
app.include_router(self_approval.router,      prefix="/api/v1/tenants", tags=["self-approval"])
app.include_router(adjustment_approval.router, prefix="/api/v1/tenants", tags=["adjustment-approval"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "tenant"}
