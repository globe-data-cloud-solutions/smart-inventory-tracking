from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session
from dependencies import get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import IssueStockRequest, IssueStockResponse
from services.inventory_service import InventoryService

router = APIRouter()


@router.post("/", status_code=201, response_model=SuccessResponse[IssueStockResponse])
@require_permission(PERMISSIONS.INVENTORY_ISSUE)
async def issue_stock(
    body: IssueStockRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[IssueStockResponse]:
    """Issue stock out of a warehouse.

    ISSUE is a direct On Hand deduction — a single ledger INSERT with a negative
    quantity. No RESERVE transaction is created at any point. On Hand decreases
    immediately; the Reserved column is unaffected.
    CLAUDE.md §27: ISSUE must never create a RESERVE transaction or a transfer_orders row.
    """
    svc = InventoryService(db)
    result = await svc.issue_stock(user, body)
    return SuccessResponse(data=result)
