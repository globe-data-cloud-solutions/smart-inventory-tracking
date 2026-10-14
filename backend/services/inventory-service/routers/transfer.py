from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db_session
from dependencies import get_current_user
from shared.permissions.middleware import require_permission
from shared.permissions.plan_middleware import check_plan
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.inventory import (
    ApprovalInfoResponse,
    ReceiveTransferRequest,
    ResolveDiscrepancyRequest,
    TransferApproveRequest,
    TransferDiscrepancyListItem,
    TransferDiscrepancyOut,
    TransferListItem,
    TransferOrderRequest,
    TransferOrderResponse,
    TransferTransitionRequest,
)
from services import transfer_discrepancies
from services.inventory_service import InventoryService

router = APIRouter()

# GAP 1 fix: each transfer type has a different first post-DRAFT state.
# "SUBMITTED" is not a valid state in any machine — it was the old placeholder.
_SUBMIT_NEXT_STATUS: dict[str, str] = {
    "PULL":   "PENDING_REVIEW",
    "PUSH":   "PENDING_APPROVAL",
    "SISTER": "PENDING_SOURCE_CONFIRM",
}


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


# Fixed path — declared before every /{transfer_id} route (CLAUDE.md §7).
@router.get("/discrepancies", response_model=SuccessResponse[List[TransferDiscrepancyListItem]])
@require_permission(PERMISSIONS.TRANSFER_LIST)
async def list_discrepancies(
    status: Optional[Literal["OPEN", "RESOLVED"]] = Query(None),
    warehouse_id: Optional[UUID] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TransferDiscrepancyListItem]]:
    """Transfer discrepancies of the tenant, newest first (at most 200).

    status filters OPEN / RESOLVED; warehouse_id matches the source or the
    destination. A WM only sees transfers touching its own warehouse, as on
    GET /transfers.
    """
    result = await transfer_discrepancies.list_discrepancies(
        db, user, status=status, warehouse_id=warehouse_id
    )
    return SuccessResponse(data=result)


