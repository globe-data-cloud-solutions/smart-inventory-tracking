from contextlib import asynccontextmanager
from fastapi import FastAPI
from routers import products


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Product Service", version="1.0.0", lifespan=lifespan)
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "product"}
