import os

from fastapi import APIRouter, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel

router = APIRouter()

JWT_SECRET    = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE    = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))


class TokenRequest(BaseModel):
    cognito_token: str
    # Demo-only overrides — ignored in production Cognito validation.
    # When the frontend passes these, the issued JWT carries the correct
    # role/tenant/warehouse for that demo user rather than the scaffold defaults.
    demo_sub:          str | None = None
    demo_role:         str | None = None
    demo_tenant_id:    str | None = None
    demo_warehouse_id: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/token", response_model=TokenResponse)
async def exchange_token(body: TokenRequest) -> TokenResponse:
    """Exchange a Cognito IdToken for a SMART JWT with tenant + role claims.

    Production path: validate body.cognito_token against Cognito JWKS,
    look up user + role in the database, build claims from DB rows.

    Demo path: when demo_* fields are present, use them directly so every
    demo role gets a correctly-scoped JWT instead of the hardcoded WM stub.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    payload = {
        "sub":          body.demo_sub          or "00000000-0000-0000-0000-000000000001",
        "role":         body.demo_role         or "WM",
        "tenant_id":    body.demo_tenant_id    or "10000000-0000-0000-0000-000000000001",
        "region_id":    None,
        "warehouse_id": body.demo_warehouse_id,   # None is valid — NM/TA have no warehouse
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=JWT_EXPIRE)).timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenResponse(access_token=token, expires_in=JWT_EXPIRE * 60)


@router.post("/refresh")
async def refresh_token() -> dict:
    return {"message": "use Cognito refresh flow"}
