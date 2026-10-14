from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session
from dependencies import get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import (
    AdjustmentApprovalInfoResponse,
    AdjustmentListItem,
    AdjustmentRequest,
    AdjustmentResponse,
)
from services.inventory_service import InventoryService

router = APIRouter()


@router.get("/", response_model=SuccessResponse[List[AdjustmentListItem]])
@require_permission(PERMISSIONS.ADJUSTMENT_LIST)
async def list_adjustments(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[AdjustmentListItem]]:
    svc = InventoryService(db)
    result = await svc.list_adjustments(user, page=page, limit=limit)
    return SuccessResponse(data=result)


@router.post("/", status_code=201, response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_CREATE)
async def create_adjustment(
    body: AdjustmentRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.create_adjustment(user, body)
    return SuccessResponse(data=result)


@router.post("/{adjustment_id}/submit", response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_SUBMIT)
async def submit_adjustment(
    adjustment_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.transition_adjustment(user, adjustment_id, "PENDING_APPROVAL")
    return SuccessResponse(data=result)


@router.get("/{adjustment_id}/approval-info", response_model=SuccessResponse[AdjustmentApprovalInfoResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_VIEW)
async def get_adjustment_approval_info(
    adjustment_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentApprovalInfoResponse]:
    svc = InventoryService(db)
    result = await svc.get_adjustment_approval_info(user, adjustment_id)
    return SuccessResponse(data=result)


@router.post("/{adjustment_id}/reject", response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_REJECT)
async def reject_adjustment(
    adjustment_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.transition_adjustment(user, adjustment_id, "REJECTED")
    return SuccessResponse(data=result)


@router.post("/{adjustment_id}/cancel", response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_CANCEL)
async def cancel_adjustment(
    adjustment_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    svc = InventoryService(db)
    result = await svc.transition_adjustment(user, adjustment_id, "CANCELLED")
    return SuccessResponse(data=result)


@router.post("/{adjustment_id}/approve", response_model=SuccessResponse[AdjustmentResponse])
@require_permission(PERMISSIONS.ADJUSTMENT_APPROVE)
async def approve_adjustment(
    adjustment_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[AdjustmentResponse]:
    from sqlalchemy import text as _text
    from schemas.inventory import AdjustStockRequest
    from decimal import Decimal as _Decimal

    svc = InventoryService(db)

    # Load adjustment data from DB before advancing state
    row = (await db.execute(
        _text("SELECT status, product_id, warehouse_id, quantity_delta, reason_code "
              "FROM adjustment_orders WHERE id = :id AND tenant_id = :tid"),
        {"id": str(adjustment_id), "tid": str(user.tenant_id)},
    )).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Adjustment not found")

    # If DRAFT, auto-advance to PENDING_APPROVAL first (single-approver shortcut)
    if row.status == "DRAFT":
        await svc.transition_adjustment(user, adjustment_id, "PENDING_APPROVAL")

    # PENDING_APPROVAL → APPROVED (pure status change)
    await svc.transition_adjustment(user, adjustment_id, "APPROVED")

    # APPROVED → POSTED + ledger entry via AdjustStockRequest
    adj_body = AdjustStockRequest(
        product_id=row.product_id,
        warehouse_id=row.warehouse_id,
        quantity=_Decimal(str(row.quantity_delta)),
        reason_code=row.reason_code,
        idempotency_key=f"adj:{adjustment_id}:post",
    )
    result = await svc.approve_adjustment(user, adjustment_id, adj_body)
    return SuccessResponse(data=result)
