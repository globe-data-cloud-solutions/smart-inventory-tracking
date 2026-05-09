from __future__ import annotations

from decimal import Decimal
from typing import List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.inventory_service.schemas.inventory import LotSelection


class InsufficientStockError(Exception):
    def __init__(self, product_id: UUID, required: Decimal, available: Decimal) -> None:
        super().__init__(
            f"Insufficient stock for {product_id}: required={required}, available={available}"
        )
        self.product_id = product_id
        self.required = required
        self.available = available


async def resolve_strategy(
    db: AsyncSession,
    tenant_id: UUID,
    product_id: UUID,
    category_id: UUID | None,
    batch_tracking: bool,
    expiry_tracking: bool,
) -> str:
    # Auto-FEFO when both batch tracking AND expiry date are active
    if batch_tracking and expiry_tracking:
        return "FEFO"

    result = await db.execute(
        text(
            "SELECT strategy FROM dispatch_strategy_configs "
            "WHERE tenant_id = :tid AND scope = 'PRODUCT' AND scope_id = :sid LIMIT 1"
        ),
        {"tid": str(tenant_id), "sid": str(product_id)},
    )
    row = result.fetchone()
    if row:
        return row[0]

    if category_id:
        result = await db.execute(
            text(
                "SELECT strategy FROM dispatch_strategy_configs "
                "WHERE tenant_id = :tid AND scope = 'CATEGORY' AND scope_id = :sid LIMIT 1"
            ),
            {"tid": str(tenant_id), "sid": str(category_id)},
        )
        row = result.fetchone()
        if row:
            return row[0]

    return "FIFO"


async def select_lots(
    db: AsyncSession,
    tenant_id: UUID,
    product_id: UUID,
    warehouse_id: UUID,
    required_qty: Decimal,
    strategy: str,
) -> List[LotSelection]:
    result = await db.execute(
        text(
            "SELECT id, lot_number, expiry_date, received_at, quantity "
            "FROM inventory_balances "
            "WHERE tenant_id = :tid AND product_id = :pid "
            "AND warehouse_id = :wid AND quantity > 0"
        ),
        {"tid": str(tenant_id), "pid": str(product_id), "wid": str(warehouse_id)},
    )
    lots = result.fetchall()

    if strategy == "FEFO":
        lots = sorted(lots, key=lambda l: (l.expiry_date is None, l.expiry_date))
    elif strategy == "FIFO":
        lots = sorted(lots, key=lambda l: l.received_at if hasattr(l, "received_at") else 0)
    else:  # LIFO
        lots = sorted(
            lots,
            key=lambda l: l.received_at if hasattr(l, "received_at") else 0,
            reverse=True,
        )

    selections: List[LotSelection] = []
    remaining = required_qty

    for lot in lots:
        if remaining <= 0:
            break
        take = min(Decimal(str(lot.quantity)), remaining)
        selections.append(
            LotSelection(
                lot_id=lot.id,
                lot_number=lot.lot_number,
                quantity=take,
                strategy_applied=strategy,
            )
        )
        remaining -= take

    if remaining > 0:
        raise InsufficientStockError(product_id, required_qty, required_qty - remaining)

    return selections
