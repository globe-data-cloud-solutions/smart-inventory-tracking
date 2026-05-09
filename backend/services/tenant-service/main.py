from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import tenants, wizard


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Tenant Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(tenants.router, prefix="/api/v1/tenants", tags=["tenants"])
app.include_router(wizard.router,  prefix="/api/v1/tenants", tags=["wizard"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "tenant"}
