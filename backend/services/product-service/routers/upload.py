"""Upload endpoints for product images and tenant branding.

POST /api/v1/upload/product-image  → product:upload_image (TA, NM)
POST /api/v1/upload/tenant-logo    → tenant:upload_branding (TA)
POST /api/v1/upload/tenant-banner  → tenant:upload_branding (TA)

Files are saved by LocalStorageService (uploads/ on disk, served as /static/uploads/).
In production swap LocalStorageService for S3StorageService — same interface.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.storage import LocalStorageService
from shared.utils.responses import SuccessResponse

router = APIRouter()

_storage = LocalStorageService()

_ACCEPTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_PRODUCT_IMAGE_BYTES = 2 * 1024 * 1024   # 2 MB
_MAX_LOGO_BYTES          = 1 * 1024 * 1024   # 1 MB
_MAX_BANNER_BYTES        = 3 * 1024 * 1024   # 3 MB


def _validate_image(file: UploadFile, max_bytes: int) -> None:
    if file.content_type not in _ACCEPTED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_IMAGE_TYPE", "message": "Only JPG, PNG, WebP accepted"},
        )
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=422,
            detail={"code": "IMAGE_TOO_LARGE", "message": f"File must be under {max_bytes // (1024*1024)} MB"},
        )


@router.post("/product-image", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.PRODUCT_UPLOAD_IMAGE)
async def upload_product_image(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    _validate_image(file, _MAX_PRODUCT_IMAGE_BYTES)
    data = await file.read()
    if len(data) > _MAX_PRODUCT_IMAGE_BYTES:
        raise HTTPException(
            status_code=422,
            detail={"code": "IMAGE_TOO_LARGE", "message": "Image must be under 2 MB"},
        )
    url = await _storage.save(
        file_bytes=data,
        filename=file.filename or "product.jpg",
        content_type=file.content_type or "image/jpeg",
        folder="products",
    )
    return SuccessResponse(data={"url": url})


@router.post("/tenant-logo", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_UPLOAD_BRANDING)
async def upload_tenant_logo(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    _validate_image(file, _MAX_LOGO_BYTES)
    data = await file.read()
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=422,
            detail={"code": "IMAGE_TOO_LARGE", "message": "Logo must be under 1 MB"},
        )
    url = await _storage.save(
        file_bytes=data,
        filename=file.filename or "logo.png",
        content_type=file.content_type or "image/png",
        folder="tenants/logos",
    )
    # Persist to tenant row immediately
    await db.execute(
        text("UPDATE tenants SET logo_url = :url, updated_at = NOW() WHERE id = :tid"),
        {"url": url, "tid": str(user.tenant_id)},
    )
    return SuccessResponse(data={"url": url})


@router.post("/tenant-banner", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.TENANT_UPLOAD_BRANDING)
async def upload_tenant_banner(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    _validate_image(file, _MAX_BANNER_BYTES)
    data = await file.read()
    if len(data) > _MAX_BANNER_BYTES:
        raise HTTPException(
            status_code=422,
            detail={"code": "IMAGE_TOO_LARGE", "message": "Banner must be under 3 MB"},
        )
    url = await _storage.save(
        file_bytes=data,
        filename=file.filename or "banner.jpg",
        content_type=file.content_type or "image/jpeg",
        folder="tenants/banners",
    )
    await db.execute(
        text("UPDATE tenants SET banner_url = :url, updated_at = NOW() WHERE id = :tid"),
        {"url": url, "tid": str(user.tenant_id)},
    )
    return SuccessResponse(data={"url": url})
