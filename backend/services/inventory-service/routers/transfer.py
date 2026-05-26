from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session
from dependencies import get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import TransferListItem, TransferOrderRequest, TransferOrderResponse, TransferTransitionRequest
from services.inventory_service import InventoryService

router = APIRouter()


@router.get("/", response_model=SuccessResponse[List[TransferListItem]])
@require_permission(PERMISSIONS.TRANSFER_LIST)
async def list_transfers(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TransferListItem]]:
    svc = InventoryService(db)
    result = await svc.list_transfers(user, page=page, limit=limit)
    return SuccessResponse(data=result)


@router.post("/", status_code=201, response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_CREATE)
async def create_transfer(
    body: TransferOrderRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    svc = InventoryService(db)
    result = await svc.create_transfer(user, body)
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/submit", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_SUBMIT)
async def submit_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    svc = InventoryService(db)
    result = await svc.transition_transfer(user, transfer_id, "SUBMITTED")
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/approve", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_APPROVE)
async def approve_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    svc = InventoryService(db)
    result = await svc.transition_transfer(user, transfer_id, "APPROVED")
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/dispatch", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_DISPATCH)
async def dispatch_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Advance APPROVED → ISSUED. Source warehouse only (warehouse_id ABAC).
    Books a RESERVE at the destination warehouse so in_transit_in is visible.
    Source on_hand was already deducted at APPROVED via TRANSFER_OUT — no second deduction here.
    """
    svc = InventoryService(db)
    result = await svc.dispatch_transfer(user, transfer_id)
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/receive", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_RECEIVE)
async def receive_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Advance IN_TRANSIT → RECEIVED. Destination warehouse only (warehouse_id ABAC).
    Writes TRANSFER_IN ledger entries, credits destination balance, and fires
    StockTransferred outbox events — all in the same database transaction.
    """
    svc = InventoryService(db)
    result = await svc.receive_transfer(user, transfer_id)
    return SuccessResponse(data=result)


@router.patch("/{transfer_id}", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_VIEW)
async def transition_transfer(
    transfer_id: UUID,
    body: TransferTransitionRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Generic state transition — delegates to specialized methods for ledger-writing states.

    next_status == "ISSUED":   calls dispatch_transfer() — books RESERVE at destination.
    next_status == "RECEIVED": calls receive_transfer()  — books TRANSFER_IN at destination.
    All other statuses:        calls transition_transfer() — pure status update.
    """
    svc = InventoryService(db)
    if body.next_status == "ISSUED":
        result = await svc.dispatch_transfer(user, transfer_id)
    elif body.next_status == "RECEIVED":
        result = await svc.receive_transfer(user, transfer_id)
    else:
        result = await svc.transition_transfer(user, transfer_id, body.next_status)
    return SuccessResponse(data=result)


@router.get("/{transfer_id}", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_VIEW)
async def get_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    svc = InventoryService(db)
    result = await svc.get_transfer(user, transfer_id)
    return SuccessResponse(data=result)