@router.post("/", status_code=201, response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_CREATE)
async def create_transfer(
    body: TransferOrderRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    if body.transfer_type == "SISTER":
        await check_plan(user, "transfer:sister", db)
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
    transfer = await svc.get_transfer(user, transfer_id)
    next_status = _SUBMIT_NEXT_STATUS.get(transfer.transfer_type)
    if next_status is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNKNOWN_TRANSFER_TYPE", "message": f"Unknown transfer type: {transfer.transfer_type}"},
        )
    result = await svc.transition_transfer(user, transfer_id, next_status)
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/review", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_APPROVE)
async def review_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Advance PENDING_REVIEW → PENDING_APPROVAL for PULL transfers.

    Called by the reviewer (RM or NM) after inspecting a PULL request before
    it enters the formal approval queue.  This transition is only valid for PULL
    — PUSH and SISTER skip PENDING_REVIEW entirely.
    """
    svc = InventoryService(db)
    transfer = await svc.get_transfer(user, transfer_id)
    if transfer.transfer_type != "PULL":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TRANSFER_TYPE",
                "message": "/review is only valid for PULL transfers. PUSH and SISTER transfers have no PENDING_REVIEW state.",
            },
        )
    result = await svc.transition_transfer(user, transfer_id, "PENDING_APPROVAL")
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/approve", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_APPROVE)
async def approve_transfer(
    transfer_id: UUID,
    body: Optional[TransferApproveRequest] = Body(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Approve a transfer. The optional body lets the FINAL approver choose lots.

    A selection that differs from the engine's order is an override: FEFO needs
    dispatch:fefo_override (and a reason), FIFO/LIFO needs dispatch:lot_select at
    the source warehouse. Both are resolved here and enforced in transfer_lots.
    """
    svc = InventoryService(db)
    if body is None or not body.lot_selections:
        result = await svc.transition_transfer(user, transfer_id, "APPROVED")
        return SuccessResponse(data=result)

    tid = str(user.tenant_id)
    transfer_row = (await db.execute(
        text("SELECT from_warehouse_id FROM transfer_orders WHERE id = :id AND tenant_id = :tid"),
        {"id": str(transfer_id), "tid": tid},
    )).fetchone()
    if not transfer_row:
        raise HTTPException(status_code=404, detail="Transfer not found")

    from shared.permissions.middleware import check_permission

    # A CONDITIONAL grant returns allowed=True; the FEFO reason rule covers it.
    can_fefo_override = (await check_permission(
        user, PERMISSIONS.DISPATCH_FEFO_OVERRIDE, {"tenant_id": tid}, db=db
    )).allowed
    can_lot_select = (await check_permission(
        user,
        PERMISSIONS.DISPATCH_LOT_SELECT,
        {"tenant_id": tid, "warehouse_id": str(transfer_row.from_warehouse_id)},
        db=db,
    )).allowed

    result = await svc.transition_transfer(
        user,
        transfer_id,
        "APPROVED",
        lot_selections=body.lot_selections,
        override_reason=body.override_reason,
        can_fefo_override=can_fefo_override,
        can_lot_select=can_lot_select,
    )
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/dispatch", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_DISPATCH)
async def dispatch_transfer(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Advance APPROVED → ISSUED. Source warehouse only (warehouse_id ABAC).
    Writes NO ledger entries — source on_hand was already deducted at APPROVED via TRANSFER_OUT.
    In-transit tracking uses transfer_orders.status in analytics queries, not ledger entries.
    """
    svc = InventoryService(db)
    result = await svc.dispatch_transfer(user, transfer_id)
    return SuccessResponse(data=result)


@router.post("/{transfer_id}/receive", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_RECEIVE)
async def receive_transfer(
    transfer_id: UUID,
    body: Optional[ReceiveTransferRequest] = Body(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Advance IN_TRANSIT → RECEIVED. Destination warehouse only (warehouse_id ABAC).
    Writes TRANSFER_IN ledger entries, credits destination balance, and fires
    StockTransferred outbox events — all in the same database transaction.

    No body: every line is received in full. The optional body confirms the
    received quantity per allocated lot (batch line) or per line (non-batch
    line) and must list each exactly once. A quantity below what was sent needs
    a reason (SHORT | DAMAGED | WRONG_LOT): only the received quantity is
    credited and the shortfall is returned in `discrepancies`. The transfer
    ends in RECEIVED either way.
    """
    svc = InventoryService(db)
    result = await svc.receive_transfer(user, transfer_id, body)
    return SuccessResponse(data=result)


@router.post(
    "/{transfer_id}/discrepancies/{discrepancy_id}/resolve",
    response_model=SuccessResponse[TransferDiscrepancyOut],
)
@require_permission(PERMISSIONS.TRANSFER_RESOLVE_DISCREPANCY)
async def resolve_discrepancy(
    transfer_id: UUID,
    discrepancy_id: UUID,
    body: ResolveDiscrepancyRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferDiscrepancyOut]:
    """Resolve one OPEN discrepancy: WRITTEN_OFF | RETURNED | ARRIVED_LATE |
    RECEIVED_AS_LOT. Ledger rows, the OPEN -> RESOLVED update and the audit row
    commit together; any error rolls all of them back. TA / NM tenant-wide,
    RM within its node subtree.
    """
    result = await transfer_discrepancies.resolve_discrepancy(
        db, user, transfer_id, discrepancy_id, body
    )
    return SuccessResponse(data=result)


@router.patch("/{transfer_id}", response_model=SuccessResponse[TransferOrderResponse])
@require_permission(PERMISSIONS.TRANSFER_VIEW, read_only_force_write=True)
async def transition_transfer(
    transfer_id: UUID,
    body: TransferTransitionRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferOrderResponse]:
    """Generic state transition — delegates to specialized methods for ledger-writing states.

    next_status == "ISSUED":   calls dispatch_transfer() — ABAC check, no ledger entries.
    next_status == "RECEIVED": calls receive_transfer()  — books TRANSFER_IN at destination
                               (always a full receipt; quantities go through POST /receive).
    next_status == "PARTIALLY_RECEIVED": 422 — a short receipt is POST /receive with a body.
    All other statuses:        calls transition_transfer() — pure status update.
    """
    if body.next_status == "PARTIALLY_RECEIVED":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PARTIAL_RECEIPT_NOT_SUPPORTED",
                "detail": "Use POST /transfers/{id}/receive with the received quantities.",
            },
        )

    svc = InventoryService(db)

    # Destructive transitions require elevated permissions beyond transfer:view.
    from shared.permissions.middleware import check_permission
    from shared.permissions.registry import PERMISSIONS as _P

    if body.next_status == "REJECTED":
        result = await check_permission(user, _P.TRANSFER_REJECT, {"tenant_id": str(user.tenant_id)}, db=db)
        if not result.allowed:
            raise HTTPException(status_code=403, detail={"code": result.reason, "action": _P.TRANSFER_REJECT.id})
    elif body.next_status == "CANCELLED":
        result = await check_permission(user, _P.TRANSFER_CANCEL, {"tenant_id": str(user.tenant_id)}, db=db)
        if not result.allowed:
            raise HTTPException(status_code=403, detail={"code": result.reason, "action": _P.TRANSFER_CANCEL.id})

    if body.next_status == "ISSUED":
        result = await svc.dispatch_transfer(user, transfer_id)
    elif body.next_status == "RECEIVED":
        result = await svc.receive_transfer(user, transfer_id)
    else:
        result = await svc.transition_transfer(user, transfer_id, body.next_status)
    return SuccessResponse(data=result)


