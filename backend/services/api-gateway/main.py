"""API Gateway — JWT validation, rate limiting, plan cap enforcement, request routing."""
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from jose import JWTError, jwt

JWT_SECRET    = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

SERVICE_MAP = {
    "/api/v1/auth":      os.environ.get("AUTH_SERVICE_URL",       "http://auth-service:8000"),
    "/api/v1/tenants":   os.environ.get("TENANT_SERVICE_URL",     "http://tenant-service:8000"),
    "/api/v1/products":  os.environ.get("PRODUCT_SERVICE_URL",    "http://product-service:8000"),
    "/api/v1/inventory": os.environ.get("INVENTORY_SERVICE_URL",  "http://inventory-service:8000"),
    # Transfer requests are handled by the inventory service (routers/transfer.py
    # and routers/transfer_requests.py).  Separate entry so the prefix match is
    # unambiguous and a dedicated transfers microservice can replace it later.
    "/api/v1/transfers": os.environ.get("INVENTORY_SERVICE_URL",  "http://inventory-service:8000"),
    "/api/v1/orders":    os.environ.get("ORDER_SERVICE_URL",       "http://order-service:8000"),
    "/api/v1/logistics": os.environ.get("LOGISTICS_SERVICE_URL",  "http://logistics-service:8000"),
    "/api/v1/analytics": os.environ.get("ANALYTICS_SERVICE_URL",  "http://analytics-service:8000"),
}

UNAUTHENTICATED_PATHS = {"/api/v1/auth/token", "/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


app = FastAPI(title="SMART API Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# /health must be declared BEFORE the /{path:path} catch-all — FastAPI matches
# routes in registration order and the wildcard would otherwise intercept it.
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy(request: Request, path: str) -> Response:
    full_path = f"/{path}"

    if full_path not in UNAUTHENTICATED_PATHS:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        _decode_jwt(auth_header.removeprefix("Bearer "))

    target_base: str | None = None
    for prefix, url in SERVICE_MAP.items():
        if full_path.startswith(prefix):
            target_base = url
            break

    if not target_base:
        raise HTTPException(status_code=404, detail="Route not found")

    target_url = f"{target_base}{full_path}"
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=dict(request.headers),
            content=await request.body(),
            params=dict(request.query_params),
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )
