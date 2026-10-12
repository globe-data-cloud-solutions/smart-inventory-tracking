from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_read_db_session
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import FeatureFlagsResponse

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