@router.get("/{transfer_id}/approval-info",
            response_model=SuccessResponse[ApprovalInfoResponse])
@require_permission(PERMISSIONS.TRANSFER_VIEW)
async def get_approval_info(
    transfer_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ApprovalInfoResponse]:
    """Return approval requirements for a transfer.

    Tells the frontend who must approve, whether it auto-approves, and whether
    the current user has sufficient authority to approve.
    """
    from decimal import Decimal
    from sqlalchemy import text
    from services.approval_service import resolve_approval, ROLE_AUTHORITY_LEVEL

    import json as _json
    transfer_row = (await db.execute(
        text(
            "SELECT transfer_type, created_by, created_by_authority_level, "
            "resolved_approval_steps, current_approval_step "
            "FROM transfer_orders WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": str(transfer_id), "tid": str(user.tenant_id)},
    )).fetchone()
    if not transfer_row:
        raise HTTPException(status_code=404, detail="Transfer not found")

    # ── Session 6: dynamic routing via resolved_approval_steps ────────────────
    resolved_steps = transfer_row.resolved_approval_steps
    if resolved_steps:
        if isinstance(resolved_steps, str):
            resolved_steps = _json.loads(resolved_steps)
        steps: list[dict] = resolved_steps if isinstance(resolved_steps, list) else []
        cur_idx = max(0, (transfer_row.current_approval_step or 1) - 1)
        cur_step = steps[cur_idx] if cur_idx < len(steps) else (steps[-1] if steps else {})

        caller_uid      = str(user.user_id)
        assignee_uid    = cur_step.get("assigned_to_user_id")
        exec_mode       = (cur_step.get("execution_mode") or "sequential").lower()
        all_holders     = cur_step.get("all_holders") or []
        holder_count    = cur_step.get("holder_count") or (len(all_holders) if all_holders else (1 if assignee_uid else 0))
        position_title  = cur_step.get("position_title", "Approver")
        is_own_transfer = (
            transfer_row.created_by is not None
            and str(transfer_row.created_by) == caller_uid
        )

        # Compute can_approve for dynamic routing.
        # For ANY mode: caller must be one of the listed holders AND not the creator.
        # Creator self-approval is already blocked by CANNOT_APPROVE_OWN_TRANSFER in the
        # APPROVED transition, but we also reflect it here so the UI shows correctly.
        if exec_mode == "any":
            holder_uids     = {str(h.get("user_id", "")) for h in all_holders}
            can_approve_dyn = bool(holder_uids and caller_uid in holder_uids and not is_own_transfer)
        else:
            can_approve_dyn = bool(assignee_uid and caller_uid == assignee_uid and not is_own_transfer)

        # BUG 5: TA (Tenant Admin, system_role='TA') can approve any transfer they didn't
        # create, regardless of who the specifically assigned approver is.  This prevents
        # TA from being locked out when a transfer escalated to them shows can_approve=False
        # because the dynamic step has no holders or a different assignee.
        caller_role = getattr(user, "role", "")
        if caller_role == "TA" and not is_own_transfer:
            can_approve_dyn = True

        # Compute human-readable status_label.
        # For ANY mode, exclude the TRANSFER CREATOR from the "available approvers" count
        # shown in the label so the label reflects who can actually act (not the creator).
        transfer_creator_uid = str(transfer_row.created_by) if transfer_row.created_by else ""
        non_creator_holders = [
            h for h in all_holders
            if str(h.get("user_id", "")) != transfer_creator_uid
        ]
        display_count = len(non_creator_holders) if exec_mode == "any" else holder_count

        is_vacant = cur_step.get("is_vacant", False)
        escalated  = cur_step.get("escalated", False)
        esc_name   = cur_step.get("assigned_to_name") or "an escalated approver"
        # BUG 4: distinguish "position vacant → escalating" from "self-approval → escalating".
        # is_vacant=True means the position had no holder at all.
        # escalated=True with is_vacant=False means the original holder was the creator.
        if is_vacant and escalated:
            status_label: str | None = f"Position vacant — escalating to {esc_name}"
        elif is_vacant:
            status_label = f"Position vacant — no available approver"
        elif escalated:
            status_label = f"Awaiting {esc_name} approval (escalated — creator cannot self-approve)"
        elif exec_mode == "any" and display_count > 1:
            status_label = f"Any {position_title} can approve ({display_count} approvers available)"
        elif exec_mode == "any" and display_count == 1:
            approver_name = non_creator_holders[0]["name"] if non_creator_holders else (assignee_uid or position_title)
            status_label = f"Awaiting {approver_name} approval"
        elif exec_mode == "any" and display_count == 0 and all_holders:
            # Only the creator holds the position — they can't self-approve
            status_label = f"Only you hold '{position_title}' — cannot self-approve"
        elif cur_step.get("assigned_to_name"):
            status_label = f"Awaiting {cur_step['assigned_to_name']} approval"
        else:
            status_label = f"Awaiting {position_title} approval"

        _cur_seq = cur_step.get("sequence", 1)
        _total   = len(steps)
        return SuccessResponse(data=ApprovalInfoResponse(
            transfer_id=transfer_id,
            required_authority_level=1,
            required_role_display=position_title,
            is_auto_approve=False,
            can_approve=can_approve_dyn,
            reason=f"Step {_cur_seq} of {_total}: {position_title} approval required.",
            current_step=_cur_seq,
            total_steps=_total,
            current_approver_user_id=assignee_uid,
            current_approver_name=cur_step.get("assigned_to_name"),
            current_approver_position_title=position_title,
            execution_mode=exec_mode,
            sla_hours=cur_step.get("sla_hours"),
            is_dynamic_routing=True,
            holder_count=holder_count,
            all_holders=all_holders,
            status_label=status_label,
            step_label=f"Step {_cur_seq} of {_total}" if _total > 1 else None,
        ))

    # ── Legacy path: role-level routing (old approval_rule / authority_level) ─
    lines = (await db.execute(
        text(
            "SELECT quantity FROM transfer_order_lines "
            "WHERE transfer_order_id = :xfer_id AND tenant_id = :tid"
        ),
        {"xfer_id": str(transfer_id), "tid": str(user.tenant_id)},
    )).fetchall()

    total_qty = sum(Decimal(str(l.quantity)) for l in lines) if lines else Decimal("0")

    creator_level: int | None = (
        int(transfer_row.created_by_authority_level)
        if transfer_row.created_by_authority_level is not None
        else None
    )

    _tenant_result = await db.execute(
        text("SELECT approval_thresholds FROM tenants WHERE id = :tid"),
        {"tid": str(user.tenant_id)},
    )
    _rules_json = _tenant_result.scalar()
    simple_mode = _rules_json.get("simple_mode", True) if isinstance(_rules_json, dict) else True

    decision = await resolve_approval(
        db, str(user.tenant_id), transfer_row.transfer_type, total_qty,
        requester_authority_level=creator_level,
        simple_mode=simple_mode,
    )

    caller_level = ROLE_AUTHORITY_LEVEL.get(getattr(user, "role", ""), 5)
    is_own_transfer = (
        transfer_row.created_by is not None
        and str(transfer_row.created_by) == str(user.user_id)
    )
    can_approve = (not is_own_transfer) and (caller_level <= decision.required_authority_level)

    return SuccessResponse(data=ApprovalInfoResponse(
        transfer_id=transfer_id,
        required_authority_level=decision.required_authority_level,
        required_role_display=decision.required_role_display,
        is_auto_approve=decision.is_auto_approve,
        can_approve=can_approve,
        reason=decision.reason,
    ))


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
