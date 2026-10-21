import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from routers import products, upload
from shared.storage import get_storage
from shared.utils.env_guard import assert_safe_environment


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART Product Service", version="1.0.0", lifespan=lifespan)
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(upload.router, prefix="/api/v1/upload", tags=["upload"])

# Serve uploaded files — disk (LocalStorageService) via StaticFiles, or S3
# (S3StorageService) via a proxy route. Both are public, matching the gateway's
# /static/ passthrough (see api-gateway/main.py UNAUTHENTICATED_PATHS).
if os.environ.get("STORAGE_BACKEND", "local") == "s3":
    _storage = get_storage()

    @app.get("/static/uploads/{path:path}")
    async def serve_upload(path: str) -> Response:
        if ".." in path or path.startswith("/"):
            return Response(status_code=400)
        result = await _storage.get(path)
        if result is None:
            return Response(status_code=404)
        content, content_type = result
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
else:
    _uploads_dir = Path("uploads")
    _uploads_dir.mkdir(exist_ok=True)
    app.mount("/static/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "product"}
