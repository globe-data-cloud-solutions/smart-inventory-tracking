from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from dependencies import get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import TransferOrderRequest, TransferOrderResponse
from services.inventory_service import InventoryService

router = APIRouter()


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
    """Advance APPROVED → IN_TRANSIT. Source warehouse only (warehouse_id ABAC).
    Writes TRANSFER_OUT ledger entries and deducts source balance.
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
