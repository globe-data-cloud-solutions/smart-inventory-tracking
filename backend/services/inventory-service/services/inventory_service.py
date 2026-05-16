from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import (
    AdjustmentAppliedPayload,
    StockTransferredPayload,
)
from shared.outbox.writer import write_to_outbox
from repositories.ledger_repo import record_transaction
from schemas.inventory import (
    AdjustmentRequest,
    AdjustmentResponse,
    CountSessionRequest,
    CountSessionResponse,
    ReceiveStockRequest,
    ReceiveStockResponse,
    TransferOrderRequest,
    TransferOrderResponse,
)
from services.state_machine import InvalidStateTransitionError, validate_transition


class InventoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def receive(self, user: Any, body: ReceiveStockRequest) -> ReceiveStockResponse:
        tx_id = await record_transaction(
            self.db,
            tenant_id=str(user.tenant_id),
            transaction_type="RECEIVE",
            product_id=str(body.product_id),
            warehouse_id=str(body.warehouse_id),
            quantity=body.quantity,
            performed_by=str(user.user_id),
            idempotency_key=body.idempotency_key,
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

        transfer_type = getattr(row, "transfer_type", "PULL")
        try:
            validate_transition(transfer_type, row.status, next_state)
        except InvalidStateTransitionError as exc:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_STATE_TRANSITION", "detail": str(exc)},
            ) from exc

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

    async def dispatch_transfer(self, user: Any, transfer_id: UUID) -> TransferOrderResponse:
        """Advance an APPROVED transfer to ISSUED.

        Writes a TRANSFER_OUT ledger entry for every line and deducts the source
        warehouse balance via record_transaction().  Only the source warehouse manager
        may dispatch — user.warehouse_id must equal transfer.from_warehouse_id.
        """
        result = await self.db.execute(
            text("SELECT * FROM transfer_orders WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
            {"id": str(transfer_id), "tid": str(user.tenant_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Transfer not found")

        # ABAC: caller must be the source warehouse — no warehouse_id means middle-layer
        # manager (RM/NM/LM) who has no facility assignment and must be denied.
        if not user.warehouse_id or str(user.warehouse_id) != str(row.from_warehouse_id):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="Only the source warehouse can dispatch this transfer",
            )

        transfer_type = getattr(row, "transfer_type", "PULL")
        try:
            validate_transition(transfer_type, row.status, "ISSUED")
        except InvalidStateTransitionError as exc:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_STATE_TRANSITION", "detail": str(exc)},
            ) from exc

        lines = (await self.db.execute(
            text(
                "SELECT * FROM transfer_order_lines "
                "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
            ),
            {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
        )).fetchall()

        for line in lines:
            ikey = f"transfer:{transfer_id}:dispatch:line:{line.id}"
            await record_transaction(
                self.db,
                tenant_id=str(user.tenant_id),
                transaction_type="TRANSFER_OUT",
                product_id=str(line.product_id),
                warehouse_id=str(row.from_warehouse_id),
                quantity=-Decimal(str(line.quantity)),  # negative: deduct from source
                performed_by=str(user.user_id),
                idempotency_key=ikey,
                reference_id=str(transfer_id),
            )

        await self.db.execute(
            text("UPDATE transfer_orders SET status = 'ISSUED', updated_at = now() WHERE id = :id"),
            {"id": str(transfer_id)},
        )

        from datetime import datetime, timezone
        return TransferOrderResponse(
            transfer_id=transfer_id,
            status="ISSUED",
            from_warehouse_id=row.from_warehouse_id,
            to_warehouse_id=row.to_warehouse_id,
            created_at=datetime.now(timezone.utc),
        )

    async def receive_transfer(self, user: Any, transfer_id: UUID) -> TransferOrderResponse:
        """Advance an IN_TRANSIT transfer to RECEIVED.

        Writes a TRANSFER_IN ledger entry for every line and credits the destination
        warehouse balance.  Only the destination warehouse manager may receive —
        user.warehouse_id must equal transfer.to_warehouse_id.

        Writes a StockTransferred outbox event per line in the same transaction.
        """
        result = await self.db.execute(
            text("SELECT * FROM transfer_orders WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
            {"id": str(transfer_id), "tid": str(user.tenant_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Transfer not found")

        # ABAC: caller must be the destination warehouse — no warehouse_id means
        # middle-layer manager (RM/NM/LM) who must be denied regardless of role.
        if not user.warehouse_id or str(user.warehouse_id) != str(row.to_warehouse_id):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="Only the destination warehouse can receive this transfer",
            )

        transfer_type = getattr(row, "transfer_type", "PULL")
        try:
            validate_transition(transfer_type, row.status, "RECEIVED")
        except InvalidStateTransitionError as exc:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_STATE_TRANSITION", "detail": str(exc)},
            ) from exc

        lines = (await self.db.execute(
            text(
                "SELECT * FROM transfer_order_lines "
                "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
            ),
            {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
        )).fetchall()

        for line in lines:
            ikey = f"transfer:{transfer_id}:receive:line:{line.id}"
            await record_transaction(
                self.db,
                tenant_id=str(user.tenant_id),
                transaction_type="TRANSFER_IN",
                product_id=str(line.product_id),
                warehouse_id=str(row.to_warehouse_id),
                quantity=Decimal(str(line.quantity)),  # positive: credit to destination
                performed_by=str(user.user_id),
                idempotency_key=ikey,
                reference_id=str(transfer_id),
            )

            # StockTransferred is an additional event beyond the InventoryUpdated
            # that record_transaction() already fired — both in the same transaction.
            await write_to_outbox(
                self.db,
                str(user.tenant_id),
                "StockTransferred",
                StockTransferredPayload(
                    from_warehouse_id=str(row.from_warehouse_id),
                    to_warehouse_id=str(row.to_warehouse_id),
                    product_id=str(line.product_id),
                    quantity=float(line.quantity),
                    transfer_order_id=str(transfer_id),
                ),
            )

        await self.db.execute(
            text("UPDATE transfer_orders SET status = 'RECEIVED', updated_at = now() WHERE id = :id"),
            {"id": str(transfer_id)},
        )

        from datetime import datetime, timezone
        return TransferOrderResponse(
            transfer_id=transfer_id,
            status="RECEIVED",
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

        try:
            validate_transition("ADJUSTMENT", row.status, next_state)
        except InvalidStateTransitionError as exc:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_STATE_TRANSITION", "detail": str(exc)},
            ) from exc

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
