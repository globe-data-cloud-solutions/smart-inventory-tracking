from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import json as _json
from sqlalchemy import bindparam, text, types
from sqlalchemy.ext.asyncio import AsyncSession

from shared.outbox.schemas import (
    AdjustmentAppliedPayload,
    AutoApprovalNoticePayload,
    StockTransferredPayload,
)
from shared.outbox.writer import write_to_outbox
from services.approval_service import resolve_approval, ROLE_AUTHORITY_LEVEL
from services.self_approval_service import (
    check_adjustment_self_approval,
    check_product_override,
    get_self_approval_decision,
)
from repositories.ledger_repo import record_transaction, write_transfer_ledger_entry
from repositories.lot_repo import create_auto_lot, get_or_create_lot
from schemas.inventory import (
    AdjustmentApprovalInfoResponse,
    AdjustmentListItem,
    AdjustmentRequest,
    AdjustmentResponse,
    AdjustStockRequest,
    AdjustStockResponse,
    CountSessionRequest,
    CountSessionResponse,
    IssuedLot,
    IssueStockRequest,
    IssueStockResponse,
    ReceiveStockRequest,
    ReceiveStockResponse,
    ReceiveTransferRequest,
    TransferLineItem,
    TransferListItem,
    TransferLotAllocation,
    TransferOrderRequest,
    TransferOrderResponse,
)
from services import transfer_discrepancies, transfer_lots
from services.transfer_discrepancies import _FACILITY_SCOPED_ROLES, _inside, _subtree
from services.dispatch_service import (
    DispatchError,
    InsufficientStockError,
    allocate,
    load_candidate_lots,
    load_product,
    plan_allocation,
    record_override,
    resolve_strategy,
    validate_manual_selection,
)
from services.state_machine import InvalidStateTransitionError, validate_transition
from shared.permissions.audit import audit_log

# Reason codes that always deduct stock — service forces negative quantity regardless of input sign
_FORCE_NEGATIVE_REASONS: frozenset[str] = frozenset({"DAMAGE", "EXPIRY", "SUPPLIER_RETURN"})

# A subtree-scoped caller also sees a transfer whose approval chain names them:
# a step whose node_id is in their subtree, whose assigned_to_user_id is them,
# or whose all_holders lists them (approval_service.ResolvedStep.to_dict).
# The SQL (list_transfers) and _on_approval_steps (get_transfer) state the
# same rule — change them together. Non-array steps (NULL before
# PENDING_APPROVAL) match nothing.
_APPROVER_SCOPE_SQL = """EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(to_.resolved_approval_steps) = 'array'
                         THEN to_.resolved_approval_steps ELSE '[]'::jsonb END
                ) AS step
                WHERE lower(step->>'node_id') = ANY(:step_nodes)
                   OR lower(step->>'assigned_to_user_id') = :uid
                   OR EXISTS (
                       SELECT 1
                       FROM jsonb_array_elements(
                           CASE WHEN jsonb_typeof(step->'all_holders') = 'array'
                                THEN step->'all_holders' ELSE '[]'::jsonb END
                       ) AS holder
                       WHERE lower(holder->>'user_id') = :uid
                   )
              )"""


def _on_approval_steps(scope: set[str], user_id: Any, steps: Any) -> bool:
    """Python form of _APPROVER_SCOPE_SQL for one transfer's steps."""
    if isinstance(steps, str):
        try:
            steps = _json.loads(steps)
        except ValueError:
            return False
    if not isinstance(steps, list):
        return False
    uid = str(user_id).lower()
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("node_id") and str(step["node_id"]).lower() in scope:
            return True
        if step.get("assigned_to_user_id") and str(step["assigned_to_user_id"]).lower() == uid:
            return True
        holders = step.get("all_holders")
        if isinstance(holders, list) and any(
            isinstance(h, dict) and str(h.get("user_id", "")).lower() == uid for h in holders
        ):
            return True
    return False


async def _get_warehouse_name(db: Any, tenant_id: str, warehouse_id: str) -> str | None:
    """Resolve a facility's display name for audit logging (cosmetic — never raises)."""
    try:
        result = await db.execute(
            text(
                "SELECT COALESCE(w.name, n.name) AS name "
                "FROM (SELECT CAST(:wid AS uuid) AS id) x "
                "LEFT JOIN warehouses w ON w.id = x.id AND w.tenant_id = CAST(:tid AS uuid) "
                "LEFT JOIN organization_node n ON n.id = x.id AND n.tenant_id = CAST(:tid AS uuid)"
            ),
            {"wid": str(warehouse_id), "tid": str(tenant_id)},
        )
        row = result.fetchone()
        return row.name if row else None
    except Exception:
        # Cosmetic field — never let this break the transition
        return None


async def _resolve_product_override(
    db: Any,
    tenant_id: str,
    lines: Any,
    transaction_type: str,
    quantity: Decimal,
    total_value: Decimal,
) -> Optional[dict]:
    """Check each line's product for an active Design-B approval override.

    Returns the first override found (by line order), or None if no line's
    product has an active override that fires for this quantity/value.
    Takes precedence over self-approval and normal position routing — see
    check_product_override() in self_approval_service.py.
    """
    for line in lines:
        override = await check_product_override(
            session=db,
            tenant_id=tenant_id,
            product_id=str(line.product_id),
            transaction_type=transaction_type,
            quantity=quantity,
            total_value=total_value,
        )
        if override is not None:
            override = dict(override)
            override["product_id"] = str(line.product_id)
            return override
    return None


async def _apply_product_override_flag(
    db: Any,
    user: Any,
    resource_type: str,
    resource_id: Any,
    override: dict,
) -> None:
    """Set product_override_applied=TRUE and write the override audit log entry.

    resource_type is "transfer" or "adjustment" — selects the table updated
    and the audit action name (transfer:product_override_required /
    adjustment:product_override_required).
    """
    table = "transfer_orders" if resource_type == "transfer" else "adjustment_orders"
    await db.execute(
        text(
            f"UPDATE {table} SET product_override_applied = TRUE, updated_at = now() "
            f"WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": str(resource_id), "tid": str(user.tenant_id)},
    )

    product_row = (
        await db.execute(
            text("SELECT name FROM products WHERE id = :pid AND tenant_id = :tid"),
            {"pid": override["product_id"], "tid": str(user.tenant_id)},
        )
    ).fetchone()

    await audit_log(
        user=user,
        action=f"{resource_type}:product_override_required",
        resource={
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "product_id": override["product_id"],
            "product_name": product_row.name if product_row else None,
            "required_approver_position_id": override.get("approver_position_id"),
            "required_approver_title": override.get("approver_title"),
            "threshold_type": override.get("threshold_type"),
            "note": override.get("note"),
        },
        decision="CONDITIONAL",
        reason="product_override_required",
        db=db,
    )


async def _override_resolution_steps(
    session: AsyncSession,
    tenant_id: str,
    override: dict,
    creator_user_id: Optional[str] = None,
) -> list[dict]:
    """Build a single-step resolved_approval_steps list from a product override.

    Mirrors the shape produced by approval_service.ResolvedStep.to_dict() so
    _check_can_approve() routes correctly: caller must match
    assigned_to_user_id (sequential mode), or be escalated to TA if the
    position is vacant.

    If the configured approver position is vacant, OR its current holder IS
    the requester (a self-approval conflict — the override forces
    PENDING_APPROVAL but the only configured approver is the person who must
    not approve their own request), escalate up the reports_to chain from the
    override position via _escalate_vacant(), falling back to the tenant's TA
    if the chain is exhausted or also resolves back to the creator. This
    mirrors the self-approval escalation resolve_transfer_approvers() performs
    for normal (non-override) routing.
    """
    from services.approval_service import _escalate_vacant, _find_tenant_ta

    approver_user_id = override.get("approver_user_id")
    approver_name = override.get("approver_name")
    position_id = override.get("approver_position_id")
    escalated = False

    needs_escalation = approver_user_id is None or (
        creator_user_id is not None and str(approver_user_id) == str(creator_user_id)
    )
    if needs_escalation:
        approver_user_id, approver_name, escalated = await _escalate_vacant(
            session,
            tenant_id,
            position_id,
        )
        if not approver_user_id or (
            creator_user_id is not None and str(approver_user_id) == str(creator_user_id)
        ):
            approver_user_id, approver_name = await _find_tenant_ta(session, tenant_id)
            escalated = True

    is_vacant = approver_user_id is None
    return [
        {
            "sequence": 1,
            "position_title": override.get("approver_title") or "Designated Approver",
            "position_id": position_id,
            "node_id": None,
            "assigned_to_user_id": approver_user_id,
            "assigned_to_name": approver_name,
            "execution_mode": "sequential",
            "sla_hours": None,
            "is_vacant": is_vacant,
            "escalated": escalated,
            "status": "pending",
            "all_holders": [],
            "holder_count": 0 if is_vacant else 1,
        }
    ]


