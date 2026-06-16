from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routers import products, upload


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART Product Service", version="1.0.0", lifespan=lifespan)
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(upload.router,   prefix="/api/v1/upload",   tags=["upload"])

# Serve uploaded files from disk (LocalStorageService).
# In production this is replaced by S3 — remove this mount and point CDN to S3.
_uploads_dir = Path("uploads")
_uploads_dir.mkdir(exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "product"}
