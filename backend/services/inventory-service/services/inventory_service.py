from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import (
    AdjustmentAppliedPayload,
    AutoApprovalNoticePayload,
    StockTransferredPayload,
)
from shared.outbox.writer import write_to_outbox
from services.approval_service import resolve_approval, ROLE_AUTHORITY_LEVEL
from repositories.ledger_repo import record_transaction, write_transfer_ledger_entry
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


async def _get_simple_mode(session: AsyncSession, tenant_id: str) -> bool:
    """Read simple_mode from the tenant's approval_thresholds JSONB.

    Returns True when the column is absent, None, or the key is missing — safe default.
    simple_mode=True  → all tx types share one approval tier set.
    simple_mode=False → each tx type may have its own tier set (custom mode).
    """
    result = await session.execute(
        text("SELECT approval_thresholds FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )
    rules_json = result.scalar()
    return rules_json.get("simple_mode", True) if isinstance(rules_json, dict) else True


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
        """Post the ledger entry and advance adjustment to POSTED.

        Called by the approve endpoint after APPROVED transition succeeds.
        Calls record_transaction() — the only permitted path for balance mutations.
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
            reference_id=str(adjustment_id),
        )

        # APPROVED → POSTED (terminal state)
        await self.db.execute(
            text("UPDATE adjustment_orders SET status = 'POSTED', updated_at = now() WHERE id = :id"),
            {"id": str(adjustment_id)},
        )

        from datetime import datetime, timezone
        return AdjustmentResponse(
            adjustment_id=adjustment_id,
            status="POSTED",
            quantity_delta=quantity,
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
                "(id, tenant_id, from_warehouse_id, to_warehouse_id, transfer_type, status, "
                "created_by, created_by_authority_level) "
                "VALUES (:id, :tid, :from_wid, :to_wid, :ttype, 'DRAFT', :uid, :creator_level)"
            ),
            {
                "id": str(transfer_id),
                "tid": str(user.tenant_id),
                "from_wid": str(body.from_warehouse_id),
                "to_wid": str(body.to_warehouse_id),
                "ttype": body.transfer_type,
                "uid": str(user.user_id),
                "creator_level": ROLE_AUTHORITY_LEVEL.get(getattr(user, "role", "WM"), 4),
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

        _lines_query = text(
            "SELECT * FROM transfer_order_lines "
            "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
        )
        _lines_params = {"tid_order": str(transfer_id), "tid": str(user.tenant_id)}

        # PENDING_REVIEW: soft-lock source stock per line (RESERVE audit entry).
        if next_state == "PENDING_REVIEW":
            lines = (await self.db.execute(_lines_query, _lines_params)).fetchall()
            for line in lines:
                await write_transfer_ledger_entry(
                    session=self.db,
                    transfer_id=str(transfer_id),
                    transaction_type="RESERVE",
                    quantity=Decimal(str(line.quantity)),
                    warehouse_id=str(row.from_warehouse_id),
                    product_id=str(line.product_id),
                    tenant_id=str(user.tenant_id),
                    performed_by=str(user.user_id),
                    status_transition="DRAFT_TO_PENDING_REVIEW",
                    line_id=str(line.id),
                )

        # APPROVED: authority check → hard deduction per line → auto-approve notification.
        elif next_state == "APPROVED":
            lines = (await self.db.execute(
                text(
                    "SELECT * FROM transfer_order_lines "
                    "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
                ),
                {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
            )).fetchall()

            total_qty = sum(Decimal(str(l.quantity)) for l in lines)

            # Self-approval guard: fetch the creator's authority level stored at creation.
            creator_level: int | None = getattr(row, "created_by_authority_level", None)
            caller_level = ROLE_AUTHORITY_LEVEL.get(getattr(user, "role", ""), 5)

            # Belt-and-suspenders: if the caller IS the creator, reject immediately.
            if (
                getattr(row, "created_by", None) is not None
                and str(getattr(row, "created_by", "")) == str(user.user_id)
            ):
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code":    "CANNOT_APPROVE_OWN_TRANSFER",
                        "message": "You cannot approve a transfer you created.",
                    },
                )

            simple_mode = await _get_simple_mode(self.db, str(user.tenant_id))
            decision = await resolve_approval(
                self.db, str(user.tenant_id), transfer_type, total_qty,
                requester_authority_level=creator_level,
                simple_mode=simple_mode,
            )
            if caller_level > decision.required_authority_level:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code":          "INSUFFICIENT_APPROVAL_AUTHORITY",
                        "required":      decision.required_authority_level,
                        "required_role": decision.required_role_display,
                        "reason":        decision.reason,
                    },
                )

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

            # Notify higher authority levels when the band auto-approves (PROMPT 2B).
            if decision.is_auto_approved:
                for notify_level in decision.notify_levels:
                    await write_to_outbox(
                        self.db,
                        str(user.tenant_id),
                        "AutoApprovalNotice",
                        AutoApprovalNoticePayload(
                            transfer_id=str(transfer_id),
                            transaction_type=transfer_type,
                            quantity=float(total_qty),
                            notify_authority_level=notify_level,
                            approver_role=decision.required_role,
                            tenant_id=str(user.tenant_id),
                        ),
                    )

        # CANCELLED/REJECTED from pre-approval: release the soft-lock written at PENDING_REVIEW.
        elif next_state in ("CANCELLED", "REJECTED") and row.status in (
            "PENDING_REVIEW", "PENDING_APPROVAL"
        ):
            lines = (await self.db.execute(_lines_query, _lines_params)).fetchall()
            for line in lines:
                await write_transfer_ledger_entry(
                    session=self.db,
                    transfer_id=str(transfer_id),
                    transaction_type="RELEASE",
                    quantity=-Decimal(str(line.quantity)),
                    warehouse_id=str(row.from_warehouse_id),
                    product_id=str(line.product_id),
                    tenant_id=str(user.tenant_id),
                    performed_by=str(user.user_id),
                    status_transition="CANCELLED_PRE_APPROVAL",
                    line_id=str(line.id),
                )

        # CANCELLED from APPROVED/ADVISED: restore source on_hand (deducted at APPROVED).
        elif next_state == "CANCELLED" and row.status in ("APPROVED", "ADVISED"):
            lines = (await self.db.execute(_lines_query, _lines_params)).fetchall()
            for line in lines:
                await write_transfer_ledger_entry(
                    session=self.db,
                    transfer_id=str(transfer_id),
                    transaction_type="TRANSFER_REVERSAL",
                    quantity=Decimal(str(line.quantity)),
                    warehouse_id=str(row.from_warehouse_id),
                    product_id=str(line.product_id),
                    tenant_id=str(user.tenant_id),
                    performed_by=str(user.user_id),
                    status_transition="APPROVED_TO_CANCELLED",
                    line_id=str(line.id),
                )

        # IN_TRANSIT: confirm source dispatch + record destination inbound.
        elif next_state == "IN_TRANSIT":
            lines = (await self.db.execute(_lines_query, _lines_params)).fetchall()
            for line in lines:
                await write_transfer_ledger_entry(
                    session=self.db,
                    transfer_id=str(transfer_id),
                    transaction_type="TRANSIT_OUT",
                    quantity=Decimal(str(line.quantity)),
                    warehouse_id=str(row.from_warehouse_id),
                    product_id=str(line.product_id),
                    tenant_id=str(user.tenant_id),
                    performed_by=str(user.user_id),
                    status_transition="ISSUED_TO_IN_TRANSIT",
                    line_id=str(line.id),
                )
                await write_transfer_ledger_entry(
                    session=self.db,
                    transfer_id=str(transfer_id),
                    transaction_type="TRANSIT_IN",
                    quantity=Decimal(str(line.quantity)),
                    warehouse_id=str(row.to_warehouse_id),
                    product_id=str(line.product_id),
                    tenant_id=str(user.tenant_id),
                    performed_by=str(user.user_id),
                    status_transition="ISSUED_TO_IN_TRANSIT",
                    line_id=str(line.id),
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

        Source manager ABAC — allowed when either:
          (a) user.warehouse_id == transfer.from_warehouse_id (WM/RM/LM at source facility), OR
          (b) user has no warehouse_id AND role is NM/TA/SA (tenant-level authority, no single
              facility assignment — e.g. General Manager overseeing the source warehouse).
        Writes NO ledger entries — source on_hand was already deducted at APPROVED.
        """
        result = await self.db.execute(
            text("SELECT * FROM transfer_orders WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
            {"id": str(transfer_id), "tid": str(user.tenant_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Transfer not found")

        # ABAC: the caller must manage the source warehouse.
        # Facility-bound roles (WM/RM/LM) must have warehouse_id matching from_warehouse_id.
        # Tenant-level roles (NM/TA/SA) without a specific warehouse assignment have
        # organisation-wide authority and may dispatch from any source facility.
        _TENANT_LEVEL_ROLES = {"NM", "TA", "SA"}
        if user.warehouse_id:
            can_dispatch = str(user.warehouse_id).lower() == str(row.from_warehouse_id).lower()
        else:
            can_dispatch = getattr(user, "role", None) in _TENANT_LEVEL_ROLES
        if not can_dispatch:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="Only the source warehouse manager can dispatch this transfer",
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

        # Source on_hand was already deducted at APPROVED via TRANSFER_OUT.
        # Record physical dispatch in the audit ledger (does not affect on_hand again).
        for line in lines:
            await write_transfer_ledger_entry(
                session=self.db,
                transfer_id=str(transfer_id),
                transaction_type="TRANSIT_OUT",
                quantity=Decimal(str(line.quantity)),
                warehouse_id=str(row.from_warehouse_id),
                product_id=str(line.product_id),
                tenant_id=str(user.tenant_id),
                performed_by=str(user.user_id),
                status_transition="APPROVED_TO_ISSUED",
                line_id=str(line.id),
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

        # ABAC: caller must be the destination warehouse.
        # Three cases are permitted:
        #   (a) user.warehouse_id matches to_warehouse_id (facility-bound WM/RM),
        #   (b) tenant-level role without a warehouse assignment (NM/TA/SA),
        #   (c) the user created this transfer (RM who submitted the PULL without a
        #       specific warehouse assignment — they are the logical destination manager).
        _TENANT_LEVEL_ROLES = {"NM", "TA", "SA"}
        user_role = getattr(user, "role", None)
        if user.warehouse_id:
            can_receive = str(user.warehouse_id).lower() == str(row.to_warehouse_id).lower()
        elif user_role in _TENANT_LEVEL_ROLES:
            can_receive = True
        else:
            can_receive = str(getattr(user, "user_id", "")) == str(getattr(row, "created_by", "NONE"))
        if not can_receive:
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
            # Clear in-transit tracking at both source and destination.
            await write_transfer_ledger_entry(
                session=self.db,
                transfer_id=str(transfer_id),
                transaction_type="TRANSIT_CLEAR",
                quantity=-Decimal(str(line.quantity)),
                warehouse_id=str(row.from_warehouse_id),
                product_id=str(line.product_id),
                tenant_id=str(user.tenant_id),
                performed_by=str(user.user_id),
                status_transition="IN_TRANSIT_TO_RECEIVED",
                line_id=str(line.id),
            )
            await write_transfer_ledger_entry(
                session=self.db,
                transfer_id=str(transfer_id),
                transaction_type="TRANSIT_CLEAR",
                quantity=-Decimal(str(line.quantity)),
                warehouse_id=str(row.to_warehouse_id),
                product_id=str(line.product_id),
                tenant_id=str(user.tenant_id),
                performed_by=str(user.user_id),
                status_transition="IN_TRANSIT_TO_RECEIVED",
                line_id=f"{line.id}:dest",
            )
            # Credit destination on_hand — stock physically received.
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
                COALESCE(fw.name, fw_n.name) AS from_warehouse_name,
                to_.to_warehouse_id,
                COALESCE(tw.name, tw_n.name) AS to_warehouse_name,
                to_.created_by::text   AS created_by,
                to_.created_at,
                to_.updated_at
            FROM transfer_orders to_
            LEFT JOIN warehouses fw          ON fw.id       = to_.from_warehouse_id
            LEFT JOIN organization_node fw_n ON fw_n.id    = to_.from_warehouse_id
            LEFT JOIN warehouses tw          ON tw.id       = to_.to_warehouse_id
            LEFT JOIN organization_node tw_n ON tw_n.id    = to_.to_warehouse_id
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
                COALESCE(w.name, wn.name) AS warehouse_name,
                ao.quantity_delta,
                ao.reason_code,
                ao.status,
                ao.created_by::text AS created_by,
                ao.created_at,
                ao.notes
            FROM adjustment_orders ao
            JOIN products          p  ON p.id  = ao.product_id
            LEFT JOIN warehouses   w  ON w.id  = ao.warehouse_id
            LEFT JOIN organization_node wn ON wn.id = ao.warehouse_id
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
