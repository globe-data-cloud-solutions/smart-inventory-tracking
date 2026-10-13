from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session, get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import (
    FeatureFlagsResponse,
    LotSettingsRequest,
    LotSettingsResponse,
)
from services.lot_settings_service import update_lot_settings

router = APIRouter()

_TRUTHY = {"1", "true", "yes"}


def feature_lot_tracking_enabled() -> bool:
    return os.environ.get("FEATURE_LOT_TRACKING", "").strip().lower() in _TRUTHY


@router.get("/features", response_model=SuccessResponse[FeatureFlagsResponse])
@require_permission(PERMISSIONS.INVENTORY_VIEW_BALANCE)
async def get_features(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db_session),
) -> SuccessResponse[FeatureFlagsResponse]:
    return SuccessResponse(data=FeatureFlagsResponse(lot_tracking=feature_lot_tracking_enabled()))


@router.put(
    "/products/{product_id}/lot-settings",
    response_model=SuccessResponse[LotSettingsResponse],
)
@require_permission(PERMISSIONS.PRODUCT_UPDATE)
async def put_lot_settings(
    product_id: uuid.UUID,
    body: LotSettingsRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[LotSettingsResponse]:
    result = await update_lot_settings(
        db,
        tenant_id=str(user.tenant_id),
        product_id=str(product_id),
        user_id=str(user.user_id),
        role=user.role,
        feature_enabled=feature_lot_tracking_enabled(),
        batch_tracking=body.batch_tracking,
        expiry_tracking=body.expiry_tracking,
        dispatch_strategy=body.dispatch_strategy,
    )
    return SuccessResponse(data=result)
