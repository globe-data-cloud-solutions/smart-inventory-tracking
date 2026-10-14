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

    ISSUE is a direct On Hand deduction — ledger INSERTs with a negative quantity.
    No RESERVE transaction is created at any point. On Hand decreases
    immediately; the Reserved column is unaffected.
    CLAUDE.md §27: ISSUE must never create a RESERVE transaction or a transfer_orders row.

    A non-batch product posts a single ISSUE row. A batch-tracked product posts
    one ISSUE row per lot: the lots come from the dispatch engine (FEFO/FIFO/LIFO)
    or from body.lot_selections. A selection that differs from the engine's order
    is an override: FEFO needs dispatch:fefo_override (and a reason), FIFO/LIFO
    needs dispatch:lot_select at the warehouse. Both are resolved here and
    enforced in InventoryService.issue_stock().
    """
    svc = InventoryService(db)
    if not body.lot_selections:
        result = await svc.issue_stock(user, body)
        return SuccessResponse(data=result)

    from shared.permissions.middleware import check_permission

    tid = str(user.tenant_id)
    # A CONDITIONAL grant returns allowed=True; the FEFO reason rule covers it.
    can_fefo_override = (await check_permission(
        user, PERMISSIONS.DISPATCH_FEFO_OVERRIDE, {"tenant_id": tid}, db=db
    )).allowed
    can_lot_select = (await check_permission(
        user,
        PERMISSIONS.DISPATCH_LOT_SELECT,
        {"tenant_id": tid, "warehouse_id": str(body.warehouse_id)},
        db=db,
    )).allowed

    result = await svc.issue_stock(
        user, body, can_fefo_override=can_fefo_override, can_lot_select=can_lot_select
    )
    return SuccessResponse(data=result)
