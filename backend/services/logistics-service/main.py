from contextlib import asynccontextmanager
from fastapi import FastAPI
from services.logistics_service.routers import fleet


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Logistics Service", version="1.0.0", lifespan=lifespan)
app.include_router(fleet.router, prefix="/api/v1/logistics", tags=["logistics"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "logistics"}
