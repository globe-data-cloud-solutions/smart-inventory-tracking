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


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/token", response_model=TokenResponse)
async def exchange_token(body: TokenRequest) -> TokenResponse:
    """Exchange a Cognito IdToken for a SMART JWT with tenant + role claims."""
    from datetime import datetime, timedelta, timezone

    # In production: validate Cognito token against JWKS, look up user in DB
    # For scaffold: return a minimal signed token
    payload = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "role": "WM",
        "tenant_id": "10000000-0000-0000-0000-000000000001",
        "region_id": None,
        "warehouse_id": "20000000-0000-0000-0000-000000000001",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE)).timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenResponse(access_token=token, expires_in=JWT_EXPIRE * 60)


@router.post("/refresh")
async def refresh_token() -> dict:
    return {"message": "use Cognito refresh flow"}
