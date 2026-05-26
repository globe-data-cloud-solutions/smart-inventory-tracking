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
    AdjustmentListItem,
    AdjustmentRequest,
    AdjustmentResponse,
    AdjustStockRequest,
    AdjustStockResponse,
    CountSessionRequest,
    CountSessionResponse,
    IssueStockRequest,
    IssueStockResponse,
    ReceiveStockRequest,
    ReceiveStockResponse,
    TransferLineItem,
    TransferListItem,
    TransferOrderRequest,
    TransferOrderResponse,
)
from services.state_machine import InvalidStateTransitionError, validate_transition
from shared.permissions.audit import audit_log

# Reason codes that always deduct stock — service forces negative quantity regardless of input sign
_FORCE_NEGATIVE_REASONS: frozenset[str] = frozenset({"DAMAGE", "EXPIRY", "SUPPLIER_RETURN"})


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

    async def issue_stock(self, user: Any, body: IssueStockRequest) -> IssueStockResponse:
        """Issue stock out of a warehouse — direct On Hand deduction, no reservation step.

        ISSUE is always a single ledger INSERT with a negative quantity.
        No RESERVE transaction is created at any point in the workflow.
        If quantity exceeds the tenant approval threshold, the caller must
        route through the adjustment approval workflow instead.
        """
        tx_id = await record_transaction(
            self.db,
            tenant_id=str(user.tenant_id),
            transaction_type="ISSUE",
            product_id=str(body.product_id),
            warehouse_id=str(body.warehouse_id),
            quantity=-abs(body.quantity),   # always a deduction
            performed_by=str(user.user_id),
            idempotency_key=body.idempotency_key,
        )

        from datetime import datetime, timezone
        return IssueStockResponse(
            transaction_id=UUID(tx_id),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
            reason_code=body.reason_code,
            created_at=datetime.now(timezone.utc),
        )

    async def adjust(self, user: Any, body: AdjustStockRequest) -> AdjustStockResponse:
        """Apply a stock adjustment to a warehouse's on-hand balance.

        BUG 4A: DAMAGE and EXPIRY reason codes always produce a negative quantity
        (deduction) regardless of the sign supplied by the caller.
        BUG 7:  record_transaction() raises INSUFFICIENT_STOCK (HTTP 422) when the
        resulting balance would go below zero; callers with override_zero_floor=True
        have already confirmed the risk in the frontend — the ledger still enforces
        idempotency and outbox atomicity.
        """
        quantity = (
            -abs(body.quantity)
            if body.reason_code in _FORCE_NEGATIVE_REASONS
            else body.quantity
        )

        tx_id = await record_transaction(
            self.db,
            tenant_id=str(user.tenant_id),
            transaction_type="ADJUSTMENT",
            product_id=str(body.product_id),
            warehouse_id=str(body.warehouse_id),
            quantity=quantity,
            performed_by=str(user.user_id),
            idempotency_key=body.idempotency_key,
        )

        await audit_log(
            user=user,
            action="ADJUSTMENT",
            resource={
                "resource_type": "adjustment",
                "product_id": str(body.product_id),
                "warehouse_id": str(body.warehouse_id),
                "quantity": str(quantity),
                "reason_code": body.reason_code,
            },
            decision="GRANTED",
        )

        from datetime import datetime, timezone
        return AdjustStockResponse(
            transaction_id=UUID(tx_id),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=quantity,
            reason_code=body.reason_code,
            created_at=datetime.now(timezone.utc),
        )

    async def approve_adjustment(
        self, user: Any, adjustment_id: UUID, body: AdjustStockRequest
    ) -> AdjustStockResponse:
        """Approve a SUBMITTED adjustment — posts the ledger entry and updates on-hand.

        BUG 9: manager approval must call record_transaction() with transaction_type=
        'ADJUSTMENT'.  A status-only UPDATE leaves on-hand unchanged.
        """
        tx_id = await record_transaction(
            self.db,
            tenant_id=str(user.tenant_id),
            transaction_type="ADJUSTMENT",
            product_id=str(body.product_id),
            warehouse_id=str(body.warehouse_id),
            quantity=body.quantity,
            performed_by=str(user.user_id),
            idempotency_key=body.idempotency_key,
            reference_id=str(adjustment_id),
        )

        from datetime import datetime, timezone
        return AdjustStockResponse(
            transaction_id=UUID(tx_id),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
            reason_code=body.reason_code,
            created_at=datetime.now(timezone.utc),
        )

    async def _get_factory_subtree(self, tenant_id: str, factory_node_id: str) -> set[str]:
        """Returns all organization_node IDs within the given factory's subtree.

        Traverses PRIMARY_REPORTS_TO relationships downward from the factory root.
        Used to validate that a source warehouse is within a factory-specific product's
        permitted sourcing scope.
        """
        rows = await self.db.execute(
            text("""
                WITH RECURSIVE subtree AS (
                    SELECT id AS node_id
                    FROM organization_node
                    WHERE id = :fid AND tenant_id = :tid
                    UNION ALL
                    SELECT h.from_node_id
                    FROM org_node_hierarchy h
                    INNER JOIN subtree s ON h.to_node_id = s.node_id
                    WHERE h.tenant_id = :tid
                      AND h.relationship_type = 'PRIMARY_REPORTS_TO'
                )
                SELECT node_id FROM subtree
            """),
            {"tid": tenant_id, "fid": factory_node_id},
        )
        return {str(r[0]) for r in rows.fetchall()}

    async def create_transfer(
        self, user: Any, body: TransferOrderRequest
    ) -> TransferOrderResponse:
        from fastapi import HTTPException

        # Validate factory-specific products before any INSERT.
        for line in body.lines:
            product_row = (await self.db.execute(
                text("SELECT sku, source_factory_id FROM products WHERE id = :pid AND tenant_id = :tid"),
                {"pid": str(line.product_id), "tid": str(user.tenant_id)},
            )).fetchone()

            if product_row and product_row.source_factory_id is not None:
                subtree = await self._get_factory_subtree(
                    str(user.tenant_id), str(product_row.source_factory_id)
                )
                if str(body.from_warehouse_id) not in subtree:
                    factory_row = (await self.db.execute(
                        text("SELECT name FROM organization_node WHERE id = :fid AND tenant_id = :tid"),
                        {"fid": str(product_row.source_factory_id), "tid": str(user.tenant_id)},
                    )).fetchone()
                    factory_name = factory_row.name if factory_row else str(product_row.source_factory_id)
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "INVALID_SOURCE_FACTORY",
                            "message": f"Product {product_row.sku} can only be sourced from {factory_name}",
                        },
                    )

        transfer_id = uuid.uuid4()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text(
                "INSERT INTO transfer_orders "
                "(id, tenant_id, from_warehouse_id, to_warehouse_id, transfer_type, status, created_by) "
                "VALUES (:id, :tid, :from_wid, :to_wid, :ttype, 'DRAFT', :uid)"
            ),
            {
                "id": str(transfer_id),
                "tid": str(user.tenant_id),
                "from_wid": str(body.from_warehouse_id),
                "to_wid": str(body.to_warehouse_id),
                "ttype": body.transfer_type,
                "uid": str(user.user_id),
            },
        )

        for line in body.lines:
            await self.db.execute(
                text(
                    "INSERT INTO transfer_order_lines "
                    "(id, transfer_order_id, tenant_id, product_id, quantity, lot_number) "
                    "VALUES (gen_random_uuid(), :xfer_id, :tid, :pid, :qty, :lot)"
                ),
                {
                    "xfer_id": str(transfer_id),
                    "tid": str(user.tenant_id),
                    "pid": str(line.product_id),
                    "qty": str(line.quantity),
                    "lot": getattr(line, "lot_number", None),
                },
            )

        return TransferOrderResponse(
            transfer_id=transfer_id,
            transfer_type=body.transfer_type,
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

        # APPROVED: reservation converts to a hard deduction — write TRANSFER_OUT per line.
        if next_state == "APPROVED":
            lines = (await self.db.execute(
                text(
                    "SELECT * FROM transfer_order_lines "
                    "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
                ),
                {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
            )).fetchall()
            for line in lines:
                await record_transaction(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    transaction_type="TRANSFER_OUT",
                    product_id=str(line.product_id),
                    warehouse_id=str(row.from_warehouse_id),
                    quantity=-Decimal(str(line.quantity)),
                    performed_by=str(user.user_id),
                    idempotency_key=f"transfer:{transfer_id}:approve:out:line:{line.id}",
                    reference_id=str(transfer_id),
                )

        # CANCELLED from APPROVED/ADVISED: compensate with RETURN to restore source on_hand.
        elif next_state == "CANCELLED" and row.status in ("APPROVED", "ADVISED"):
            lines = (await self.db.execute(
                text(
                    "SELECT * FROM transfer_order_lines "
                    "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
                ),
                {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
            )).fetchall()
            for line in lines:
                await record_transaction(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    transaction_type="RETURN",
                    product_id=str(line.product_id),
                    warehouse_id=str(row.from_warehouse_id),
                    quantity=Decimal(str(line.quantity)),
                    performed_by=str(user.user_id),
                    idempotency_key=f"transfer:{transfer_id}:cancel:restore:line:{line.id}",
                    reference_id=str(transfer_id),
                )

        await self.db.execute(
            text("UPDATE transfer_orders SET status = :s, updated_at = now() WHERE id = :id"),
            {"s": next_state, "id": str(transfer_id)},
        )

        from datetime import datetime, timezone
        return TransferOrderResponse(
            transfer_id=transfer_id,
            transfer_type=transfer_type,
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
            # Source on_hand was already deducted at APPROVED via TRANSFER_OUT ledger entry.
            # dispatch_transfer() only books in-transit at the destination via RESERVE so
            # the receiving warehouse can see committed inbound stock. RELEASE reverses
            # this booking when receive_transfer() is called.
            await record_transaction(
                self.db,
                tenant_id=str(user.tenant_id),
                transaction_type="RESERVE",
                product_id=str(line.product_id),
                warehouse_id=str(row.to_warehouse_id),
                quantity=Decimal(str(line.quantity)),   # positive: reserve at destination
                performed_by=str(user.user_id),
                idempotency_key=f"transfer:{transfer_id}:dispatch:reserve:line:{line.id}",
                reference_id=str(transfer_id),
            )

        await self.db.execute(
            text("UPDATE transfer_orders SET status = 'ISSUED', updated_at = now() WHERE id = :id"),
            {"id": str(transfer_id)},
        )

        from datetime import datetime, timezone
        return TransferOrderResponse(
            transfer_id=transfer_id,
            transfer_type=transfer_type,
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
            # Source on_hand was already deducted at APPROVED via TRANSFER_OUT — do not repeat.
            # Clear the in_transit_in booking written at dispatch time.
            await record_transaction(
                self.db,
                tenant_id=str(user.tenant_id),
                transaction_type="RELEASE",
                product_id=str(line.product_id),
                warehouse_id=str(row.to_warehouse_id),
                quantity=-Decimal(str(line.quantity)),  # negative: reverse the RESERVE
                performed_by=str(user.user_id),
                idempotency_key=f"transfer:{transfer_id}:receive:release:line:{line.id}",
                reference_id=str(transfer_id),
            )
            # Credit destination on_hand — stock has been physically received.
            await record_transaction(
                self.db,
                tenant_id=str(user.tenant_id),
                transaction_type="TRANSFER_IN",
                product_id=str(line.product_id),
                warehouse_id=str(row.to_warehouse_id),
                quantity=Decimal(str(line.quantity)),  # positive: credit to destination
                performed_by=str(user.user_id),
                idempotency_key=f"transfer:{transfer_id}:receive:in:line:{line.id}",
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
            transfer_type=transfer_type,
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
            transfer_type=row.transfer_type,
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

    async def list_transfers(
        self, user: Any, page: int = 1, limit: int = 50
    ) -> list[TransferListItem]:
        """List transfers scoped by role.

        WM: sees only transfers involving their assigned warehouse (source or destination).
        All other roles: see all transfers for the tenant.
        """
        offset = (page - 1) * limit
        params: dict = {"tid": str(user.tenant_id), "offset": offset, "limit": limit}

        wh_filter = ""
        if user.role == "WM" and user.warehouse_id:
            wh_filter = "AND (to_.from_warehouse_id = :wid OR to_.to_warehouse_id = :wid)"
            params["wid"] = str(user.warehouse_id)

        sql = text(f"""
            SELECT
                to_.id                 AS transfer_id,
                to_.transfer_type,
                to_.status,
                to_.from_warehouse_id,
                fw.name                AS from_warehouse_name,
                to_.to_warehouse_id,
                tw.name                AS to_warehouse_name,
                to_.created_by::text   AS created_by,
                to_.created_at,
                to_.updated_at
            FROM transfer_orders to_
            JOIN warehouses fw ON fw.id = to_.from_warehouse_id
            JOIN warehouses tw ON tw.id = to_.to_warehouse_id
            WHERE to_.tenant_id = :tid
              {wh_filter}
            ORDER BY to_.created_at DESC
            OFFSET :offset LIMIT :limit
        """)

        rows = (await self.db.execute(sql, params)).fetchall()
        results: list[TransferListItem] = []

        for r in rows:
            lines_sql = text("""
                SELECT
                    tol.product_id,
                    p.name               AS product_name,
                    p.sku,
                    tol.quantity,
                    COALESCE(p.unit, '') AS uom
                FROM transfer_order_lines tol
                JOIN products p ON p.id = tol.product_id
                WHERE tol.transfer_order_id = :xfer_id
            """)
            line_rows = (
                await self.db.execute(lines_sql, {"xfer_id": str(r.transfer_id)})
            ).fetchall()

            results.append(
                TransferListItem(
                    transfer_id=r.transfer_id,
                    transfer_type=r.transfer_type,
                    status=r.status,
                    from_warehouse_id=r.from_warehouse_id,
                    from_warehouse_name=r.from_warehouse_name,
                    to_warehouse_id=r.to_warehouse_id,
                    to_warehouse_name=r.to_warehouse_name,
                    created_by=str(r.created_by),
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    lines=[
                        TransferLineItem(
                            product_id=line.product_id,
                            product_name=line.product_name,
                            sku=line.sku,
                            quantity=Decimal(str(line.quantity)),
                            uom=line.uom,
                        )
                        for line in line_rows
                    ],
                )
            )

        return results

    async def list_adjustments(
        self, user: Any, page: int = 1, limit: int = 50
    ) -> list[AdjustmentListItem]:
        """List adjustment orders scoped by role.

        WM: sees only adjustments at their assigned warehouse.
        All other roles: see all adjustments for the tenant.
        """
        offset = (page - 1) * limit
        params: dict = {"tid": str(user.tenant_id), "offset": offset, "limit": limit}

        wh_filter = ""
        if user.role == "WM" and user.warehouse_id:
            wh_filter = "AND ao.warehouse_id = :wid"
            params["wid"] = str(user.warehouse_id)

        sql = text(f"""
            SELECT
                ao.id               AS adjustment_id,
                ao.product_id,
                p.name              AS product_name,
                p.sku,
                ao.warehouse_id,
                w.name              AS warehouse_name,
                ao.quantity_delta,
                ao.reason_code,
                ao.status,
                ao.created_by::text AS created_by,
                ao.created_at,
                ao.notes
            FROM adjustment_orders ao
            JOIN products   p ON p.id = ao.product_id
            JOIN warehouses w ON w.id = ao.warehouse_id
            WHERE ao.tenant_id = :tid
              {wh_filter}
            ORDER BY ao.created_at DESC
            OFFSET :offset LIMIT :limit
        """)

        rows = (await self.db.execute(sql, params)).fetchall()

        return [
            AdjustmentListItem(
                adjustment_id=r.adjustment_id,
                product_id=r.product_id,
                product_name=r.product_name,
                sku=r.sku,
                warehouse_id=r.warehouse_id,
                warehouse_name=r.warehouse_name,
                quantity_delta=Decimal(str(r.quantity_delta)),
                reason_code=r.reason_code,
                status=r.status,
                created_by=str(r.created_by),
                created_at=r.created_at,
                notes=r.notes,
            )
            for r in rows
        ]
