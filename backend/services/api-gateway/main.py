"""API Gateway — JWT validation, rate limiting, plan cap enforcement, request routing."""
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from jose import JWTError, jwt
from shared.cache.token_revocation import is_token_revoked
from shared.utils.env_guard import assert_safe_environment

logger = logging.getLogger("api-gateway")

JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET (or JWT_SECRET_KEY) must be set — refusing to start with an "
        "empty signing secret."
    )
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

# Behind an ALB, request.client.host is the load balancer, not the caller —
# every user would otherwise share one rate-limit bucket. 0 (default, today's
# local behaviour) trusts the direct connection; n>0 reads the n-th entry from
# the RIGHT of the incoming X-Forwarded-For (the ALB appends the real client
# IP as the first hop, so counting from the right skips any hops it added).
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))

SERVICE_MAP = {
    "/api/v1/auth":      os.environ.get("AUTH_SERVICE_URL",       "http://auth-service:8000"),
    "/api/v1/tenants":   os.environ.get("TENANT_SERVICE_URL",     "http://tenant-service:8000"),
    "/api/v1/products":  os.environ.get("PRODUCT_SERVICE_URL",    "http://product-service:8000"),
    "/api/v1/upload":    os.environ.get("PRODUCT_SERVICE_URL",    "http://product-service:8000"),
    # Uploaded static files (images) — served by product-service StaticFiles mount.
    # No JWT required: <img> tags cannot send Authorization headers.
    "/static":           os.environ.get("PRODUCT_SERVICE_URL",    "http://product-service:8000"),
    # All inventory endpoints (transfers, adjustments, issues, counts, analytics)
    # are mounted under /api/v1/inventory/* on the inventory service.
    # Callers must use /api/v1/inventory/transfers (not /api/v1/transfers).
    "/api/v1/inventory": os.environ.get("INVENTORY_SERVICE_URL",  "http://inventory-service:8000"),
    # Audit log is served by inventory-service but exposed at /api/v1/audit-log
    # so callers don't need to know which service owns it.
    "/api/v1/audit-log": os.environ.get("INVENTORY_SERVICE_URL",  "http://inventory-service:8000"),
    "/api/v1/orders":    os.environ.get("ORDER_SERVICE_URL",       "http://order-service:8000"),
    "/api/v1/logistics": os.environ.get("LOGISTICS_SERVICE_URL",  "http://logistics-service:8000"),
    "/api/v1/analytics": os.environ.get("ANALYTICS_SERVICE_URL",  "http://analytics-service:8000"),
}

UNAUTHENTICATED_PATHS = {
    "/api/v1/auth/token",
    "/health",
    # Public sign-up (S4) — exact-match only, never a prefix.
    "/api/v1/tenants/public/packages",
    "/api/v1/tenants/public/signup",
    "/api/v1/tenants/public/contact",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/resend-verification",
    # Password reset (B2) — exact-match only, never a prefix.
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    # Public STUB payment webhook (S5) — no SMART JWT on a gateway callback.
    "/api/v1/tenants/public/payments/webhook/stub",
}


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    assert_safe_environment()
    yield


app = FastAPI(title="SMART API Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_client_ip(request: Request) -> str:
    """The real caller IP, trusted only to the configured proxy depth.
    Incoming X-Real-IP is never trusted (handled by the caller, which always
    overwrites it) — this only decides what to overwrite it WITH."""
    direct = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return direct
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    if len(hops) < TRUSTED_PROXY_HOPS:
        return direct
    return hops[-TRUSTED_PROXY_HOPS]


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

    if full_path not in UNAUTHENTICATED_PATHS and not full_path.startswith("/static/"):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        payload = _decode_jwt(auth_header.removeprefix("Bearer "))
        if await is_token_revoked(payload):
            raise HTTPException(status_code=401, detail="TOKEN_REVOKED")

    target_base: str | None = None
    for prefix, url in SERVICE_MAP.items():
        if full_path.startswith(prefix):
            target_base = url
            break

    if not target_base:
        raise HTTPException(status_code=404, detail="Route not found")

    matched_prefix = next((p for p in SERVICE_MAP.keys() if full_path.startswith(p)), "")
    target_url = f"{target_base}{full_path}"

    # X-Real-IP is the rate-limit key for public sign-up/verification endpoints
    # downstream — always set it from the actual connection, overwriting any
    # incoming value so a caller cannot spoof another IP's rate limit.
    proxied_headers = {k: v for k, v in request.headers.items() if k.lower() != "x-real-ip"}
    proxied_headers["X-Real-IP"] = _resolve_client_ip(request)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=proxied_headers,
                content=await request.body(),
                params=dict(request.query_params),
            )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        logger.warning(
            f"Upstream service for {matched_prefix} is unavailable: "
            f"{request.method} {full_path}"
        )
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": f"Upstream service for {matched_prefix} is unavailable",
                },
            },
        )
    except httpx.TimeoutException:
        logger.warning(
            f"Upstream service for {matched_prefix} timed out: "
            f"{request.method} {full_path}"
        )
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "error": {
                    "code": "UPSTREAM_TIMEOUT",
                    "message": f"Upstream service for {matched_prefix} timed out",
                },
            },
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )
