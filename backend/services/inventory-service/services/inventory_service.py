from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import AdjustmentAppliedPayload, InventoryUpdatedPayload
from shared.outbox.writer import write_to_outbox
from shared.utils.idempotency import DuplicateTransactionError, check_and_register_idempotency_key
from services.inventory_service.schemas.inventory import (
    AdjustmentRequest,
    AdjustmentResponse,
    CountSessionRequest,
    CountSessionResponse,
    ReceiveStockRequest,
    ReceiveStockResponse,
    TransferOrderRequest,
    TransferOrderResponse,
)
from services.inventory_service.services.state_machine import (
    ADJUSTMENT_TRANSITIONS,
    TRANSFER_TRANSITIONS,
    validate_transition,
)


class InventoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def receive(self, user: Any, body: ReceiveStockRequest) -> ReceiveStockResponse:
        tx_id = str(uuid.uuid4())
        today = date.today()

        await check_and_register_idempotency_key(self.db, body.idempotency_key, tx_id)

        # Pessimistic lock on balance row
        await self.db.execute(
            text(
                "SELECT id FROM inventory_balances "
                "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid "
                "FOR UPDATE"
            ),
            {
                "tid": str(user.tenant_id),
                "pid": str(body.product_id),
                "wid": str(body.warehouse_id),
            },
        )

        await self.db.execute(
            text(
                "INSERT INTO inventory_transactions "
                "(id, transaction_date, tenant_id, type, product_id, warehouse_id, "
                " quantity, unit_cost, lot_number, expiry_date, idempotency_key, "
                " source, created_by) "
                "VALUES (:id, :td, :tid, 'RECEIVE', :pid, :wid, :qty, :cost, "
                "        :lot, :exp, :ikey, :src, :uid)"
            ),
            {
                "id": tx_id,
                "td": today,
                "tid": str(user.tenant_id),
                "pid": str(body.product_id),
                "wid": str(body.warehouse_id),
                "qty": str(body.quantity),
                "cost": str(body.unit_cost) if body.unit_cost else None,
                "lot": body.lot_number,
                "exp": body.expiry_date,
                "ikey": body.idempotency_key,
                "src": body.source,
                "uid": str(user.user_id),
            },
        )

        # Upsert running balance
        await self.db.execute(
            text(
                "INSERT INTO inventory_balances (tenant_id, product_id, warehouse_id, quantity) "
                "VALUES (:tid, :pid, :wid, :qty) "
                "ON CONFLICT (tenant_id, product_id, warehouse_id) WHERE lot_number IS NULL "
                "DO UPDATE SET quantity = inventory_balances.quantity + EXCLUDED.quantity, "
                "             updated_at = now()"
            ),
            {
                "tid": str(user.tenant_id),
                "pid": str(body.product_id),
                "wid": str(body.warehouse_id),
                "qty": str(body.quantity),
            },
        )

        await write_to_outbox(
            self.db,
            str(user.tenant_id),
            "InventoryUpdated",
            InventoryUpdatedPayload(
                product_id=str(body.product_id),
                warehouse_id=str(body.warehouse_id),
                delta=float(body.quantity),
                transaction_id=tx_id,
            ),
        )

        from datetime import datetime, timezone
        return ReceiveStockResponse(
            transaction_id=UUID(tx_id),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
            created_at=datetime.now(timezone.utc),
        )

    async def create_transfer(
        self, user: Any, body: TransferOrderRequest
    ) -> TransferOrderResponse:
        transfer_id = uuid.uuid4()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text(
                "INSERT INTO transfer_orders "
                "(id, tenant_id, from_warehouse_id, to_warehouse_id, status, created_by) "
                "VALUES (:id, :tid, :from_wid, :to_wid, 'DRAFT', :uid)"
            ),
            {
                "id": str(transfer_id),
                "tid": str(user.tenant_id),
                "from_wid": str(body.from_warehouse_id),
                "to_wid": str(body.to_warehouse_id),
                "uid": str(user.user_id),
            },
        )

        return TransferOrderResponse(
            transfer_id=transfer_id,
            status="DRAFT",
            from_warehouse_id=body.from_warehouse_id,
            to_warehouse_id=body.to_warehouse_id,
            created_at=now,
        )

    async def transition_transfer(
        self, user: Any, transfer_id: UUID, next_state: str
    ) -> TransferOrderResponse:
        result = await self.db.execute(
            text("SELECT * FROM transfer_orders WHERE id = :id FOR UPDATE"),
            {"id": str(transfer_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Transfer not found")

        validate_transition(TRANSFER_TRANSITIONS, row.status, next_state)

        await self.db.execute(
            text("UPDATE transfer_orders SET status = :s, updated_at = now() WHERE id = :id"),
            {"s": next_state, "id": str(transfer_id)},
        )

        from datetime import datetime, timezone
        return TransferOrderResponse(
            transfer_id=transfer_id,
            status=next_state,
            from_warehouse_id=row.from_warehouse_id,
            to_warehouse_id=row.to_warehouse_id,
            created_at=datetime.now(timezone.utc),
        )

    async def get_transfer(self, user: Any, transfer_id: UUID) -> TransferOrderResponse:
        result = await self.db.execute(
            text("SELECT * FROM transfer_orders WHERE id = :id"),
            {"id": str(transfer_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Transfer not found")

        from datetime import datetime, timezone
        return TransferOrderResponse(
            transfer_id=transfer_id,
            status=row.status,
            from_warehouse_id=row.from_warehouse_id,
            to_warehouse_id=row.to_warehouse_id,
            created_at=datetime.now(timezone.utc),
        )

    async def create_adjustment(
        self, user: Any, body: AdjustmentRequest
    ) -> AdjustmentResponse:
        adj_id = uuid.uuid4()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text(
                "INSERT INTO adjustment_orders "
                "(id, tenant_id, warehouse_id, product_id, quantity_delta, "
                " reason_code, status, created_by) "
                "VALUES (:id, :tid, :wid, :pid, :delta, :reason, 'DRAFT', :uid)"
            ),
            {
                "id": str(adj_id),
                "tid": str(user.tenant_id),
                "wid": str(body.warehouse_id),
                "pid": str(body.product_id),
                "delta": str(body.quantity_delta),
                "reason": body.reason_code,
                "uid": str(user.user_id),
            },
        )

        return AdjustmentResponse(
            adjustment_id=adj_id,
            status="DRAFT",
            quantity_delta=body.quantity_delta,
            created_at=now,
        )

    async def transition_adjustment(
        self, user: Any, adjustment_id: UUID, next_state: str
    ) -> AdjustmentResponse:
        result = await self.db.execute(
            text("SELECT * FROM adjustment_orders WHERE id = :id FOR UPDATE"),
            {"id": str(adjustment_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Adjustment not found")

        validate_transition(ADJUSTMENT_TRANSITIONS, row.status, next_state)

        await self.db.execute(
            text("UPDATE adjustment_orders SET status = :s, updated_at = now() WHERE id = :id"),
            {"s": next_state, "id": str(adjustment_id)},
        )

        if next_state == "APPLIED":
            await write_to_outbox(
                self.db,
                str(user.tenant_id),
                "AdjustmentApplied",
                AdjustmentAppliedPayload(
                    adjustment_id=str(adjustment_id),
                    product_id=str(row.product_id),
                    warehouse_id=str(row.warehouse_id),
                    delta=float(row.quantity_delta),
                ),
            )

        from datetime import datetime, timezone
        return AdjustmentResponse(
            adjustment_id=adjustment_id,
            status=next_state,
            quantity_delta=Decimal(str(row.quantity_delta)),
            created_at=datetime.now(timezone.utc),
        )

    async def create_count_session(
        self, user: Any, body: CountSessionRequest
    ) -> CountSessionResponse:
        session_id = uuid.uuid4()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text(
                "INSERT INTO count_sessions "
                "(id, tenant_id, warehouse_id, status, created_by) "
                "VALUES (:id, :tid, :wid, 'OPEN', :uid)"
            ),
            {
                "id": str(session_id),
                "tid": str(user.tenant_id),
                "wid": str(body.warehouse_id),
                "uid": str(user.user_id),
            },
        )

        return CountSessionResponse(
            session_id=session_id,
            warehouse_id=body.warehouse_id,
            status="OPEN",
            created_at=now,
        )

    async def get_count_session(
        self, user: Any, session_id: UUID
    ) -> CountSessionResponse:
        result = await self.db.execute(
            text("SELECT * FROM count_sessions WHERE id = :id"),
            {"id": str(session_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Count session not found")

        from datetime import datetime, timezone
        return CountSessionResponse(
            session_id=session_id,
            warehouse_id=row.warehouse_id,
            status=row.status,
            created_at=datetime.now(timezone.utc),
        )