async def _check_can_approve(
    row: Any,
    user: Any,
    caller_level: int,
    decision: Any,  # resolve_approval() result — used for simple-mode fallback gate
) -> None:
    """Raise HTTP 403 if the user cannot approve this transfer.

    Priority order:
      1. Dynamic routing (resolved_approval_steps on the transfer):
         - ANY mode  : caller must be one of the listed all_holders
         - Sequential: caller must match assigned_to_user_id exactly
      2. No dynamic steps: fall back to simple-mode authority gate using the
         pre-computed decision (caller passes it to avoid a double DB round-trip).

    Self-approval is blocked by the caller before this function runs.
    """
    import json as _json
    from fastapi import HTTPException

    caller_uid = str(user.user_id)

    resolved_steps = getattr(row, "resolved_approval_steps", None)
    if resolved_steps:
        if isinstance(resolved_steps, str):
            resolved_steps = _json.loads(resolved_steps)
        steps: list = resolved_steps if isinstance(resolved_steps, list) else []
        if steps:
            cur_idx = max(0, (getattr(row, "current_approval_step", 1) or 1) - 1)
            cur_step = steps[cur_idx] if cur_idx < len(steps) else steps[-1]

            exec_mode = (cur_step.get("execution_mode") or "sequential").lower()
            assigned_uid = cur_step.get("assigned_to_user_id")
            all_holders = cur_step.get("all_holders") or []
            step_escalated = cur_step.get("escalated", False)

            # Escalated step override: when a step was escalated to TA because the
            # original assignee was the transfer creator (self-approval prevention),
            # any active TA for this tenant is allowed to approve — even if their
            # user_id differs from the stored assigned_to_user_id.
            if step_escalated:
                caller_role = getattr(user, "role", "")
                is_own = str(getattr(row, "created_by", "")) == caller_uid
                if caller_role == "TA" and not is_own:
                    return  # TA allowed on escalated steps

            if exec_mode == "any":
                # ANY mode: first eligible holder to approve wins.
                holder_uids = {str(h.get("user_id", "")) for h in all_holders}

                if not holder_uids:
                    # Dynamic routing is configured but no holder was stored.
                    # This means resolve_transfer_approvers() found no active
                    # person for the position (misconfigured rule, vacant position,
                    # or position not found in the hierarchy).
                    # Raise 422 rather than silently allowing anyone — a stuck
                    # transfer is safer than an incorrectly approved one.
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "NO_APPROVER_FOUND",
                            "message": (
                                f"No active holder found for "
                                f"'{cur_step.get('position_title', 'the designated approver')}' "
                                "in the approval chain. Contact your Tenant Admin to assign "
                                "someone to this position or update the approval rules."
                            ),
                            "position_title": cur_step.get("position_title"),
                        },
                    )

                if caller_uid not in holder_uids:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "NOT_ASSIGNED_APPROVER",
                            "message": (
                                f"Only an active '{cur_step.get('position_title', 'designated')}' "
                                "can approve this step."
                            ),
                            "position": cur_step.get("position_title"),
                        },
                    )
                return  # caller is a valid ANY-mode approver

            # Sequential / specific assignment
            if assigned_uid and caller_uid != str(assigned_uid):
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "NOT_ASSIGNED_APPROVER",
                        "message": (
                            f"This transfer is assigned to "
                            f"{cur_step.get('assigned_to_name', 'another approver')}. "
                            "You are not the assigned approver."
                        ),
                        "assigned_to": cur_step.get("assigned_to_name"),
                        "position": cur_step.get("position_title"),
                    },
                )
            return  # caller matches assigned approver (or no specific assignee)

    # No dynamic routing — simple-mode authority gate using pre-computed decision
    if caller_level > decision.required_authority_level:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_APPROVAL_AUTHORITY",
                "required": decision.required_authority_level,
                "required_role": decision.required_role_display,
                "reason": decision.reason,
            },
        )


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
        from datetime import date as _date, datetime, timezone
        from fastapi import HTTPException

        from schemas.inventory import ALLOWED_RECEIVE_SOURCES

        if body.source not in ALLOWED_RECEIVE_SOURCES:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_SOURCE", "source": body.source},
            )

        product_row = (
            await self.db.execute(
                text(
                    "SELECT batch_tracking, expiry_tracking FROM products "
                    "WHERE id = :pid AND tenant_id = :tid"
                ),
                {"pid": str(body.product_id), "tid": str(user.tenant_id)},
            )
        ).fetchone()
        if product_row is None:
            raise HTTPException(status_code=404, detail={"code": "PRODUCT_NOT_FOUND"})

        lot_id: Optional[str] = None
        lot_number = body.lot_number
        expiry_date = body.expiry_date

        if not product_row.batch_tracking:
            if lot_number or expiry_date or body.auto_lot:
                raise HTTPException(status_code=422, detail={"code": "LOT_NOT_TRACKED"})
        else:
            if lot_number and body.auto_lot:
                raise HTTPException(status_code=422, detail={"code": "LOT_INPUT_CONFLICT"})
            if not lot_number and not body.auto_lot:
                raise HTTPException(status_code=422, detail={"code": "LOT_NUMBER_REQUIRED"})

            if product_row.expiry_tracking and not expiry_date:
                raise HTTPException(status_code=422, detail={"code": "EXPIRY_REQUIRED"})
            if expiry_date is not None and expiry_date < _date.today():
                raise HTTPException(status_code=422, detail={"code": "EXPIRY_IN_PAST"})

            if body.auto_lot:
                lot_id, lot_number = await create_auto_lot(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    product_id=str(body.product_id),
                    expiry_date=expiry_date,
                    performed_by=str(user.user_id),
                )
            else:
                lot_id = await get_or_create_lot(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    product_id=str(body.product_id),
                    lot_number=lot_number,
                    expiry_date=expiry_date,
                    performed_by=str(user.user_id),
                )

        tx_id = await record_transaction(
            self.db,
            tenant_id=str(user.tenant_id),
            transaction_type="RECEIVE",
            product_id=str(body.product_id),
            warehouse_id=str(body.warehouse_id),
            quantity=body.quantity,
            performed_by=str(user.user_id),
            idempotency_key=body.idempotency_key,
            lot_id=lot_id,
            lot_number=lot_number,
            expiry_date=expiry_date,
            source=body.source,
            unit_cost=body.unit_cost,
        )

        return ReceiveStockResponse(
            transaction_id=UUID(tx_id),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
            created_at=datetime.now(timezone.utc),
            lot_id=UUID(lot_id) if lot_id else None,
            lot_number=lot_number,
            expiry_date=expiry_date,
            source=body.source,
        )

    async def _issued_rows(self, tenant_id: str, issue_ref: str) -> list[Any]:
        """ISSUE ledger rows already posted for this issue_ref, ordered by lot_id."""
        return list(
            (
                await self.db.execute(
                    text(
                        "SELECT id, lot_id, lot_number, expiry_date, quantity "
                        "FROM inventory_transactions "
                        "WHERE tenant_id = :tid AND type = 'ISSUE' AND reference_id = :ref "
                        "ORDER BY lot_id"
                    ),
                    {"tid": tenant_id, "ref": issue_ref},
                )
            ).fetchall()
        )

    async def _issue_replay(
        self, tenant_id: str, issue_ref: str, body: IssueStockRequest, rows: list[Any]
    ) -> IssueStockResponse:
        """The response of an Issue that was already posted — nothing is written."""
        from datetime import datetime, timezone

        override_row = (
            await self.db.execute(
                text(
                    "SELECT id FROM lot_allocation_overrides "
                    "WHERE tenant_id = :tid AND movement_type = 'ISSUE' AND reference_id = :ref "
                    "LIMIT 1"
                ),
                {"tid": tenant_id, "ref": issue_ref},
            )
        ).fetchone()
        lots = [
            IssuedLot(
                lot_id=r.lot_id,
                lot_number=r.lot_number,
                expiry_date=r.expiry_date,
                quantity=abs(Decimal(str(r.quantity))),
            )
            for r in rows
        ]
        return IssueStockResponse(
            transaction_id=UUID(str(rows[0].id)),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=sum((lot.quantity for lot in lots), Decimal("0")),
            reason_code=body.reason_code,
            created_at=datetime.now(timezone.utc),
            lots=lots,
            is_override=override_row is not None,
        )

    async def issue_stock(
        self,
        user: Any,
        body: IssueStockRequest,
        *,
        can_fefo_override: bool = False,
        can_lot_select: bool = False,
    ) -> IssueStockResponse:
        """Issue stock out of a warehouse — direct On Hand deduction, no reservation step.

        No RESERVE transaction is created at any point in the workflow.
        If quantity exceeds the tenant approval threshold, the caller must
        route through the adjustment approval workflow instead.

        Non-batch product: a single ISSUE ledger INSERT with a negative quantity,
        key = body.idempotency_key. lot_selections → 422 LOT_NOT_TRACKED. A
        replay (the key's ISSUE row already exists) returns that row and writes
        nothing.

        Batch product: one ISSUE row per lot, sorted by lot_id, key
        f"{body.idempotency_key}:lot:{lot_id}", all sharing reference_id =
        issue_ref (uuid5 of tenant + idempotency_key). The lots come from the
        dispatch engine (allocate) or from body.lot_selections. A selection that
        differs from the engine's order is an override: FEFO needs
        can_fefo_override (and a reason), FIFO/LIFO needs can_lot_select; it is
        logged in lot_allocation_overrides with movement_type="ISSUE". A replay
        (ISSUE rows already exist for issue_ref) returns those rows and writes
        nothing.

        Lock order is the same as record_transaction(): the product balance row
        first, then the lot_balances rows (ORDER BY lot_id).

        PERMISSIONS: the override flags are resolved by the router.
        """
        from datetime import datetime, timezone
        from fastapi import HTTPException

        tenant_id, user_id = str(user.tenant_id), str(user.user_id)
        product_id, warehouse_id = str(body.product_id), str(body.warehouse_id)
        qty = abs(body.quantity)

        product = await load_product(self.db, tenant_id, product_id)

        if not product.batch_tracking:
            if body.lot_selections:
                raise transfer_lots.http_from_engine(DispatchError("LOT_NOT_TRACKED"))
            try:
                tx_id = await record_transaction(
                    self.db,
                    tenant_id=tenant_id,
                    transaction_type="ISSUE",
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity=-qty,  # always a deduction
                    performed_by=user_id,
                    idempotency_key=body.idempotency_key,
                )
            except HTTPException as exc:
                # A replay (same key resent) returns the original ISSUE row, as
                # a batch replay does. A key used by anything else stays a 409.
                if exc.status_code != 409:
                    raise
                original = (
                    await self.db.execute(
                        text(
                            "SELECT id, quantity FROM inventory_transactions "
                            "WHERE tenant_id = :tid AND type = 'ISSUE' AND idempotency_key = :key"
                        ),
                        {"tid": tenant_id, "key": body.idempotency_key},
                    )
                ).fetchone()
                if original is None:
                    raise
                return IssueStockResponse(
                    transaction_id=UUID(str(original.id)),
                    product_id=body.product_id,
                    warehouse_id=body.warehouse_id,
                    quantity=abs(Decimal(str(original.quantity))),
                    reason_code=body.reason_code,
                    created_at=datetime.now(timezone.utc),
                )
            return IssueStockResponse(
                transaction_id=UUID(tx_id),
                product_id=body.product_id,
                warehouse_id=body.warehouse_id,
                quantity=body.quantity,
                reason_code=body.reason_code,
                created_at=datetime.now(timezone.utc),
            )

        # Stable per request: every lot row of this Issue carries it as reference_id.
        issue_ref = str(uuid.uuid5(uuid.NAMESPACE_URL, f"issue:{tenant_id}:{body.idempotency_key}"))

        # Replay check first — an Issue already posted is returned as it was.
        posted = await self._issued_rows(tenant_id, issue_ref)
        if posted:
            return await self._issue_replay(tenant_id, issue_ref, body, posted)

        # Same lock order as record_transaction(): balance row first, then lots.
        await self.db.execute(
            text(
                "SELECT id FROM inventory_balances "
                "WHERE tenant_id = :tid AND product_id = :pid AND warehouse_id = :wid FOR UPDATE"
            ),
            {"tid": tenant_id, "pid": product_id, "wid": warehouse_id},
        )

        # A concurrent request with the same key may have posted while this one
        # waited for the lock — look again before allocating a second time.
        posted = await self._issued_rows(tenant_id, issue_ref)
        if posted:
            return await self._issue_replay(tenant_id, issue_ref, body, posted)

        strategy, _ = resolve_strategy(
            product.batch_tracking, product.expiry_tracking, product.dispatch_strategy
        )
        chosen = body.lot_selections or None
        is_override = False

        try:
            if chosen is None:
                try:
                    plan = await allocate(
                        self.db, tenant_id, product_id, warehouse_id, qty, strategy
                    )
                except InsufficientStockError as exc:
                    # Tell the caller how much of the shortfall is sitting in expired lots.
                    lots = await load_candidate_lots(
                        self.db, tenant_id, product_id, warehouse_id, lock=False
                    )
                    exc.expired_qty = sum(  # type: ignore[attr-defined]
                        (
                            lot.quantity
                            for lot in plan_allocation(lots, qty, strategy).expired_skipped
                        ),
                        Decimal("0"),
                    )
                    raise
                allocs = sorted(
                    (
                        transfer_lots.Alloc(pl.lot_id, pl.lot_number, pl.expiry_date, pl.quantity)
                        for pl in plan.lines
                    ),
                    key=lambda a: a.lot_id,
                )
            else:
                plan, is_override = await validate_manual_selection(
                    self.db, tenant_id, product_id, warehouse_id, qty, chosen, strategy, lock=True
                )
                if is_override:
                    permitted = can_fefo_override if strategy == "FEFO" else can_lot_select
                    if not permitted:
                        raise DispatchError("OVERRIDE_NOT_PERMITTED", strategy=strategy)
                    await record_override(
                        self.db,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        strategy=strategy,
                        movement_type="ISSUE",
                        reference_id=issue_ref,
                        qty=qty,
                        plan=plan,
                        chosen=chosen,
                        reason=body.override_reason,
                    )
                # The lots posted are the user's chosen lots, not the plan.
                allocs = await transfer_lots._chosen_allocs(self.db, tenant_id, product_id, chosen)
        except (DispatchError, InsufficientStockError) as e:
            raise transfer_lots.http_from_engine(e) from e

        tx_ids: list[str] = []
        for alloc in allocs:  # sorted by lot_id
            tx_ids.append(
                await record_transaction(
                    self.db,
                    tenant_id=tenant_id,
                    transaction_type="ISSUE",
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity=-alloc.quantity,  # always a deduction
                    performed_by=user_id,
                    idempotency_key=f"{body.idempotency_key}:lot:{alloc.lot_id}",
                    reference_id=issue_ref,
                    lot_id=alloc.lot_id,
                    lot_number=alloc.lot_number,
                    expiry_date=alloc.expiry_date,
                )
            )

        return IssueStockResponse(
            transaction_id=UUID(tx_ids[0]),
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
            reason_code=body.reason_code,
            created_at=datetime.now(timezone.utc),
            lots=[
                IssuedLot(
                    lot_id=UUID(a.lot_id),
                    lot_number=a.lot_number,
                    expiry_date=a.expiry_date,
                    quantity=a.quantity,
                )
                for a in allocs
            ],
            is_override=is_override,
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
            -abs(body.quantity) if body.reason_code in _FORCE_NEGATIVE_REASONS else body.quantity
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
            action="adjustment:post",
            resource={
                "resource_type": "adjustment",
                "resource_id": tx_id,
                "product_id": str(body.product_id),
                "warehouse_id": str(body.warehouse_id),
                "quantity": str(quantity),
                "reason_code": body.reason_code,
            },
            decision="GRANTED",
            db=self.db,
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
            -abs(body.quantity) if body.reason_code in _FORCE_NEGATIVE_REASONS else body.quantity
        )

        lot_id, lot_number, expiry_date = await self._adjustment_lot_for_post(user, adjustment_id)

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
            lot_id=lot_id,
            lot_number=lot_number,
            expiry_date=expiry_date,
        )

        # APPROVED → POSTED (terminal state)
        await self.db.execute(
            text(
                "UPDATE adjustment_orders SET status = 'POSTED', updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": str(adjustment_id), "tid": str(user.tenant_id)},
        )

        await write_to_outbox(
            self.db,
            str(user.tenant_id),
            "AdjustmentApplied",
            AdjustmentAppliedPayload(
                adjustment_id=str(adjustment_id),
                product_id=str(body.product_id),
                warehouse_id=str(body.warehouse_id),
                delta=float(quantity),
            ),
            idempotency_key=(
                f"{body.idempotency_key}:adjustment-applied" if body.idempotency_key else None
            ),
        )

        await audit_log(
            user,
            "adjustment:approve",
            {
                "resource_type": "adjustment",
                "resource_id": str(adjustment_id),
                "product_id": str(body.product_id),
                "warehouse_id": str(body.warehouse_id),
                "quantity_delta": str(quantity),
                "reason_code": body.reason_code.value,
                "transaction_id": str(tx_id),
                "lot_id": lot_id,
            },
            "GRANTED",
            db=self.db,
        )

        from datetime import datetime, timezone

        return AdjustmentResponse(
            adjustment_id=adjustment_id,
            status="POSTED",
            quantity_delta=quantity,
            created_at=datetime.now(timezone.utc),
            lot_id=UUID(lot_id) if lot_id else None,
            lot_number=lot_number,
            expiry_date=expiry_date,
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

    async def create_transfer(self, user: Any, body: TransferOrderRequest) -> TransferOrderResponse:
        from fastapi import HTTPException

        # Reject inactive (deactivated) warehouses on either side — otherwise a
        # transfer can be created against a node that has been closed/deactivated,
        # defeating the deactivation feature's purpose.
        for side, wid in (("from", body.from_warehouse_id), ("to", body.to_warehouse_id)):
            node_row = (
                await self.db.execute(
                    text(
                        "SELECT is_active FROM organization_node WHERE id = :nid AND tenant_id = :tid"
                    ),
                    {"nid": str(wid), "tid": str(user.tenant_id)},
                )
            ).fetchone()
            if node_row is not None and not node_row.is_active:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "NODE_INACTIVE",
                        "message": f"Cannot create transfer — the {side} warehouse is inactive. "
                        "Reactivate it first or choose a different warehouse.",
                    },
                )

        # Validate factory-specific products before any INSERT.
        for line in body.lines:
            product_row = (
                await self.db.execute(
                    text(
                        "SELECT sku, source_factory_id FROM products WHERE id = :pid AND tenant_id = :tid"
                    ),
                    {"pid": str(line.product_id), "tid": str(user.tenant_id)},
                )
            ).fetchone()

            if product_row and product_row.source_factory_id is not None:
                subtree = await self._get_factory_subtree(
                    str(user.tenant_id), str(product_row.source_factory_id)
                )
                if str(body.from_warehouse_id) not in subtree:
                    factory_row = (
                        await self.db.execute(
                            text(
                                "SELECT name FROM organization_node WHERE id = :fid AND tenant_id = :tid"
                            ),
                            {"fid": str(product_row.source_factory_id), "tid": str(user.tenant_id)},
                        )
                    ).fetchone()
                    factory_name = (
                        factory_row.name if factory_row else str(product_row.source_factory_id)
                    )
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

        # ── Resolve transfer_type_config (optional — allows backward compat) ──
        config_id: str | None = (
            str(body.transfer_type_config_id) if body.transfer_type_config_id else None
        )

        if config_id is None:
            # Auto-resolve by underlying_type so new tenants get config linkage automatically
            cfg_row = (
                await self.db.execute(
                    text(
                        "SELECT id FROM transfer_type_config WHERE underlying_type = :tt AND tenant_id = :tid AND is_active = true"
                    ),
                    {"tt": body.transfer_type, "tid": str(user.tenant_id)},
                )
            ).fetchone()
            if cfg_row:
                config_id = str(cfg_row.id)

        # ── Validate level permissions if config is present ───────────────────
        if config_id:
            from fastapi import HTTPException as _HTTPException

            # Source node level — check can_initiate
            # Initiator is the requesting side:
            #   PULL:   destination (to_warehouse_id) requests stock from source
            #   PUSH:   source (from_warehouse_id) proactively sends stock down
            #   SISTER: both sides; check the destination (requestor) node
            initiator_node_id = (
                str(body.to_warehouse_id)
                if body.transfer_type in ("PULL", "SISTER")
                else str(body.from_warehouse_id)
            )
            initiator_node = (
                await self.db.execute(
                    text(
                        "SELECT hierarchy_level FROM organization_node WHERE id = :nid AND tenant_id = :tid"
                    ),
                    {"nid": initiator_node_id, "tid": str(user.tenant_id)},
                )
            ).fetchone()
            if initiator_node:
                init_perm = (
                    await self.db.execute(
                        text(
                            "SELECT can_initiate FROM transfer_type_level_permissions "
                            "WHERE transfer_type_config_id = :cid AND level_number = :ln"
                        ),
                        {"cid": config_id, "ln": initiator_node.hierarchy_level},
                    )
                ).fetchone()
                if init_perm is not None and not init_perm.can_initiate:
                    raise _HTTPException(
                        status_code=422,
                        detail={
                            "code": "LEVEL_CANNOT_INITIATE",
                            "message": f"Level {initiator_node.hierarchy_level} nodes cannot initiate this transfer type.",
                        },
                    )
            # Destination node level — check can_receive
            dst_node = (
                await self.db.execute(
                    text(
                        "SELECT hierarchy_level FROM organization_node WHERE id = :nid AND tenant_id = :tid"
                    ),
                    {"nid": str(body.to_warehouse_id), "tid": str(user.tenant_id)},
                )
            ).fetchone()
            if dst_node:
                dst_perm = (
                    await self.db.execute(
                        text(
                            "SELECT can_receive FROM transfer_type_level_permissions "
                            "WHERE transfer_type_config_id = :cid AND level_number = :ln"
                        ),
                        {"cid": config_id, "ln": dst_node.hierarchy_level},
                    )
                ).fetchone()
                if dst_perm is not None and not dst_perm.can_receive:
                    raise _HTTPException(
                        status_code=422,
                        detail={
                            "code": "LEVEL_CANNOT_RECEIVE",
                            "message": f"Level {dst_node.hierarchy_level} nodes cannot receive this transfer type.",
                        },
                    )

        # ── Source stock availability check ──────────────────────────────────
        # Reject at creation time when requested qty exceeds available stock at the
        # source warehouse for any line.  Catches over-allocation for PUSH, PULL, and
        # SISTER before the transfer enters the approval workflow.
        # available = on_hand  - pending_out (soft holds at PENDING_* statuses).
        # APPROVED/ISSUED/IN_TRANSIT are excluded: on_hand already reflects the
        # APPROVED deduction, so counting them again would double-subtract.
        from fastapi import HTTPException as _HTTPEx2

        for line in body.lines:
            oh_row = (
                await self.db.execute(
                    text(
                        "SELECT COALESCE(quantity, 0) AS qty "
                        "FROM inventory_balances "
                        "WHERE tenant_id = :tid AND product_id = :pid "
                        "  AND warehouse_id = :wid AND lot_number IS NULL"
                    ),
                    {
                        "tid": str(user.tenant_id),
                        "pid": str(line.product_id),
                        "wid": str(body.from_warehouse_id),
                    },
                )
            ).fetchone()
            on_hand = Decimal(str(oh_row.qty)) if oh_row else Decimal("0")

            pending_row = (
                await self.db.execute(
                    text(
                        "SELECT COALESCE(SUM(tol.quantity), 0) AS pending "
                        "FROM transfer_order_lines tol "
                        "JOIN transfer_orders to_ ON to_.id = tol.transfer_order_id "
                        "WHERE to_.from_warehouse_id = :wid "
                        "  AND tol.product_id = :pid "
                        "  AND to_.tenant_id = :tid "
                        "  AND to_.status IN ("
                        "    'PENDING_REVIEW','PENDING_APPROVAL',"
                        "    'PENDING_SOURCE_CONFIRM','PENDING_DEST_CONFIRM'"
                        "  )"
                    ),
                    {
                        "tid": str(user.tenant_id),
                        "pid": str(line.product_id),
                        "wid": str(body.from_warehouse_id),
                    },
                )
            ).fetchone()
            pending_out = Decimal(str(pending_row.pending)) if pending_row else Decimal("0")

            available = on_hand - pending_out
            if line.quantity > available:
                raise _HTTPEx2(
                    status_code=422,
                    detail={
                        "code": "INSUFFICIENT_STOCK",
                        "product_id": str(line.product_id),
                        "warehouse_id": str(body.from_warehouse_id),
                        "available": float(available),
                        "requested": float(line.quantity),
                        "message": (
                            f"Insufficient stock. "
                            f"Available: {available}, Requested: {line.quantity}"
                        ),
                    },
                )

        # ── Calculate total_value from product unit_prices ────────────────────
        total_value: Decimal | None = None
        for line in body.lines:
            price_row = (
                await self.db.execute(
                    text("SELECT unit_price FROM products WHERE id = :pid AND tenant_id = :tid"),
                    {"pid": str(line.product_id), "tid": str(user.tenant_id)},
                )
            ).fetchone()
            if price_row and price_row.unit_price is not None:
                line_value = Decimal(str(price_row.unit_price)) * line.quantity
                total_value = (total_value or Decimal("0")) + line_value

        # ── Insert transfer order ─────────────────────────────────────────────
        await self.db.execute(
            text(
                "INSERT INTO transfer_orders "
                "(id, tenant_id, from_warehouse_id, to_warehouse_id, transfer_type, status, "
                "created_by, created_by_authority_level, "
                "transfer_type_config_id, total_value, currency) "
                "VALUES (:id, :tid, :from_wid, :to_wid, :ttype, 'DRAFT', :uid, :creator_level, "
                ":config_id, :total_value, :currency)"
            ),
            {
                "id": str(transfer_id),
                "tid": str(user.tenant_id),
                "from_wid": str(body.from_warehouse_id),
                "to_wid": str(body.to_warehouse_id),
                "ttype": body.transfer_type,
                "uid": str(user.user_id),
                "creator_level": ROLE_AUTHORITY_LEVEL.get(getattr(user, "role", "WM"), 4),
                "config_id": config_id,
                "total_value": str(total_value) if total_value is not None else None,
                "currency": "ETB",
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

        import uuid as _uuid

        return TransferOrderResponse(
            transfer_id=transfer_id,
            transfer_type=body.transfer_type,
            status="DRAFT",
            from_warehouse_id=body.from_warehouse_id,
            to_warehouse_id=body.to_warehouse_id,
            created_at=now,
            total_value=total_value,
            currency="ETB",
            transfer_type_config_id=_uuid.UUID(config_id) if config_id else None,
        )

    async def transition_transfer(
        self,
        user: Any,
        transfer_id: UUID,
        next_state: str,
        lot_selections: Optional[list] = None,
        override_reason: Optional[str] = None,
        can_fefo_override: bool = False,
        can_lot_select: bool = False,
    ) -> TransferOrderResponse:
        result = await self.db.execute(
            text("SELECT * FROM transfer_orders WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
            {"id": str(transfer_id), "tid": str(user.tenant_id)},
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

        # Lots are chosen only on the call that posts TRANSFER_OUT (final approval).
        if lot_selections and next_state != "APPROVED":
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail={"code": "LOT_SELECTION_NOT_ALLOWED"})

        _lines_query = text(
            "SELECT * FROM transfer_order_lines "
            "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
        )
        _lines_params = {"tid_order": str(transfer_id), "tid": str(user.tenant_id)}

        # PENDING_REVIEW: WH submitted the PULL request; source has not yet committed.
        # No RESERVE is written here — the source warehouse has not seen or acted on
        # the request, so no stock should be locked at this stage.
        # (PUSH never reaches PENDING_REVIEW; SISTER goes via PENDING_SOURCE_CONFIRM.)
        #
        # Self-approval fast-path: if the submitter's policy permits it, skip
        # the full approval chain and jump directly to APPROVED in one step.
        if next_state == "PENDING_REVIEW":
            lines = (await self.db.execute(_lines_query, _lines_params)).fetchall()
            total_qty = sum(Decimal(str(ln.quantity)) for ln in lines)
            try:
                total_value_pull = Decimal(str(getattr(row, "total_value", None) or "0"))
            except Exception:
                total_value_pull = Decimal("0")

            # Product override (Design B) — takes precedence over self-approval.
            # If any line's product has an active override that fires for this
            # quantity/value, skip self-approval entirely; the named approver
            # position will be enforced when normal routing is resolved at
            # PENDING_APPROVAL.
            _product_override_pull = await _resolve_product_override(
                self.db,
                str(user.tenant_id),
                lines,
                transfer_type,
                total_qty,
                total_value_pull,
            )
            if _product_override_pull is not None:
                await _apply_product_override_flag(
                    self.db,
                    user,
                    "transfer",
                    transfer_id,
                    _product_override_pull,
                )
                _self_approval_policy_pull = None
            else:
                _self_approval_policy_pull = await get_self_approval_decision(
                    session=self.db,
                    tenant_id=str(user.tenant_id),
                    user_role=str(user.role),
                    level_number=getattr(user, "level_number", None),
                    transfer_type=transfer_type,
                    quantity=total_qty,
                    total_value=total_value_pull,
                )
            if _self_approval_policy_pull is not None:
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
                        status_transition="DRAFT_TO_SELF_APPROVED_RESERVE",
                        line_id=str(line.id),
                    )
                try:
                    await transfer_lots.post_transfer_out(
                        self.db,
                        tenant_id=str(user.tenant_id),
                        user_id=str(user.user_id),
                        transfer_id=str(transfer_id),
                        from_warehouse_id=str(row.from_warehouse_id),
                        lines=lines,
                        key_prefix=f"transfer:{transfer_id}:self_approve:out",
                    )
                except (DispatchError, InsufficientStockError) as e:
                    raise transfer_lots.http_from_engine(e) from e
                await self.db.execute(
                    text(
                        "UPDATE transfer_orders "
                        "SET status = 'APPROVED', is_self_approved = TRUE, updated_at = now() "
                        "WHERE id = :id"
                    ),
                    {"id": str(transfer_id)},
                )
                await audit_log(
                    user=user,
                    action="transfer:self_approved",
                    resource={
                        "resource_type": "transfer",
                        "resource_id": str(transfer_id),
                        "transfer_type": transfer_type,
                        "quantity": str(total_qty),
                        "total_value": str(total_value_pull),
                        "policy": {
                            "role_code": str(user.role),
                            "level_number": getattr(user, "level_number", None),
                            "threshold_type": _self_approval_policy_pull.threshold_type,
                            "qty_limit": str(_self_approval_policy_pull.qty_limit)
                            if _self_approval_policy_pull.qty_limit is not None
                            else None,
                            "value_limit": str(_self_approval_policy_pull.value_limit)
                            if _self_approval_policy_pull.value_limit is not None
                            else None,
                        },
                    },
                    decision="GRANTED",
                    reason="within_self_approval_limit",
                    db=self.db,
                )
                from datetime import datetime, timezone

                return TransferOrderResponse(
                    transfer_id=transfer_id,
                    transfer_type=transfer_type,
                    status="APPROVED",
                    from_warehouse_id=row.from_warehouse_id,
                    to_warehouse_id=row.to_warehouse_id,
                    created_at=datetime.now(timezone.utc),
                    is_self_approved=True,
                )

        # PENDING_APPROVAL: first committed reservation for ALL transfer types.
        #   PULL:   source reviewed the request and forwarded it — lock now.
        #   PUSH:   source initiates here (DRAFT → PENDING_APPROVAL); lock immediately.
        #   SISTER: both parties confirmed (PENDING_DEST_CONFIRM → PENDING_APPROVAL);
        #           source is committed — lock now.
        elif next_state == "PENDING_APPROVAL":
            from services.approval_service import resolve_transfer_approvers as _resolve_approvers

            lines = (await self.db.execute(_lines_query, _lines_params)).fetchall()
            total_qty = sum(Decimal(str(ln.quantity)) for ln in lines)

            # Self-approval fast-path for PUSH (DRAFT → PENDING_APPROVAL is the submission
            # step). If the submitter's policy permits it, skip the approval chain and jump
            # directly to APPROVED. PULL self-approval is handled earlier at PENDING_REVIEW.
            # SISTER is excluded intentionally — dual-confirm is non-negotiable (§17).
            if row.status == "DRAFT" and transfer_type == "PUSH":
                try:
                    total_value_push = Decimal(str(getattr(row, "total_value", None) or "0"))
                except Exception:
                    total_value_push = Decimal("0")

                # Product override (Design B) — takes precedence over self-approval.
                _product_override_push = await _resolve_product_override(
                    self.db,
                    str(user.tenant_id),
                    lines,
                    transfer_type,
                    total_qty,
                    total_value_push,
                )
                if _product_override_push is not None:
                    await _apply_product_override_flag(
                        self.db,
                        user,
                        "transfer",
                        transfer_id,
                        _product_override_push,
                    )
                    _self_approval_policy_push = None
                else:
                    _self_approval_policy_push = await get_self_approval_decision(
                        session=self.db,
                        tenant_id=str(user.tenant_id),
                        user_role=str(user.role),
                        level_number=getattr(user, "level_number", None),
                        transfer_type=transfer_type,
                        quantity=total_qty,
                        total_value=total_value_push,
                    )
                if _self_approval_policy_push is not None:
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
                            status_transition="DRAFT_TO_SELF_APPROVED_RESERVE",
                            line_id=str(line.id),
                        )
                    try:
                        await transfer_lots.post_transfer_out(
                            self.db,
                            tenant_id=str(user.tenant_id),
                            user_id=str(user.user_id),
                            transfer_id=str(transfer_id),
                            from_warehouse_id=str(row.from_warehouse_id),
                            lines=lines,
                            key_prefix=f"transfer:{transfer_id}:self_approve:out",
                        )
                    except (DispatchError, InsufficientStockError) as e:
                        raise transfer_lots.http_from_engine(e) from e
                    await self.db.execute(
                        text(
                            "UPDATE transfer_orders "
                            "SET status = 'APPROVED', is_self_approved = TRUE, updated_at = now() "
                            "WHERE id = :id"
                        ),
                        {"id": str(transfer_id)},
                    )
                    await audit_log(
                        user=user,
                        action="transfer:self_approved",
                        resource={
                            "resource_type": "transfer",
                            "resource_id": str(transfer_id),
                            "transfer_type": transfer_type,
                            "quantity": str(total_qty),
                            "total_value": str(total_value_push),
                            "policy": {
                                "role_code": str(user.role),
                                "level_number": getattr(user, "level_number", None),
                                "threshold_type": _self_approval_policy_push.threshold_type,
                                "qty_limit": str(_self_approval_policy_push.qty_limit)
                                if _self_approval_policy_push.qty_limit is not None
                                else None,
                                "value_limit": str(_self_approval_policy_push.value_limit)
                                if _self_approval_policy_push.value_limit is not None
                                else None,
                            },
                        },
                        decision="GRANTED",
                        reason="within_self_approval_limit",
                        db=self.db,
                    )
                    from datetime import datetime, timezone

                    return TransferOrderResponse(
                        transfer_id=transfer_id,
                        transfer_type=transfer_type,
                        status="APPROVED",
                        from_warehouse_id=row.from_warehouse_id,
                        to_warehouse_id=row.to_warehouse_id,
                        created_at=datetime.now(timezone.utc),
                        is_self_approved=True,
                    )

            # Write RESERVE for each line at the source warehouse.
            # Idempotency key encodes the originating status so retries are safe.
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
                    status_transition=f"{row.status}_TO_PENDING_APPROVAL",
                    line_id=str(line.id),
                )
            tv_row = (
                await self.db.execute(
                    text(
                        "SELECT transfer_type_config_id, total_value, created_by "
                        "FROM transfer_orders WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"id": str(transfer_id), "tid": str(user.tenant_id)},
                )
            ).fetchone()
            config_id_for_res = (
                str(tv_row.transfer_type_config_id)
                if tv_row and tv_row.transfer_type_config_id
                else None
            )
            tv_for_res = Decimal(str(tv_row.total_value)) if tv_row and tv_row.total_value else None
            created_by_for_res = str(tv_row.created_by) if tv_row and tv_row.created_by else None

            # If the transfer was created before transfer type configs existed,
            # transfer_type_config_id may be NULL.  Re-resolve it now so rules
            # are used for legacy transfers too.
            if not config_id_for_res:
                cfg_fallback = (
                    await self.db.execute(
                        text(
                            "SELECT id FROM transfer_type_config "
                            "WHERE underlying_type = :tt AND tenant_id = :tid AND is_active = true "
                            "LIMIT 1"
                        ),
                        {"tt": transfer_type, "tid": str(user.tenant_id)},
                    )
                ).fetchone()
                if cfg_fallback:
                    config_id_for_res = str(cfg_fallback.id)

            # Product override (Design B) takes precedence over normal position
            # routing — if a prior step already flagged this transfer (or any
            # line's product carries an active override that now fires), route
            # directly to the override's approver position instead of calling
            # resolve_transfer_approvers().
            _product_override_routing = await _resolve_product_override(
                self.db,
                str(user.tenant_id),
                lines,
                transfer_type,
                total_qty,
                tv_for_res if tv_for_res is not None else Decimal("0"),
            )
            if _product_override_routing is not None:
                if not getattr(row, "product_override_applied", False):
                    await _apply_product_override_flag(
                        self.db,
                        user,
                        "transfer",
                        transfer_id,
                        _product_override_routing,
                    )
                resolved_steps = await _override_resolution_steps(
                    self.db,
                    str(user.tenant_id),
                    _product_override_routing,
                    created_by_for_res,
                )
            else:
                resolution = await _resolve_approvers(
                    session=self.db,
                    tenant_id=str(user.tenant_id),
                    transfer_type_config_id=config_id_for_res,
                    from_warehouse_id=str(row.from_warehouse_id),
                    to_warehouse_id=str(row.to_warehouse_id),
                    quantity=total_qty,
                    total_value=tv_for_res,
                    created_by=created_by_for_res,
                )
                resolved_steps = _json.loads(resolution.steps_as_json())

            await self.db.execute(
                text(
                    "UPDATE transfer_orders "
                    "SET resolved_approval_steps = :steps, current_approval_step = 1 "
                    "WHERE id = :id"
                ).bindparams(bindparam("steps", type_=types.JSON)),
                {"steps": resolved_steps, "id": str(transfer_id)},
            )

        # APPROVED: authority check → hard deduction per line → auto-approve notification.
        elif next_state == "APPROVED":
            lines = (
                await self.db.execute(
                    text(
                        "SELECT * FROM transfer_order_lines "
                        "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
                    ),
                    {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
                )
            ).fetchall()

            total_qty = sum(Decimal(str(ln.quantity)) for ln in lines)

            # Self-approval guard: fetch the creator's authority level stored at creation.
            creator_level: int | None = getattr(row, "created_by_authority_level", None)
            caller_level = ROLE_AUTHORITY_LEVEL.get(getattr(user, "role", ""), 5)

            # Belt-and-suspenders: if the caller IS the creator, reject immediately.
            if getattr(row, "created_by", None) is not None and str(
                getattr(row, "created_by", "")
            ) == str(user.user_id):
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "CANNOT_APPROVE_OWN_TRANSFER",
                        "message": "You cannot approve a transfer you created.",
                    },
                )

            # Compute once for both the gate and auto-approve notification.
            simple_mode = await _get_simple_mode(self.db, str(user.tenant_id))
            decision = await resolve_approval(
                self.db,
                str(user.tenant_id),
                transfer_type,
                total_qty,
                requester_authority_level=creator_level,
                simple_mode=simple_mode,
            )

            # Gate check: dynamic routing overrides simple-mode authority level.
            await _check_can_approve(row, user, caller_level, decision)

            # ── Multi-step sequential advancement (GAP-A fix) ────────────────
            # resolved_approval_steps snapshot was set at PENDING_APPROVAL time.
            # Each /approve call marks the current step and checks if more remain.
            _steps: list[dict] = list(row.resolved_approval_steps or [])
            if isinstance(_steps, str):
                _steps = _json.loads(_steps)

            if _steps:
                from datetime import datetime as _dt, timezone as _tz

                _cur_idx = (getattr(row, "current_approval_step", 1) or 1) - 1
                _next_idx = _cur_idx + 1

                _steps[_cur_idx]["status"] = "approved"
                _steps[_cur_idx]["approved_by_user_id"] = str(user.user_id)
                _steps[_cur_idx]["approved_at"] = _dt.now(_tz.utc).isoformat()

                if _next_idx < len(_steps):
                    # More steps remain — advance counter, stay PENDING_APPROVAL.
                    # Do NOT fire TRANSFER_OUT; return early before the fall-through.
                    if lot_selections:
                        from fastapi import HTTPException

                        raise HTTPException(
                            status_code=422, detail={"code": "LOT_SELECTION_NOT_ALLOWED"}
                        )
                    await self.db.execute(
                        text(
                            "UPDATE transfer_orders "
                            "SET resolved_approval_steps = :steps, "
                            "    current_approval_step = :next_step, "
                            "    updated_at = now() "
                            "WHERE id = :id"
                        ).bindparams(bindparam("steps", type_=types.JSON)),
                        {
                            "steps": _steps,
                            "next_step": _next_idx + 1,
                            "id": str(transfer_id),
                        },
                    )
                    await audit_log(
                        user=user,
                        action="transfer:step_approved",
                        resource={
                            "resource_type": "transfer",
                            "resource_id": str(transfer_id),
                            "step": _cur_idx + 1,
                            "total_steps": len(_steps),
                        },
                        decision="GRANTED",
                        reason=(
                            f"Step {_cur_idx + 1} of {len(_steps)} approved; "
                            f"advancing to step {_next_idx + 1}"
                        ),
                        db=self.db,
                    )
                    from datetime import datetime, timezone

                    return TransferOrderResponse(
                        transfer_id=transfer_id,
                        transfer_type=transfer_type,
                        status="PENDING_APPROVAL",
                        from_warehouse_id=row.from_warehouse_id,
                        to_warehouse_id=row.to_warehouse_id,
                        created_at=datetime.now(timezone.utc),
                        current_approval_step=_next_idx + 1,
                        resolved_approval_steps=_steps,
                    )
                else:
                    # Final step — persist the approval into the JSONB snapshot,
                    # then fall through to TRANSFER_OUT and the APPROVED transition.
                    await self.db.execute(
                        text(
                            "UPDATE transfer_orders "
                            "SET resolved_approval_steps = :steps "
                            "WHERE id = :id"
                        ).bindparams(bindparam("steps", type_=types.JSON)),
                        {"steps": _steps, "id": str(transfer_id)},
                    )

            try:
                await transfer_lots.post_transfer_out(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    user_id=str(user.user_id),
                    transfer_id=str(transfer_id),
                    from_warehouse_id=str(row.from_warehouse_id),
                    lines=lines,
                    key_prefix=f"transfer:{transfer_id}:approve:out",
                    selections=lot_selections,
                    can_fefo_override=can_fefo_override,
                    can_lot_select=can_lot_select,
                    reason=override_reason,
                )
            except (DispatchError, InsufficientStockError) as e:
                raise transfer_lots.http_from_engine(e) from e

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

        # CANCELLED/REJECTED from PENDING_APPROVAL: release the RESERVE written when
        # entering PENDING_APPROVAL.  Must NOT fire for PENDING_REVIEW (PULL) or
        # PENDING_SOURCE_CONFIRM/PENDING_DEST_CONFIRM (SISTER) — no RESERVE was written
        # at those stages so there is nothing to release.
        elif next_state in ("CANCELLED", "REJECTED") and row.status == "PENDING_APPROVAL":
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
            _allocs = await transfer_lots.load_allocations(self.db, user.tenant_id, transfer_id)
            for line in lines:
                if _allocs.get(str(line.id)):
                    # Batch line: put each lot back at the source.
                    await transfer_lots.post_lot_audit(
                        self.db,
                        tenant_id=str(user.tenant_id),
                        user_id=str(user.user_id),
                        transfer_id=str(transfer_id),
                        line=line,
                        allocs=_allocs[str(line.id)],
                        transaction_type="TRANSFER_REVERSAL",
                        warehouse_id=str(row.from_warehouse_id),
                        sign=1,
                        status_transition="APPROVED_TO_CANCELLED",
                    )
                    continue
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
            _allocs = await transfer_lots.load_allocations(self.db, user.tenant_id, transfer_id)
            for line in lines:
                if _allocs.get(str(line.id)):
                    for _type, _wh in (
                        ("TRANSIT_OUT", row.from_warehouse_id),
                        ("TRANSIT_IN", row.to_warehouse_id),
                    ):
                        await transfer_lots.post_lot_audit(
                            self.db,
                            tenant_id=str(user.tenant_id),
                            user_id=str(user.user_id),
                            transfer_id=str(transfer_id),
                            line=line,
                            allocs=_allocs[str(line.id)],
                            transaction_type=_type,
                            warehouse_id=str(_wh),
                            sign=1,
                            status_transition="ISSUED_TO_IN_TRANSIT",
                        )
                    continue
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

            # CLAUDE.md §27 "Acting on behalf of": record when the dispatching user's
            # facility differs from the transfer's source facility.
            dispatch_audit_resource: dict[str, Any] = {
                "resource_type": "transfer",
                "resource_id": str(transfer_id),
                "transfer_type": transfer_type,
                "status_transition": "ISSUED_TO_IN_TRANSIT",
            }
            if str(user.warehouse_id or "").lower() != str(row.from_warehouse_id).lower():
                dispatch_audit_resource["acted_on_behalf_of"] = await _get_warehouse_name(
                    self.db, str(user.tenant_id), str(row.from_warehouse_id)
                ) or str(row.from_warehouse_id)
            await audit_log(
                user=user,
                action="transfer:dispatch",
                resource=dispatch_audit_resource,
                decision="GRANTED",
                db=self.db,
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
        # NM/TA/SA have tenant-wide authority — check role FIRST regardless of warehouse_id.
        # An NM with a specific facility assignment can still dispatch from any source because
        # their authority is organisation-wide, not facility-scoped (CLAUDE.md §13).
        # Facility-bound roles (WM/RM/LM) must match warehouse_id to from_warehouse_id.
        _TENANT_LEVEL_ROLES = {"NM", "TA", "SA"}
        user_role = getattr(user, "role", None)
        if user_role in _TENANT_LEVEL_ROLES:
            can_dispatch = True
        elif user.warehouse_id:
            can_dispatch = str(user.warehouse_id).lower() == str(row.from_warehouse_id).lower()
        else:
            can_dispatch = False
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

        lines = (
            await self.db.execute(
                text(
                    "SELECT * FROM transfer_order_lines "
                    "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
                ),
                {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
            )
        ).fetchall()

        # Source on_hand was already deducted at APPROVED via TRANSFER_OUT.
        # Record physical dispatch in the audit ledger (does not affect on_hand again).
        _allocs = await transfer_lots.load_allocations(self.db, user.tenant_id, transfer_id)
        for line in lines:
            if _allocs.get(str(line.id)):
                await transfer_lots.post_lot_audit(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    user_id=str(user.user_id),
                    transfer_id=str(transfer_id),
                    line=line,
                    allocs=_allocs[str(line.id)],
                    transaction_type="TRANSIT_OUT",
                    warehouse_id=str(row.from_warehouse_id),
                    sign=1,
                    status_transition="APPROVED_TO_ISSUED",
                )
                continue
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

        # CLAUDE.md §27 "Acting on behalf of": when the issuing user's facility differs
        # from the transfer's source facility (e.g. an L1/TA issuing for a WM), record
        # which facility they acted on behalf of in the audit trail.
        audit_resource: dict[str, Any] = {
            "resource_type": "transfer",
            "resource_id": str(transfer_id),
            "transfer_type": transfer_type,
            "status_transition": "APPROVED_TO_ISSUED",
        }
        if str(user.warehouse_id or "").lower() != str(row.from_warehouse_id).lower():
            audit_resource["acted_on_behalf_of"] = await _get_warehouse_name(
                self.db, str(user.tenant_id), str(row.from_warehouse_id)
            ) or str(row.from_warehouse_id)
        await audit_log(
            user=user,
            action="transfer:issue",
            resource=audit_resource,
            decision="GRANTED",
            db=self.db,
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

    async def receive_transfer(
        self,
        user: Any,
        transfer_id: UUID,
        receipt: Optional[ReceiveTransferRequest] = None,
    ) -> TransferOrderResponse:
        """Advance an IN_TRANSIT transfer to RECEIVED.

        Writes a TRANSFER_IN ledger entry for every line and credits the destination
        warehouse balance.  Only the destination warehouse manager may receive —
        user.warehouse_id must equal transfer.to_warehouse_id.

        Writes a StockTransferred outbox event per line in the same transaction.

        receipt (optional) confirms a received quantity per allocated lot (batch
        line) or per line (non-batch line). TRANSFER_IN then credits the received
        quantity only and every shortfall becomes an OPEN transfer_discrepancies
        row; TRANSIT_CLEAR still clears the full sent quantity and the transfer
        still ends in RECEIVED. Without it every line is received in full.
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
        # NM/TA/SA have tenant-wide authority — check role FIRST regardless of warehouse_id.
        # Facility-bound roles (WM/RM/LM) must match warehouse_id to to_warehouse_id.
        # Fallback: RM who created the PULL (no warehouse_id) is the logical dest manager.
        _TENANT_LEVEL_ROLES = {"NM", "TA", "SA"}
        user_role = getattr(user, "role", None)
        if user_role in _TENANT_LEVEL_ROLES:
            can_receive = True
        elif user.warehouse_id:
            can_receive = str(user.warehouse_id).lower() == str(row.to_warehouse_id).lower()
        else:
            can_receive = str(getattr(user, "user_id", "")) == str(
                getattr(row, "created_by", "NONE")
            )
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

        lines = (
            await self.db.execute(
                text(
                    "SELECT * FROM transfer_order_lines "
                    "WHERE transfer_order_id = :tid_order AND tenant_id = :tid"
                ),
                {"tid_order": str(transfer_id), "tid": str(user.tenant_id)},
            )
        ).fetchall()

        _allocs = await transfer_lots.load_allocations(self.db, user.tenant_id, transfer_id)

        # Receipt confirmation: the whole body is checked before anything is written.
        _expected: dict = {}
        _receipt: Optional[dict] = None
        if receipt is not None:
            _expected = transfer_discrepancies.expected_entries(lines, _allocs)
            _receipt = transfer_discrepancies.validate_receipt(_expected, receipt.lines)

        _sent_total = Decimal("0")
        _received_total = Decimal("0")
        _discrepancy_count = 0
        for line in lines:
            _line_allocs = _allocs.get(str(line.id))
            # Credited at the destination for this line (the full line without a receipt).
            _line_received = Decimal(str(line.quantity))
            if _line_allocs:
                # Batch line: clear transit and credit the destination per lot,
                # on the same lot_ids the source was debited on.
                _received_by_lot: Optional[dict[str, Decimal]] = None
                if _receipt is not None:
                    _received_by_lot = {
                        a.lot_id: _receipt[(str(line.id), a.lot_id)].received_quantity
                        for a in _line_allocs
                    }
                    _line_received = sum(_received_by_lot.values(), Decimal("0"))
                for _wh, _dest in ((row.from_warehouse_id, False), (row.to_warehouse_id, True)):
                    await transfer_lots.post_lot_audit(
                        self.db,
                        tenant_id=str(user.tenant_id),
                        user_id=str(user.user_id),
                        transfer_id=str(transfer_id),
                        line=line,
                        allocs=_line_allocs,
                        transaction_type="TRANSIT_CLEAR",
                        warehouse_id=str(_wh),
                        sign=-1,
                        status_transition="IN_TRANSIT_TO_RECEIVED",
                        dest=_dest,
                    )
                await transfer_lots.post_transfer_in(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    user_id=str(user.user_id),
                    transfer_id=str(transfer_id),
                    to_warehouse_id=str(row.to_warehouse_id),
                    line=line,
                    allocs=_line_allocs,
                    received_by_lot=_received_by_lot,
                )
            else:
                if _receipt is not None:
                    _line_received = _receipt[(str(line.id), None)].received_quantity
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
                # Nothing received on this line: no zero-quantity TRANSFER_IN.
                if _line_received > 0:
                    await record_transaction(
                        self.db,
                        tenant_id=str(user.tenant_id),
                        transaction_type="TRANSFER_IN",
                        product_id=str(line.product_id),
                        warehouse_id=str(row.to_warehouse_id),
                        quantity=_line_received,  # positive: credit to destination
                        performed_by=str(user.user_id),
                        idempotency_key=f"transfer:{transfer_id}:receive:in:line:{line.id}",
                        reference_id=str(transfer_id),
                    )

            # One OPEN discrepancy per lot (batch) or line (non-batch) that came up short.
            if _receipt is not None:
                for (_line_id, _lot_id), _sent in _expected.items():
                    _entry = _receipt[(_line_id, _lot_id)]
                    if _line_id != str(line.id) or _entry.received_quantity >= _sent:
                        continue
                    _discrepancy_count += 1
                    await transfer_discrepancies.insert_discrepancy(
                        self.db,
                        tenant_id=str(user.tenant_id),
                        transfer_id=str(transfer_id),
                        line_id=_line_id,
                        product_id=str(line.product_id),
                        lot_id=_lot_id,
                        to_warehouse_id=str(row.to_warehouse_id),
                        sent_quantity=_sent,
                        received_quantity=_entry.received_quantity,
                        reason=_entry.reason,
                        note=_entry.note,
                        created_by=str(user.user_id),
                    )

            _sent_total += Decimal(str(line.quantity))
            _received_total += _line_received

            # StockTransferred is an additional event beyond the InventoryUpdated
            # that record_transaction() already fired — both in the same transaction.
            # It carries what was received; a line that received nothing fires none.
            if _line_received > 0:
                await write_to_outbox(
                    self.db,
                    str(user.tenant_id),
                    "StockTransferred",
                    StockTransferredPayload(
                        from_warehouse_id=str(row.from_warehouse_id),
                        to_warehouse_id=str(row.to_warehouse_id),
                        product_id=str(line.product_id),
                        quantity=float(_line_received),
                        transfer_order_id=str(transfer_id),
                    ),
                )

        await self.db.execute(
            text(
                "UPDATE transfer_orders SET status = 'RECEIVED', updated_at = now() WHERE id = :id"
            ),
            {"id": str(transfer_id)},
        )

        # Transfer-linked audit row, in the receipt's own transaction (the permission
        # middleware's transfer:receive row carries no resource_id). Shape mirrors the
        # issue/dispatch rows; lets both transfer ends see the receipt in the Audit Log.
        receive_audit_resource: dict[str, Any] = {
            "resource_type": "transfer",
            "resource_id": str(transfer_id),
            "transfer_type": transfer_type,
            "status_transition": "IN_TRANSIT_TO_RECEIVED",
            "received_quantity_total": str(_received_total),
            "short_quantity_total": str(_sent_total - _received_total),
            "discrepancy_count": _discrepancy_count,
        }
        if str(user.warehouse_id or "").lower() != str(row.to_warehouse_id).lower():
            receive_audit_resource["acted_on_behalf_of"] = await _get_warehouse_name(
                self.db, str(user.tenant_id), str(row.to_warehouse_id)
            ) or str(row.to_warehouse_id)
        await audit_log(
            user=user,
            action="transfer:receive",
            resource=receive_audit_resource,
            decision="GRANTED",
            db=self.db,
        )

        _discrepancies: list = []
        if _receipt is not None:
            _discrepancies = await transfer_discrepancies.load_discrepancies(
                self.db, user.tenant_id, transfer_id
            )

        from datetime import datetime, timezone

        return TransferOrderResponse(
            transfer_id=transfer_id,
            transfer_type=transfer_type,
            status="RECEIVED",
            from_warehouse_id=row.from_warehouse_id,
            to_warehouse_id=row.to_warehouse_id,
            created_at=datetime.now(timezone.utc),
            discrepancies=_discrepancies,
        )

    async def get_transfer(self, user: Any, transfer_id: UUID) -> TransferOrderResponse:
        # Facility names: same COALESCE(warehouses, organization_node) as list_transfers.
        result = await self.db.execute(
            text("""
                SELECT
                    to_.*,
                    COALESCE(fw.name, fw_n.name) AS from_warehouse_name,
                    COALESCE(tw.name, tw_n.name) AS to_warehouse_name
                FROM transfer_orders to_
                LEFT JOIN warehouses fw          ON fw.id       = to_.from_warehouse_id
                LEFT JOIN organization_node fw_n ON fw_n.id    = to_.from_warehouse_id
                LEFT JOIN warehouses tw          ON tw.id       = to_.to_warehouse_id
                LEFT JOIN organization_node tw_n ON tw_n.id    = to_.to_warehouse_id
                WHERE to_.id = :id AND to_.tenant_id = :tid
            """),
            {"id": str(transfer_id), "tid": str(user.tenant_id)},
        )
        row = result.fetchone()
        if not row:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Transfer not found")

        scope = await self._transfer_scope(user)
        if scope is not None and not (
            _inside(scope, [row.from_warehouse_id])
            or _inside(scope, [row.to_warehouse_id])
            or _on_approval_steps(scope, user.user_id, row.resolved_approval_steps)
        ):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail={"code": "TRANSFER_OUT_OF_SCOPE"})

        _allocs = await transfer_lots.load_allocations(self.db, row.tenant_id, transfer_id)
        _discrepancies = await transfer_discrepancies.load_discrepancies(
            self.db, row.tenant_id, transfer_id
        )

        return TransferOrderResponse(
            transfer_id=transfer_id,
            transfer_type=row.transfer_type,
            status=row.status,
            reference_number=row.reference_number,
            from_warehouse_id=row.from_warehouse_id,
            from_warehouse_name=row.from_warehouse_name,
            to_warehouse_id=row.to_warehouse_id,
            to_warehouse_name=row.to_warehouse_name,
            created_at=row.created_at,
            total_value=row.total_value,
            currency=row.currency,
            is_self_approved=bool(row.is_self_approved),
            lines=await self._transfer_line_items(transfer_id),
            lot_allocations=[
                TransferLotAllocation(
                    line_id=line_id,
                    product_id=a.product_id,
                    lot_id=a.lot_id,
                    lot_number=a.lot_number,
                    expiry_date=a.expiry_date,
                    quantity=a.quantity,
                    is_override=a.is_override,
                )
                for line_id, line_allocs in _allocs.items()
                for a in line_allocs
            ],
            discrepancies=_discrepancies,
        )

    async def create_adjustment(self, user: Any, body: AdjustmentRequest) -> AdjustmentResponse:
        from datetime import datetime, timezone

        # Idempotency: return the existing record if this key was already used
        existing = (
            await self.db.execute(
                text(
                    "SELECT id, status, quantity_delta, created_at "
                    "FROM adjustment_orders "
                    "WHERE tenant_id = :tid AND idempotency_key = :key"
                ),
                {"tid": str(user.tenant_id), "key": body.idempotency_key},
            )
        ).fetchone()
        if existing is not None:
            return AdjustmentResponse(
                adjustment_id=existing.id,
                status=existing.status,
                quantity_delta=existing.quantity_delta,
                created_at=existing.created_at or datetime.now(timezone.utc),
            )

        lot = await self._validate_adjustment_lot(user, body)
        await self._validate_adjustment_warehouse(user, body)

        adj_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text(
                "INSERT INTO adjustment_orders "
                "(id, tenant_id, warehouse_id, product_id, quantity_delta, "
                " reason_code, status, idempotency_key, notes, created_by, "
                " lot_id, lot_number, expiry_date, auto_lot) "
                "VALUES (:id, :tid, :wid, :pid, :delta, :reason, 'DRAFT', :key, :notes, :uid, "
                "        :lot_id, :lot_number, :expiry_date, :auto_lot)"
            ),
            {
                "id": str(adj_id),
                "tid": str(user.tenant_id),
                "wid": str(body.warehouse_id),
                "pid": str(body.product_id),
                "delta": str(body.quantity_delta),
                "reason": body.reason_code.value,
                "key": body.idempotency_key,
                "notes": body.notes,
                "uid": str(user.user_id),
                "lot_id": lot["lot_id"],
                "lot_number": lot["lot_number"],
                "expiry_date": lot["expiry_date"],
                "auto_lot": lot["auto_lot"],
            },
        )

        await audit_log(
            user,
            "adjustment:create",
            {
                "resource_type": "adjustment",
                "resource_id": str(adj_id),
                "product_id": str(body.product_id),
                "warehouse_id": str(body.warehouse_id),
                "quantity_delta": str(body.quantity_delta),
                "reason_code": body.reason_code.value,
                "lot_id": lot["lot_id"],
                "lot_number": lot["lot_number"],
                "expiry_date": (lot["expiry_date"].isoformat() if lot["expiry_date"] else None),
                "auto_lot": lot["auto_lot"],
            },
            "GRANTED",
            db=self.db,
        )

        return AdjustmentResponse(
            adjustment_id=adj_id,
            status="DRAFT",
            quantity_delta=body.quantity_delta,
            created_at=now,
            lot_id=UUID(lot["lot_id"]) if lot["lot_id"] else None,
            lot_number=lot["shown_lot_number"],
            expiry_date=lot["shown_expiry_date"],
            auto_lot=lot["auto_lot"],
        )

    async def _validate_adjustment_warehouse(self, user: Any, body: AdjustmentRequest) -> None:
        """Confirm body.warehouse_id belongs to the caller's tenant before it is
        ever stored as a FK — mirrors _validate_adjustment_lot's product_id check,
        which this call already relies on existing alongside it."""
        from fastapi import HTTPException

        row = (
            await self.db.execute(
                text(
                    "SELECT 1 FROM warehouses WHERE id = :wid AND tenant_id = :tid "
                    "UNION ALL "
                    "SELECT 1 FROM organization_node WHERE id = :wid AND tenant_id = :tid"
                ),
                {"wid": str(body.warehouse_id), "tid": str(user.tenant_id)},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "WAREHOUSE_NOT_FOUND"})

    async def _validate_adjustment_lot(self, user: Any, body: AdjustmentRequest) -> dict[str, Any]:
        """Check the lot input of a new adjustment against the product's tracking.

        Read-only — a new lot is never created here, only at posting
        (_adjustment_lot_for_post). Returns the four values stored on the
        adjustment_orders row (lot_id, lot_number, expiry_date, auto_lot) plus
        shown_lot_number / shown_expiry_date for the response (the chosen lot's
        own number and expiry when lot_id is given).
        """
        from datetime import date as _date
        from fastapi import HTTPException

        tenant_id = str(user.tenant_id)
        product_id = str(body.product_id)

        product_row = (
            await self.db.execute(
                text(
                    "SELECT batch_tracking, expiry_tracking FROM products "
                    "WHERE id = :pid AND tenant_id = :tid"
                ),
                {"pid": product_id, "tid": tenant_id},
            )
        ).fetchone()
        if product_row is None:
            raise HTTPException(status_code=404, detail={"code": "PRODUCT_NOT_FOUND"})

        none: dict[str, Any] = {
            "lot_id": None,
            "lot_number": None,
            "expiry_date": None,
            "auto_lot": False,
            "shown_lot_number": None,
            "shown_expiry_date": None,
        }

        if not product_row.batch_tracking:
            if (
                body.lot_id is not None
                or (body.lot_number or "").strip()
                or body.expiry_date is not None
                or body.auto_lot
            ):
                raise HTTPException(status_code=422, detail={"code": "LOT_NOT_TRACKED"})
            return none

        # The sign that will actually post — e.g. DAMAGE with +5 posts -5.
        effective_negative = (
            body.reason_code.value in _FORCE_NEGATIVE_REASONS or body.quantity_delta < 0
        )
        has_number = body.lot_number is not None

        async def _existing_lot() -> Any:
            lot_row = (
                await self.db.execute(
                    text(
                        "SELECT id, lot_number, expiry_date FROM stock_lots "
                        "WHERE id = :lid AND tenant_id = :tid AND product_id = :pid"
                    ),
                    {"lid": str(body.lot_id), "tid": tenant_id, "pid": product_id},
                )
            ).fetchone()
            if lot_row is None:
                raise HTTPException(status_code=422, detail={"code": "LOT_NOT_FOUND"})
            return lot_row

        if effective_negative:
            if body.lot_id is None:
                raise HTTPException(status_code=422, detail={"code": "LOT_REQUIRED"})
            if has_number or body.expiry_date is not None or body.auto_lot:
                raise HTTPException(status_code=422, detail={"code": "LOT_INPUT_CONFLICT"})

            lot_row = await _existing_lot()

            balance_row = (
                await self.db.execute(
                    text(
                        "SELECT quantity FROM lot_balances "
                        "WHERE tenant_id = :tid AND lot_id = :lid AND warehouse_id = :wid"
                    ),
                    {"tid": tenant_id, "lid": str(body.lot_id), "wid": str(body.warehouse_id)},
                )
            ).fetchone()
            available = (
                Decimal(str(balance_row.quantity)) if balance_row is not None else Decimal("0")
            )
            if available <= 0:
                raise HTTPException(status_code=422, detail={"code": "LOT_NOT_IN_WAREHOUSE"})

            # An EXPIRED lot is allowed on purpose — this is how expired stock
            # is written off.
            requested = abs(body.quantity_delta)
            if requested > available:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INSUFFICIENT_LOT_STOCK",
                        "lot_id": str(body.lot_id),
                        "warehouse_id": str(body.warehouse_id),
                        "available": float(available),
                        "requested": float(requested),
                    },
                )

            return {
                **none,
                "lot_id": str(body.lot_id),
                "shown_lot_number": lot_row.lot_number,
                "shown_expiry_date": lot_row.expiry_date,
            }

        # Addition: exactly one of an existing lot, a new lot number, an auto lot.
        chosen = sum([body.lot_id is not None, has_number, bool(body.auto_lot)])
        if chosen == 0:
            raise HTTPException(status_code=422, detail={"code": "LOT_REQUIRED"})
        if chosen > 1:
            raise HTTPException(status_code=422, detail={"code": "LOT_INPUT_CONFLICT"})

        if body.lot_id is not None:
            # The lot keeps its own expiry (it may sit at any warehouse).
            if body.expiry_date is not None:
                raise HTTPException(status_code=422, detail={"code": "LOT_INPUT_CONFLICT"})
            lot_row = await _existing_lot()
            return {
                **none,
                "lot_id": str(body.lot_id),
                "shown_lot_number": lot_row.lot_number,
                "shown_expiry_date": lot_row.expiry_date,
            }

        # A new lot — same rules as receive().
        lot_number: Optional[str] = None
        if has_number:
            lot_number = (body.lot_number or "").strip()
            if not lot_number:
                raise HTTPException(status_code=422, detail={"code": "LOT_NUMBER_REQUIRED"})

        expiry_date = body.expiry_date
        if product_row.expiry_tracking and not expiry_date:
            raise HTTPException(status_code=422, detail={"code": "EXPIRY_REQUIRED"})
        if expiry_date is not None and expiry_date < _date.today():
            raise HTTPException(status_code=422, detail={"code": "EXPIRY_IN_PAST"})

        if lot_number is not None:
            same_number = (
                await self.db.execute(
                    text(
                        "SELECT id, expiry_date FROM stock_lots "
                        "WHERE tenant_id = :tid AND product_id = :pid AND lot_number = :lot"
                    ),
                    {"tid": tenant_id, "pid": product_id, "lot": lot_number},
                )
            ).fetchone()
            if same_number is not None and same_number.expiry_date != expiry_date:
                existing_expiry = same_number.expiry_date
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "LOT_EXPIRY_MISMATCH",
                        "lot_number": lot_number,
                        "existing_expiry": (
                            existing_expiry.isoformat() if existing_expiry else None
                        ),
                        "given_expiry": expiry_date.isoformat() if expiry_date else None,
                    },
                )

        return {
            "lot_id": None,
            "lot_number": lot_number,
            "expiry_date": expiry_date,
            "auto_lot": bool(body.auto_lot),
            "shown_lot_number": lot_number,
            "shown_expiry_date": expiry_date,
        }

    async def _adjustment_lot_for_post(
        self, user: Any, adjustment_id: UUID
    ) -> tuple[Optional[str], Optional[str], Optional[Any]]:
        """Resolve the lot an adjustment posts against: (lot_id, lot_number, expiry_date).

        Non-batch product → (None, None, None). A new lot (entered number or
        auto lot) is created here, in the same transaction as the ledger INSERT
        that follows, and written back to adjustment_orders.lot_id so the row
        shows the posted lot. A failed post rolls the new lot back with it.
        """
        from fastapi import HTTPException

        tenant_id = str(user.tenant_id)

        row = (
            await self.db.execute(
                text(
                    "SELECT ao.product_id, ao.lot_id, ao.lot_number, ao.expiry_date, "
                    "       ao.auto_lot, p.batch_tracking "
                    "FROM adjustment_orders ao "
                    "JOIN products p ON p.id = ao.product_id AND p.tenant_id = ao.tenant_id "
                    "WHERE ao.id = :id AND ao.tenant_id = :tid"
                ),
                {"id": str(adjustment_id), "tid": tenant_id},
            )
        ).fetchone()
        if row is None or not row.batch_tracking:
            return None, None, None

        if row.lot_id is not None:
            lot_row = (
                await self.db.execute(
                    text(
                        "SELECT lot_number, expiry_date FROM stock_lots "
                        "WHERE id = :lid AND tenant_id = :tid"
                    ),
                    {"lid": str(row.lot_id), "tid": tenant_id},
                )
            ).fetchone()
            if lot_row is None:
                raise HTTPException(status_code=422, detail={"code": "LOT_NOT_FOUND"})
            return str(row.lot_id), lot_row.lot_number, lot_row.expiry_date

        if row.lot_number is not None:
            # Raises LOT_EXPIRY_MISMATCH if the lot changed since creation.
            lot_id = await get_or_create_lot(
                self.db,
                tenant_id=tenant_id,
                product_id=str(row.product_id),
                lot_number=row.lot_number,
                expiry_date=row.expiry_date,
                performed_by=str(user.user_id),
            )
            lot_number = row.lot_number
        elif row.auto_lot:
            lot_id, lot_number = await create_auto_lot(
                self.db,
                tenant_id=tenant_id,
                product_id=str(row.product_id),
                expiry_date=row.expiry_date,
                performed_by=str(user.user_id),
            )
        else:
            # No lot on the row (created before the product was batch-tracked) —
            # record_transaction's lot guard rejects it with LOT_REQUIRED.
            return None, None, None

        await self.db.execute(
            text(
                "UPDATE adjustment_orders SET lot_id = :lot_id, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"lot_id": lot_id, "id": str(adjustment_id), "tid": tenant_id},
        )
        return lot_id, lot_number, row.expiry_date

    async def transition_adjustment(
        self, user: Any, adjustment_id: UUID, next_state: str
    ) -> AdjustmentResponse:
        result = await self.db.execute(
            text("SELECT * FROM adjustment_orders WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
            {"id": str(adjustment_id), "tid": str(user.tenant_id)},
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

        # ── Adjustment self-approval engine — runs at submission (DRAFT → PENDING_APPROVAL) ──
        if row.status == "DRAFT" and next_state == "PENDING_APPROVAL":
            product_row = (
                await self.db.execute(
                    text("SELECT unit_price FROM products WHERE id = :pid"),
                    {"pid": str(row.product_id)},
                )
            ).fetchone()
            unit_price = (
                Decimal(str(product_row.unit_price))
                if product_row and product_row.unit_price is not None
                else Decimal("0")
            )
            quantity_abs = abs(Decimal(str(row.quantity_delta)))
            total_value = quantity_abs * unit_price

            await self.db.execute(
                text(
                    "UPDATE adjustment_orders "
                    "SET unit_price_at_submission = :up, total_value = :tv, updated_at = now() "
                    "WHERE id = :id AND tenant_id = :tid"
                ),
                {
                    "up": str(unit_price),
                    "tv": str(total_value),
                    "id": str(adjustment_id),
                    "tid": str(user.tenant_id),
                },
            )

            # Product override (Design B) — takes precedence over self-approval
            # and normal adjustment routing.
            _product_override_adj = await check_product_override(
                session=self.db,
                tenant_id=str(user.tenant_id),
                product_id=str(row.product_id),
                transaction_type="ADJUSTMENT",
                quantity=quantity_abs,
                total_value=total_value,
            )
            if _product_override_adj is not None:
                _product_override_adj = dict(_product_override_adj)
                _product_override_adj["product_id"] = str(row.product_id)
                await _apply_product_override_flag(
                    self.db,
                    user,
                    "adjustment",
                    adjustment_id,
                    _product_override_adj,
                )
                _override_step = (
                    await _override_resolution_steps(
                        self.db,
                        str(user.tenant_id),
                        _product_override_adj,
                        str(row.created_by),
                    )
                )[0]
                await self.db.execute(
                    text(
                        "UPDATE adjustment_orders "
                        "SET required_approver_position_id = :pos_id, "
                        "    required_approver_user_id = :user_id, "
                        "    required_approver_name = :name, "
                        "    approver_escalated = :escalated, "
                        "    updated_at = now() "
                        "WHERE id = :id AND tenant_id = :tid"
                    ),
                    {
                        "pos_id": _override_step.get("position_id"),
                        "user_id": _override_step.get("assigned_to_user_id"),
                        "name": _override_step.get("assigned_to_name"),
                        "escalated": _override_step.get("escalated", False),
                        "id": str(adjustment_id),
                        "tid": str(user.tenant_id),
                    },
                )
                can_self_approve = False
                route_to = _product_override_adj.get("approver_role_code")
                route_position = {
                    "approver_position_id": _override_step.get("position_id"),
                    "approver_user_id": _override_step.get("assigned_to_user_id"),
                    "approver_name": _override_step.get("assigned_to_name"),
                    "approver_position_title": _product_override_adj.get("approver_title"),
                    "escalated": _override_step.get("escalated", False),
                }
            else:
                can_self_approve, route_to, route_position = await check_adjustment_self_approval(
                    session=self.db,
                    tenant_id=user.tenant_id,
                    user=user,
                    reason_code=row.reason_code,
                    quantity=quantity_abs,
                    total_value=total_value,
                )

            if can_self_approve:
                quantity = (
                    -quantity_abs
                    if row.reason_code in _FORCE_NEGATIVE_REASONS
                    else Decimal(str(row.quantity_delta))
                )

                lot_id, lot_number, expiry_date = await self._adjustment_lot_for_post(
                    user, adjustment_id
                )

                tx_id = await record_transaction(
                    self.db,
                    tenant_id=str(user.tenant_id),
                    transaction_type="ADJUSTMENT",
                    product_id=str(row.product_id),
                    warehouse_id=str(row.warehouse_id),
                    quantity=quantity,
                    performed_by=str(user.user_id),
                    idempotency_key=f"adj:{adjustment_id}:self_approve",
                    reference_id=str(adjustment_id),
                    lot_id=lot_id,
                    lot_number=lot_number,
                    expiry_date=expiry_date,
                )

                await self.db.execute(
                    text(
                        "UPDATE adjustment_orders "
                        "SET status = 'POSTED', is_self_approved = TRUE, updated_at = now() "
                        "WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"id": str(adjustment_id), "tid": str(user.tenant_id)},
                )

                await write_to_outbox(
                    self.db,
                    str(user.tenant_id),
                    "AdjustmentApplied",
                    AdjustmentAppliedPayload(
                        adjustment_id=str(adjustment_id),
                        product_id=str(row.product_id),
                        warehouse_id=str(row.warehouse_id),
                        delta=float(quantity),
                    ),
                )

                await audit_log(
                    user,
                    "adjustment:self_approved",
                    {
                        "resource_type": "adjustment",
                        "resource_id": str(adjustment_id),
                        "quantity": str(quantity_abs),
                        "total_value": str(total_value),
                        "reason_code": row.reason_code,
                        "transaction_id": str(tx_id),
                        "lot_id": lot_id,
                        "policy": {
                            "role_code": str(user.role),
                            "level_number": getattr(user, "level_number", None),
                        },
                    },
                    "GRANTED",
                    "within_self_approval_limit",
                    db=self.db,
                )

                from datetime import datetime, timezone

                return AdjustmentResponse(
                    adjustment_id=adjustment_id,
                    status="POSTED",
                    quantity_delta=quantity,
                    created_at=datetime.now(timezone.utc),
                    is_self_approved=True,
                    total_value=total_value,
                    lot_id=UUID(lot_id) if lot_id else None,
                    lot_number=lot_number,
                    expiry_date=expiry_date,
                )
            # Not self-approved — fall through to PENDING_APPROVAL.
            # Log which role/position will handle approval so the audit trail is complete.
            if route_to:
                audit_context: dict[str, Any] = {
                    "resource_type": "adjustment",
                    "resource_id": str(adjustment_id),
                    "quantity": str(quantity_abs),
                    "total_value": str(total_value),
                    "reason_code": row.reason_code,
                    "required_role": route_to,
                }
                if route_position:
                    audit_context["routed_position"] = route_position
                await audit_log(
                    user,
                    "adjustment:routed",
                    audit_context,
                    "CONDITIONAL",
                    f"routed_to:{route_to}",
                    db=self.db,
                )

        # ── Product-override approval gate (MATRIX 1) ───────────────────────
        # When a Design-B override routed this adjustment to a specific
        # position/user, only that resolved approver (or, if escalated, any
        # active TA who isn't the creator) may move it to APPROVED. Normal
        # (non-override) adjustments keep their existing RBAC-only gate.
        if next_state == "APPROVED" and getattr(row, "product_override_applied", False):
            from fastapi import HTTPException

            caller_uid = str(user.user_id)
            caller_role = getattr(user, "role", "")
            is_own = str(getattr(row, "created_by", "") or "") == caller_uid
            required_uid = (
                str(row.required_approver_user_id) if row.required_approver_user_id else None
            )
            escalated = bool(getattr(row, "approver_escalated", False))

            allowed = (required_uid is not None and caller_uid == required_uid and not is_own) or (
                escalated and caller_role == "TA" and not is_own
            )
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "NOT_REQUIRED_APPROVER",
                        "message": (
                            f"Only {row.required_approver_name or 'the designated approver'} "
                            "can approve this adjustment."
                        ),
                        "required_approver_name": row.required_approver_name,
                    },
                )

        await self.db.execute(
            text(
                "UPDATE adjustment_orders SET status = :s, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid"
            ),
            {"s": next_state, "id": str(adjustment_id), "tid": str(user.tenant_id)},
        )

        if next_state == "POSTED":
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

        # Lot chosen or entered so far (nothing is posted on this path).
        shown_lot_id = getattr(row, "lot_id", None)
        shown_lot_number = getattr(row, "lot_number", None)
        shown_expiry_date = getattr(row, "expiry_date", None)
        if shown_lot_id is not None:
            lot_row = (
                await self.db.execute(
                    text(
                        "SELECT lot_number, expiry_date FROM stock_lots "
                        "WHERE id = :lid AND tenant_id = :tid"
                    ),
                    {"lid": str(shown_lot_id), "tid": str(user.tenant_id)},
                )
            ).fetchone()
            if lot_row is not None:
                shown_lot_number = lot_row.lot_number
                shown_expiry_date = lot_row.expiry_date

        from datetime import datetime, timezone

        return AdjustmentResponse(
            adjustment_id=adjustment_id,
            status=next_state,
            quantity_delta=Decimal(str(row.quantity_delta)),
            created_at=datetime.now(timezone.utc),
            is_self_approved=bool(row.is_self_approved),
            total_value=Decimal(str(row.total_value)) if row.total_value is not None else None,
            lot_id=shown_lot_id,
            lot_number=shown_lot_number,
            expiry_date=shown_expiry_date,
            auto_lot=bool(getattr(row, "auto_lot", False)),
        )

    async def get_adjustment_approval_info(
        self, user: Any, adjustment_id: UUID
    ) -> AdjustmentApprovalInfoResponse:
        """Return who must approve this adjustment and whether the caller can.

        Mirrors GET /transfers/{id}/approval-info — when a Design-B product
        override has routed the adjustment to a specific position/user,
        can_approve is gated on that resolved approver (or, if escalated,
        any active TA who isn't the creator). Adjustments without an
        override fall back to the normal adjustment:approve RBAC grant.
        """
        from fastapi import HTTPException

        row = (
            await self.db.execute(
                text(
                    "SELECT ao.id, ao.status, ao.created_by, ao.product_override_applied, "
                    "       ao.required_approver_user_id, ao.required_approver_name, "
                    "       ao.approver_escalated, ao.lot_id, ao.auto_lot, "
                    "       CASE WHEN ao.lot_id IS NOT NULL THEN sl.lot_number "
                    "            ELSE ao.lot_number END AS lot_number, "
                    "       CASE WHEN ao.lot_id IS NOT NULL THEN sl.expiry_date "
                    "            ELSE ao.expiry_date END AS expiry_date "
                    "FROM adjustment_orders ao "
                    "LEFT JOIN stock_lots sl ON sl.id = ao.lot_id "
                    "WHERE ao.id = :id AND ao.tenant_id = :tid"
                ),
                {"id": str(adjustment_id), "tid": str(user.tenant_id)},
            )
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Adjustment not found")

        caller_uid = str(user.user_id)
        caller_role = getattr(user, "role", "")
        is_own = str(row.created_by or "") == caller_uid
        required_uid = str(row.required_approver_user_id) if row.required_approver_user_id else None
        escalated = bool(row.approver_escalated)

        if row.product_override_applied:
            can_approve = (
                required_uid is not None and caller_uid == required_uid and not is_own
            ) or (escalated and caller_role == "TA" and not is_own)
            if escalated:
                step_label = (
                    f"Awaiting {row.required_approver_name or 'TA'} approval "
                    "(escalated — creator cannot self-approve)"
                )
            elif required_uid:
                step_label = f"Awaiting {row.required_approver_name} approval"
            else:
                step_label = "Position vacant — no available approver"
        else:
            from shared.permissions.middleware import check_permission
            from shared.permissions.registry import PERMISSIONS

            result = await check_permission(
                user,
                PERMISSIONS.ADJUSTMENT_APPROVE,
                {"tenant_id": str(user.tenant_id)},
            )
            can_approve = bool(result.allowed) and not is_own
            step_label = None

        return AdjustmentApprovalInfoResponse(
            adjustment_id=adjustment_id,
            status=row.status,
            product_override_applied=bool(row.product_override_applied),
            required_approver_user_id=UUID(required_uid) if required_uid else None,
            required_approver_name=row.required_approver_name,
            approver_escalated=escalated,
            can_approve=can_approve,
            step_label=step_label,
            lot_id=row.lot_id,
            lot_number=row.lot_number,
            expiry_date=row.expiry_date,
            auto_lot=bool(row.auto_lot),
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

    async def get_count_session(self, user: Any, session_id: UUID) -> CountSessionResponse:
        result = await self.db.execute(
            text("SELECT * FROM count_sessions WHERE id = :id AND tenant_id = :tid"),
            {"id": str(session_id), "tid": str(user.tenant_id)},
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

    async def _transfer_line_items(self, transfer_id: Any) -> list[TransferLineItem]:
        """The lines of one transfer with product name/SKU, for list and detail responses."""
        line_rows = (
            await self.db.execute(
                text("""
                SELECT
                    tol.id               AS line_id,
                    tol.product_id,
                    p.name               AS product_name,
                    p.sku,
                    tol.quantity,
                    COALESCE(p.unit, '') AS uom
                FROM transfer_order_lines tol
                JOIN products p ON p.id = tol.product_id
                WHERE tol.transfer_order_id = :xfer_id
            """),
                {"xfer_id": str(transfer_id)},
            )
        ).fetchall()
        return [
            TransferLineItem(
                line_id=line.line_id,
                product_id=line.product_id,
                product_name=line.product_name,
                sku=line.sku,
                quantity=Decimal(str(line.quantity)),
                uom=line.uom,
            )
            for line in line_rows
        ]

    async def _transfer_scope(self, user: Any) -> Optional[set[str]]:
        """The lowercased node subtree whose transfers the caller sees; None means
        the whole tenant. Same rules as transfer_discrepancies.list_discrepancies:
          WM / LM / SA_GT / RT / RM  their subtree; no node -> empty set (nothing)
          TA / NM / SA / AU          the whole tenant
        """
        role = getattr(user, "role", None)
        node_id = getattr(user, "warehouse_id", None)
        if role in _FACILITY_SCOPED_ROLES and not node_id:
            return set()
        if node_id and role in _FACILITY_SCOPED_ROLES:
            return await _subtree(self.db, str(user.tenant_id), node_id)
        return None

    async def list_transfers(
        self, user: Any, page: int = 1, limit: int = 50
    ) -> list[TransferListItem]:
        """List transfers in the caller's scope (see _transfer_scope) — a transfer
        is in scope when either end is in the caller's node subtree, or one of
        its approval steps names the caller (_APPROVER_SCOPE_SQL).
        """
        scope = await self._transfer_scope(user)
        if scope is not None and not scope:
            return []

        offset = (page - 1) * limit
        params: dict = {"tid": str(user.tenant_id), "offset": offset, "limit": limit}

        wh_filter = ""
        if scope is not None:
            wh_filter = (
                "AND (to_.from_warehouse_id = ANY(:subtree) "
                "OR to_.to_warehouse_id = ANY(:subtree) "
                f"OR {_APPROVER_SCOPE_SQL})"
            )
            params["subtree"] = sorted(scope)
            # A separate text[] param: :subtree is bound as uuid[] above.
            params["step_nodes"] = sorted(scope)
            params["uid"] = str(user.user_id).lower()

        sql = text(f"""
            SELECT
                to_.id                 AS transfer_id,
                to_.transfer_type,
                to_.status,
                to_.from_warehouse_id,
                COALESCE(fw.name, fw_n.name) AS from_warehouse_name,
                to_.to_warehouse_id,
                COALESCE(tw.name, tw_n.name) AS to_warehouse_name,
                to_.created_by::text              AS created_by,
                to_.created_by_authority_level,
                to_.created_at,
                to_.updated_at,
                to_.is_self_approved,
                to_.current_approval_step,
                to_.resolved_approval_steps
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
            _rs = r.resolved_approval_steps
            if isinstance(_rs, str):
                try:
                    _rs = _json.loads(_rs)
                except Exception:
                    _rs = None
            _total_steps = len(_rs) if _rs else 1

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
                    created_by_authority_level=r.created_by_authority_level,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    is_self_approved=bool(r.is_self_approved),
                    current_step=r.current_approval_step or 1,
                    total_steps=_total_steps,
                    lines=await self._transfer_line_items(r.transfer_id),
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
                ao.notes,
                ao.is_self_approved,
                ao.lot_id,
                CASE WHEN ao.lot_id IS NOT NULL THEN sl.lot_number
                     ELSE ao.lot_number END  AS lot_number,
                CASE WHEN ao.lot_id IS NOT NULL THEN sl.expiry_date
                     ELSE ao.expiry_date END AS expiry_date,
                ao.auto_lot
            FROM adjustment_orders ao
            JOIN products          p  ON p.id  = ao.product_id
            LEFT JOIN warehouses   w  ON w.id  = ao.warehouse_id
            LEFT JOIN organization_node wn ON wn.id = ao.warehouse_id
            LEFT JOIN stock_lots   sl ON sl.id = ao.lot_id
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
                is_self_approved=bool(r.is_self_approved),
                lot_id=r.lot_id,
                lot_number=r.lot_number,
                expiry_date=r.expiry_date,
                auto_lot=bool(r.auto_lot),
            )
            for r in rows
        ]
