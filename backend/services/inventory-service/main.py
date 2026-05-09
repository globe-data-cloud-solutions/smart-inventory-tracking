from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.utils.responses import ErrorResponse, ErrorDetail
from routers import adjust, count, receive, transfer


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(
    title="SMART Inventory Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(receive.router,   prefix="/api/v1/inventory/receive",   tags=["receive"])
app.include_router(transfer.router,  prefix="/api/v1/inventory/transfers",  tags=["transfer"])
app.include_router(adjust.router,    prefix="/api/v1/inventory/adjustments",tags=["adjustment"])
app.include_router(count.router,     prefix="/api/v1/inventory/counts",     tags=["count"])


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
