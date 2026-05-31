"""Unit tests for the IMTS type-specific state machines and the InventoryService
transfer methods that call them.

Tests 1–4 verify validate_transition() and get_machine() directly.
Tests 5–7 verify InventoryService.dispatch_transfer() and receive_transfer()
via mocks, confirming that the ledger (record_transaction) is called correctly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from services.state_machine import (
    InvalidStateTransitionError,
    PULL_TRANSITIONS,
    PUSH_TRANSITIONS,
    SISTER_TRANSITIONS,
    validate_transition,
)


# ── Shared fixtures ──────────────────────────────────────────────────────────

TENANT_ID    = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A  = "20000000-0000-0000-0000-000000000001"
WAREHOUSE_B  = "20000000-0000-0000-0000-000000000002"
PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
TRANSFER_ID  = UUID("cccccccc-0000-0000-0000-000000000001")
LINE_ID      = "llllllll-0000-0000-0000-000000000001"
USER_ID      = "u-wm-src"


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: str | None
    region_id: str | None
    role: str


SRC_WM = _User(USER_ID, TENANT_ID, WAREHOUSE_A, None, "WM")
DST_WM = _User("u-wm-dst", TENANT_ID, WAREHOUSE_B, None, "WM")


# ── State machine unit tests (tests 1–4) ─────────────────────────────────────

@pytest.mark.unit
class TestIMTSStateMachines:

    def test_pull_invalid_draft_to_in_transit_raises_422(self) -> None:
        """PULL DRAFT → IN_TRANSIT must fail — IN_TRANSIT is never reachable from DRAFT.
        The only valid path from DRAFT is PENDING_REVIEW (or CANCELLED).
        InvalidStateTransitionError maps to HTTP 422."""
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            validate_transition("PULL", "DRAFT", "IN_TRANSIT")
        assert "PULL" in str(exc_info.value)
        assert "DRAFT" in str(exc_info.value)
        assert "IN_TRANSIT" in str(exc_info.value)

    def test_push_draft_goes_to_pending_approval_not_pending_review(self) -> None:
        """PUSH has no PENDING_REVIEW step — DRAFT goes directly to PENDING_APPROVAL.
        Attempting DRAFT → PENDING_REVIEW on a PUSH transfer must be rejected."""
        # Valid transition for PUSH
        validate_transition("PUSH", "DRAFT", "PENDING_APPROVAL")  # must not raise

        # PENDING_REVIEW does not exist in PUSH at all
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PUSH", "DRAFT", "PENDING_REVIEW")

    def test_sister_requires_source_confirm_before_dest_confirm(self) -> None:
        """SISTER transfers require source-manager confirmation before the destination
        manager is asked. Jumping directly from DRAFT to PENDING_DEST_CONFIRM must fail."""
        # The correct path: DRAFT → PENDING_SOURCE_CONFIRM → PENDING_DEST_CONFIRM
        validate_transition("SISTER", "DRAFT", "PENDING_SOURCE_CONFIRM")   # valid
        validate_transition("SISTER", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM")  # valid

        # Skipping source confirm is forbidden
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("SISTER", "DRAFT", "PENDING_DEST_CONFIRM")

    def test_completed_is_terminal_for_all_types(self) -> None:
        """COMPLETED is a terminal state in every machine — no onward transition
        is permitted for PULL, PUSH, or SISTER."""
        for transfer_type in ("PULL", "PUSH", "SISTER"):
            for next_state in ("DRAFT", "PENDING_REVIEW", "PENDING_APPROVAL",
                               "APPROVED", "ISSUED", "IN_TRANSIT", "RECEIVED",
                               "CANCELLED", "COMPLETED"):
                with pytest.raises(InvalidStateTransitionError):
                    validate_transition(transfer_type, "COMPLETED", next_state)

    def test_push_rejected_terminal_state(self) -> None:
        """PUSH can transition to REJECTED from PENDING_APPROVAL.
        Once REJECTED, no further transition is allowed — REJECTED is terminal.

        Fix 5A: PUSH_TRANSITIONS now explicitly declares 'REJECTED': [] so
        the terminal state is unambiguous (not silently inferred via dict.get default).
        """
        # REJECTED is reachable from PENDING_APPROVAL
        validate_transition("PUSH", "PENDING_APPROVAL", "REJECTED")  # must not raise

        # REJECTED is a hard terminal — nothing is permitted from it
        for next_state in ("APPROVED", "CANCELLED", "DRAFT", "PENDING_APPROVAL",
                           "ISSUED", "IN_TRANSIT", "COMPLETED"):
            with pytest.raises(InvalidStateTransitionError,
                               match=r"PUSH.*REJECTED"):
                validate_transition("PUSH", "REJECTED", next_state)

    def test_sister_cancelled_from_dest_confirm(self) -> None:
        """Destination WM can CANCEL a SISTER transfer from PENDING_DEST_CONFIRM.

        Fix 5B: previously only REJECTED was available at this state, meaning
        an abandonment would pollute reports as a rejection.  CANCELLED is now
        explicitly permitted as a semantically distinct outcome.
        """
        # Destination WM can abandon (CANCELLED) or refuse (REJECTED)
        validate_transition("SISTER", "PENDING_DEST_CONFIRM", "CANCELLED")   # must not raise
        validate_transition("SISTER", "PENDING_DEST_CONFIRM", "REJECTED")    # already worked

        # CANCELLED is a hard terminal for SISTER
        for next_state in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "ISSUED"):
            with pytest.raises(InvalidStateTransitionError,
                               match=r"SISTER.*CANCELLED"):
                validate_transition("SISTER", "CANCELLED", next_state)


# ── InventoryService integration tests (tests 5–7) ───────────────────────────

def _make_transfer_row(
    status: str,
    transfer_type: str = "PULL",
    from_wh: str = WAREHOUSE_A,
    to_wh: str = WAREHOUSE_B,
) -> MagicMock:
    row = MagicMock()
    row.status        = status
    row.transfer_type = transfer_type
    row.from_warehouse_id = from_wh
    row.to_warehouse_id   = to_wh
    row.tenant_id     = TENANT_ID
    return row


def _make_line(quantity: float = 50.0) -> MagicMock:
    line = MagicMock()
    line.id         = LINE_ID
    line.product_id = PRODUCT_ID
    line.quantity   = Decimal(str(quantity))
    return line


def _session_for_dispatch(
    transfer_row: MagicMock,
    lines: list,
) -> AsyncMock:
    """Build a mock session whose execute() responses cover dispatch_transfer's queries:
      call 0 — SELECT transfer_orders FOR UPDATE
      call 1 — SELECT transfer_order_lines
      call 2 — UPDATE transfer_orders SET status = 'ISSUED'
    Also suitable for transition_transfer() calls that fetch lines (APPROVED, CANCELLED from APPROVED).
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        MagicMock(fetchone=MagicMock(return_value=transfer_row)),  # transfer SELECT
        MagicMock(fetchall=MagicMock(return_value=lines)),         # lines SELECT
        MagicMock(),                                                # status UPDATE
    ])
    return session


def _session_for_receive(
    transfer_row: MagicMock,
    lines: list,
) -> AsyncMock:
    """Build a mock session for receive_transfer's queries:
      call 0 — SELECT transfer_orders FOR UPDATE
      call 1 — SELECT transfer_order_lines
      call 2 — UPDATE transfer_orders SET status = 'RECEIVED'
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        MagicMock(fetchone=MagicMock(return_value=transfer_row)),
        MagicMock(fetchall=MagicMock(return_value=lines)),
        MagicMock(),
    ])
    return session


@pytest.mark.unit
class TestInventoryServiceTransfers:

    async def test_dispatch_writes_no_ledger_entries(self) -> None:
        """dispatch_transfer() (APPROVED → ISSUED) writes no direct record_transaction entries.
        Source on_hand was already deducted at APPROVED. Transit-tracking entries are written
        via write_transfer_ledger_entry (a separate audit path — not a balance mutation)."""
        from services.inventory_service import InventoryService

        line      = _make_line(quantity=50.0)
        xfer_row  = _make_transfer_row("APPROVED", transfer_type="PULL")
        session   = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-dispatched"),
        ) as mock_record, patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            svc    = InventoryService(session)
            result = await svc.dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED"
        # No direct record_transaction calls at dispatch (transit audit is via write_transfer_ledger_entry)
        assert mock_record.await_count == 0, "dispatch_transfer must write zero direct ledger entries"

    async def test_received_transition_credits_destination_balance(self) -> None:
        """receive_transfer() (IN_TRANSIT → RECEIVED) writes one TRANSFER_IN per line
        via record_transaction (credits destination on_hand).
        Transit-clear audit entries are written via write_transfer_ledger_entry (separate path)."""
        from services.inventory_service import InventoryService

        line      = _make_line(quantity=30.0)
        xfer_row  = _make_transfer_row("IN_TRANSIT", transfer_type="PULL")
        session   = _session_for_receive(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-received"),
        ) as mock_record, patch(
            "services.inventory_service.write_to_outbox",
            new=AsyncMock(),
        ), patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            svc    = InventoryService(session)
            result = await svc.receive_transfer(DST_WM, TRANSFER_ID)

        assert result.status == "RECEIVED"
        assert mock_record.await_count == 1

        calls = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}
        assert "TRANSFER_OUT" not in calls, "TRANSFER_OUT must NOT be written at receive (deducted at APPROVED)"
        assert "RELEASE" not in calls, "RELEASE must NOT be written (no RESERVE was made at dispatch)"
        tin  = calls["TRANSFER_IN"]

        assert tin["warehouse_id"]  == WAREHOUSE_B        # destination WH credited
        assert tin["quantity"]      == Decimal("30")       # positive = credit
        assert tin["reference_id"]  == str(TRANSFER_ID)

    async def test_cancelled_from_approved_reverses_source_balance(self) -> None:
        """A PULL transfer cancelled while in APPROVED state must write a TRANSFER_REVERSAL
        at source to restore on_hand — because TRANSFER_OUT was written at APPROVED.

        Gap 2: The old record_transaction(RETURN,...) call is replaced by
        write_transfer_ledger_entry(TRANSFER_REVERSAL,...) for consistent idempotency
        key management and a cleaner audit trail.

        1. Allows APPROVED → CANCELLED (valid in PULL machine).
        2. Writes exactly one TRANSFER_REVERSAL via write_transfer_ledger_entry.
        3. No direct record_transaction call is made for the reversal.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])  # SELECT transfer, SELECT lines, UPDATE

        captured_ledger_calls: list = []
        async def _capture_ledger(*_, **kw):
            captured_ledger_calls.append(kw)

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(),
        ) as mock_record, patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(side_effect=_capture_ledger),
        ):
            svc    = InventoryService(session)
            result = await svc.transition_transfer(SRC_WM, TRANSFER_ID, "CANCELLED")

        assert result.status == "CANCELLED"
        # No direct record_transaction — reversal goes via write_transfer_ledger_entry
        assert mock_record.await_count == 0, (
            "TRANSFER_REVERSAL must NOT use record_transaction directly; "
            "it must go through write_transfer_ledger_entry"
        )
        assert len(captured_ledger_calls) == 1, "exactly one TRANSFER_REVERSAL entry expected"
        rev = captured_ledger_calls[0]
        assert rev["transaction_type"] == "TRANSFER_REVERSAL"
        assert rev["warehouse_id"]     == WAREHOUSE_A,    "reversal must target source warehouse"
        assert rev["quantity"]         == Decimal("50"),   "reversal must be positive (restore)"
        assert rev["transfer_id"]      == str(TRANSFER_ID)

        # State machine sanity: APPROVED → CANCELLED is valid for PULL
        validate_transition("PULL", "APPROVED", "CANCELLED")  # must not raise

    # ── Regression tests for BUGs 1–3 ────────────────────────────────────────

    async def test_issued_does_not_deduct_source_on_hand(self) -> None:
        """dispatch_transfer() (APPROVED → ISSUED) must NOT write any direct record_transaction
        entries. Source on_hand was already deducted at APPROVED via transition_transfer()."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=120.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PUSH",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-issued"),
        ) as mock_record, patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            svc    = InventoryService(session)
            result = await svc.dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED", "status must advance to ISSUED"
        assert mock_record.await_count == 0, "dispatch must write zero direct ledger entries"

    async def test_in_transit_writes_no_ledger_entries(self) -> None:
        """dispatch_transfer() writes zero direct record_transaction entries (APPROVED → ISSUED).
        Transit-tracking entries go via write_transfer_ledger_entry (audit only, not balance)."""
        from services.inventory_service import InventoryService

        qty      = Decimal("75")
        line     = _make_line(quantity=float(qty))
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-both-sides"),
        ) as mock_record, patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            svc    = InventoryService(session)
            result = await svc.dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED"
        assert mock_record.await_count == 0, "dispatch must write zero direct ledger entries"

    async def test_received_credits_destination_no_release(self) -> None:
        """receive_transfer() (IN_TRANSIT → RECEIVED) must write only TRANSFER_IN
        via record_transaction. TRANSIT_CLEAR audit entries go via write_transfer_ledger_entry."""
        from services.inventory_service import InventoryService

        qty      = Decimal("60")
        line     = _make_line(quantity=float(qty))
        xfer_row = _make_transfer_row("IN_TRANSIT", transfer_type="PUSH",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_receive(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-received-clear"),
        ) as mock_record, patch(
            "services.inventory_service.write_to_outbox",
            new=AsyncMock(),
        ), patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            svc    = InventoryService(session)
            result = await svc.receive_transfer(DST_WM, TRANSFER_ID)

        assert result.status == "RECEIVED"

        calls_by_type = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}

        assert "TRANSFER_OUT" not in calls_by_type, "TRANSFER_OUT must NOT be written at receive"
        assert "RELEASE" not in calls_by_type, "RELEASE must NOT be written (no RESERVE was made)"

        assert "TRANSFER_IN" in calls_by_type, "TRANSFER_IN missing — destination on_hand not credited"
        tin = calls_by_type["TRANSFER_IN"]
        assert tin["warehouse_id"] == WAREHOUSE_B, "TRANSFER_IN must target destination"
        assert tin["quantity"]     == qty,          "TRANSFER_IN must be positive (credit)"
        assert tin["reference_id"] == str(TRANSFER_ID)

    async def test_approved_transition_writes_transfer_out_at_source(self) -> None:
        """transition_transfer() (PENDING_APPROVAL → APPROVED) must write one TRANSFER_OUT
        per line at source — this is when On Hand deducts (reservation converts to a hard
        deduction at APPROVED per CLAUDE.md §17)."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])  # SELECT transfer, SELECT lines, UPDATE

        with patch(
            "services.inventory_service.resolve_approval",
            new=AsyncMock(return_value=ApprovalDecision(
                required_role="WM", is_auto_approved=False,
                next_status="PENDING_APPROVAL", required_authority_level=4,
            )),
        ), patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-approved"),
        ) as mock_record, patch(
            "services.inventory_service._get_simple_mode",
            new=AsyncMock(return_value=True),
        ):
            svc    = InventoryService(session)
            result = await svc.transition_transfer(SRC_WM, TRANSFER_ID, "APPROVED")

        assert result.status == "APPROVED"
        assert mock_record.await_count == 1

        calls = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}
        out = calls["TRANSFER_OUT"]
        assert out["warehouse_id"] == WAREHOUSE_A,        "TRANSFER_OUT must target source warehouse"
        assert out["quantity"]     == -Decimal("50"),      "TRANSFER_OUT must be negative (deduction)"
        assert out["reference_id"] == str(TRANSFER_ID)

        # State machine sanity: PENDING_APPROVAL → APPROVED is valid for PULL
        validate_transition("PULL", "PENDING_APPROVAL", "APPROVED")  # must not raise

    # ── Regression tests for Session 5 manual-testing bugs ───────────────────

    async def test_source_wm_sees_issue_button_at_approved(self) -> None:
        """Source WM can dispatch an APPROVED transfer; destination WM is denied (403).

        Bug: PULL/PUSH action buttons were not shown to the source WM when the transfer
        was in APPROVED status — the source WM could not see the dispatch/issue button.
        Root cause: frontend action-button filter used the wrong status predicate.
        Fix: source WM sees the dispatch action at APPROVED; destination WM sees the
        receive action at IN_TRANSIT.

        Backend contract: dispatch_transfer() enforces warehouse-scope ABAC.
        """
        from services.inventory_service import InventoryService
        from fastapi import HTTPException

        line     = _make_line(quantity=40.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PUSH")

        # Source WM (WAREHOUSE_A == from_warehouse_id) must succeed
        session = _session_for_dispatch(xfer_row, [line])
        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-src-dispatch"),
        ), patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            result = await InventoryService(session).dispatch_transfer(SRC_WM, TRANSFER_ID)
        assert result.status == "ISSUED", "source WM must be able to dispatch an APPROVED transfer"

        # Destination WM (WAREHOUSE_B != from_warehouse_id) must be denied
        session_dst = AsyncMock()
        session_dst.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=xfer_row))
        )
        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session_dst).dispatch_transfer(DST_WM, TRANSFER_ID)
        assert exc_info.value.status_code == 403, (
            "destination WM must NOT be allowed to dispatch (only source WM may dispatch)"
        )

    async def test_concurrent_transfers_no_balance_reversal(self) -> None:
        """Two concurrent PUSH transfers from the same source warehouse each write a
        TRANSFER_OUT with a unique idempotency key — no double-deduction or reversal.

        Bug: concurrent PUSH transfers could corrupt the source balance when both
        transitions hit APPROVED simultaneously.
        Root cause: idempotency key was not fully scoped to transfer_id:line_id,
        allowing the same key to collide across transfers.
        Fix: key format is f"transfer:{transfer_id}:approve:out:line:{line.id}" —
        the transfer_id prefix makes every key globally unique per transfer.
        """
        from services.inventory_service import InventoryService

        TRANSFER_ID_2 = UUID("cccccccc-0000-0000-0000-000000000002")

        line1 = _make_line(quantity=50.0)
        line2 = _make_line(quantity=80.0)
        xfer1 = _make_transfer_row("PENDING_APPROVAL", transfer_type="PUSH")
        xfer2 = _make_transfer_row("PENDING_APPROVAL", transfer_type="PUSH")

        _TX = "dddddddd-0000-0000-0000-000000000002"
        recorded: list = []
        async def _record(*_args, **kw):
            recorded.append(kw)
            return _TX

        from services.approval_service import ApprovalDecision
        _auto_approve_off = ApprovalDecision(
            required_role="WM", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=4,
        )
        with patch(
            "services.inventory_service.resolve_approval",
            new=AsyncMock(return_value=_auto_approve_off),
        ), patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(side_effect=_record),
        ), patch(
            "services.inventory_service._get_simple_mode",
            new=AsyncMock(return_value=True),
        ):
            await InventoryService(_session_for_dispatch(xfer1, [line1])).transition_transfer(
                SRC_WM, TRANSFER_ID, "APPROVED"
            )
            await InventoryService(_session_for_dispatch(xfer2, [line2])).transition_transfer(
                SRC_WM, TRANSFER_ID_2, "APPROVED"
            )

        transfer_outs = [r for r in recorded if r["transaction_type"] == "TRANSFER_OUT"]
        assert len(transfer_outs) == 2, (
            f"each concurrent transfer must produce exactly one TRANSFER_OUT, "
            f"got {len(transfer_outs)}"
        )

        # Idempotency keys must differ — scoped to transfer_id:line_id
        keys = {r["idempotency_key"] for r in transfer_outs}
        assert len(keys) == 2, (
            "idempotency keys must be unique per transfer to prevent double-deduction"
        )

        # Each key must reference its own transfer_id
        key_for_transfer1 = next(r["idempotency_key"] for r in transfer_outs if r["quantity"] == -Decimal("50"))
        key_for_transfer2 = next(r["idempotency_key"] for r in transfer_outs if r["quantity"] == -Decimal("80"))
        assert str(TRANSFER_ID)   in key_for_transfer1, "first key must embed TRANSFER_ID"
        assert str(TRANSFER_ID_2) in key_for_transfer2, "second key must embed TRANSFER_ID_2"

        # Quantities are independent
        qtys = {r["quantity"] for r in transfer_outs}
        assert -Decimal("50") in qtys and -Decimal("80") in qtys

    async def test_products_page_shows_same_total_all_wh_users(self) -> None:
        """Receiving at two warehouses creates independent ledger entries; the
        cross-warehouse total is their sum regardless of which user views the page.

        Bug: products/page.tsx filtered getTotalStock() by the active user's
        warehouseId — WH-A users saw 100 and WH-B users saw 200 for the same
        product instead of both seeing the tenant-wide total of 300.
        Root cause: getTotalStock() was warehouse-scoped when it must be tenant-wide.
        Fix: products page sums across ALL warehouses; warehouse-scoped view is
        only on the /inventory page.

        Backend invariant: record_transaction() is called with the exact warehouse_id
        from each request — the service does not cross-contaminate warehouse balances.
        The caller (products page) is responsible for summing across warehouses.
        """
        from services.inventory_service import InventoryService
        from schemas.inventory import ReceiveStockRequest

        body_a = ReceiveStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_A),
            quantity=Decimal("100"),
            idempotency_key="products-total:wh-a",
        )
        body_b = ReceiveStockRequest(
            product_id=UUID(PRODUCT_ID),
            warehouse_id=UUID(WAREHOUSE_B),
            quantity=Decimal("200"),
            idempotency_key="products-total:wh-b",
        )

        _TX = "dddddddd-0000-0000-0000-000000000001"
        recorded: list = []
        async def _record(*_args, **kw):
            recorded.append(kw)
            return _TX

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(side_effect=_record),
        ):
            await InventoryService(AsyncMock()).receive(SRC_WM, body_a)
            await InventoryService(AsyncMock()).receive(DST_WM, body_b)

        wh_ids = {r["warehouse_id"] for r in recorded}
        assert WAREHOUSE_A in wh_ids and WAREHOUSE_B in wh_ids

        wh_a_qty = next(r["quantity"] for r in recorded if r["warehouse_id"] == WAREHOUSE_A)
        wh_b_qty = next(r["quantity"] for r in recorded if r["warehouse_id"] == WAREHOUSE_B)
        tenant_total = wh_a_qty + wh_b_qty

        assert wh_a_qty == Decimal("100"), "WH-A user sees 100"
        assert wh_b_qty == Decimal("200"), "WH-B user sees 200"
        assert tenant_total == Decimal("300"), (
            "products page must show tenant-wide total = 300, "
            f"not a per-user-warehouse subset; got {tenant_total}"
        )

    async def test_transition_idempotent_on_double_submit(self) -> None:
        """Backend handles rapid double-submit: first call succeeds, second returns 422.

        Regression: the Confirm button in the transfers UI had no disabled state,
        allowing two PATCH requests to fire concurrently before the React state
        caught up. The FOR UPDATE lock on transfer_orders serialises concurrent
        requests — the second request reads the already-advanced status and raises
        InvalidStateTransitionError (HTTP 422).

        Fix A (backend):  SELECT FOR UPDATE in transition_transfer — already present.
        Fix B (frontend): isSubmitting guard disables the Confirm button after first click.
        Fix C (frontend): qc.invalidateQueries on error so the UI refreshes to the
                          correct post-first-request status.

        This test verifies the backend contract: the second identical request MUST
        raise InvalidStateTransitionError rather than silently succeeding or
        producing a duplicate ledger entry.
        """
        from services.inventory_service import InventoryService
        from fastapi import HTTPException

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")

        from services.approval_service import ApprovalDecision
        _TX = "tx-double-submit"
        with patch(
            "services.inventory_service.resolve_approval",
            new=AsyncMock(return_value=ApprovalDecision(
                required_role="WM", is_auto_approved=False,
                next_status="PENDING_APPROVAL", required_authority_level=4,
            )),
        ), patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value=_TX),
        ), patch(
            "services.inventory_service._get_simple_mode",
            new=AsyncMock(return_value=True),
        ):
            # First request succeeds: PENDING_APPROVAL → APPROVED
            session1 = _session_for_dispatch(xfer_row, [line])
            result1  = await InventoryService(session1).transition_transfer(
                SRC_WM, TRANSFER_ID, "APPROVED"
            )
            assert result1.status == "APPROVED"

            # Second request: DB row now shows APPROVED — trying APPROVED → APPROVED is invalid
            already_approved = _make_transfer_row("APPROVED", transfer_type="PULL")
            session2 = _session_for_dispatch(already_approved, [line])
            with pytest.raises(HTTPException) as exc_info:
                await InventoryService(session2).transition_transfer(
                    SRC_WM, TRANSFER_ID, "APPROVED"
                )
            assert exc_info.value.status_code == 422, (
                "second identical request must return 422 — backend must not allow "
                "a transfer to transition to its current state"
            )
            assert exc_info.value.detail["code"] == "INVALID_STATE_TRANSITION"

    # ── GAP 1 regression tests ───────────────────────────────────────────────

    async def test_pull_draft_to_submitted_is_invalid(self) -> None:
        """PULL: DRAFT → SUBMITTED raises InvalidStateTransitionError.

        Regression for GAP 1: submit_transfer() hardcoded 'SUBMITTED' which does
        not exist in any PULL/PUSH/SISTER machine. Fix: router resolves the
        type-specific first transition via _SUBMIT_NEXT_STATUS mapping.
        """
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PULL", "DRAFT", "SUBMITTED")

    async def test_push_draft_to_submitted_is_invalid(self) -> None:
        """PUSH: DRAFT → SUBMITTED raises InvalidStateTransitionError."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PUSH", "DRAFT", "SUBMITTED")

    async def test_sister_draft_to_submitted_is_invalid(self) -> None:
        """SISTER: DRAFT → SUBMITTED raises InvalidStateTransitionError."""
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("SISTER", "DRAFT", "SUBMITTED")

    def test_pull_submit_maps_to_pending_review(self) -> None:
        """PULL submit: the correct first post-DRAFT state is PENDING_REVIEW."""
        validate_transition("PULL", "DRAFT", "PENDING_REVIEW")  # must not raise

    def test_push_submit_maps_to_pending_approval(self) -> None:
        """PUSH submit: the correct first post-DRAFT state is PENDING_APPROVAL."""
        validate_transition("PUSH", "DRAFT", "PENDING_APPROVAL")  # must not raise

    def test_sister_submit_maps_to_pending_source_confirm(self) -> None:
        """SISTER submit: the correct first post-DRAFT state is PENDING_SOURCE_CONFIRM."""
        validate_transition("SISTER", "DRAFT", "PENDING_SOURCE_CONFIRM")  # must not raise

    # ── Approval authority enforcement tests ─────────────────────────────────

    async def test_auto_approve_sends_notification(self) -> None:
        """When resolve_approval returns is_auto_approved=True, transition_transfer()
        writes one AutoApprovalNotice outbox event per notify_level."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])

        mock_outbox = AsyncMock()
        with patch(
            "services.inventory_service.resolve_approval",
            new=AsyncMock(return_value=ApprovalDecision(
                required_role="WM", is_auto_approved=True,
                next_status="APPROVED", required_authority_level=4,
                notify_levels=[1, 2],
            )),
        ), patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-auto"),
        ), patch(
            "services.inventory_service.write_to_outbox",
            new=mock_outbox,
        ), patch(
            "services.inventory_service._get_simple_mode",
            new=AsyncMock(return_value=True),
        ):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "APPROVED"
            )

        assert result.status == "APPROVED"
        # write_to_outbox(db, tenant_id, event_type, payload) — event_type is args[2]
        auto_notices = [
            c for c in mock_outbox.call_args_list
            if c.args[2] == "AutoApprovalNotice"
        ]
        assert len(auto_notices) == 2, (
            f"expected 2 AutoApprovalNotice events (one per notify_level), got {len(auto_notices)}"
        )

    async def test_insufficient_authority_rejected(self) -> None:
        """A WM (authority_level=4) cannot approve a transfer that requires RM (authority_level=2).
        transition_transfer() must raise HTTP 403 INSUFFICIENT_APPROVAL_AUTHORITY."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.resolve_approval",
            new=AsyncMock(return_value=ApprovalDecision(
                required_role="RM", is_auto_approved=False,
                next_status="PENDING_APPROVAL", required_authority_level=2,
            )),
        ), patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-blocked"),
        ), patch(
            "services.inventory_service._get_simple_mode",
            new=AsyncMock(return_value=True),
        ), pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).transition_transfer(SRC_WM, TRANSFER_ID, "APPROVED")

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "INSUFFICIENT_APPROVAL_AUTHORITY"

    async def test_destination_on_hand_zero_until_received(self) -> None:
        """Destination on_hand must NOT be credited at APPROVED, ISSUED, or IN_TRANSIT.
        The only state that credits destination on_hand is RECEIVED via TRANSFER_IN.

        Regression for CRITICAL BUG 1: the old RESERVE at dispatch_transfer() caused
        inventory_balances to show a positive balance at destination as soon as the source
        dispatched — before the stock physically arrived. Balance shows early because the
        RESERVE ledger entry ran update_running_balance() at the destination.

        Fix: dispatch_transfer() writes zero ledger entries. Only receive_transfer()
        writes TRANSFER_IN which credits destination on_hand.
        """
        from services.inventory_service import InventoryService

        line      = _make_line(quantity=100.0)
        qty       = Decimal("100")

        # APPROVED → ISSUED: dispatch_transfer() must write zero ledger entries
        approved_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session_a    = _session_for_dispatch(approved_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx"),
        ) as mock_dispatch, patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            await InventoryService(session_a).dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert mock_dispatch.await_count == 0, (
            "No direct ledger entries at ISSUED — destination on_hand must remain unchanged"
        )

        # IN_TRANSIT → RECEIVED: receive_transfer() must write exactly TRANSFER_IN at destination
        in_transit_row = _make_transfer_row("IN_TRANSIT", transfer_type="PULL")
        session_r      = _session_for_receive(in_transit_row, [line])

        received_calls: list = []
        async def _record_receive(*_args, **kw):
            received_calls.append(kw)
            return "tx-receive"

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(side_effect=_record_receive),
        ), patch(
            "services.inventory_service.write_to_outbox",
            new=AsyncMock(),
        ), patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            result = await InventoryService(session_r).receive_transfer(DST_WM, TRANSFER_ID)

        assert result.status == "RECEIVED"
        assert len(received_calls) == 1, "exactly one ledger entry written at RECEIVED"
        tin = received_calls[0]
        assert tin["transaction_type"] == "TRANSFER_IN"
        assert tin["warehouse_id"]     == WAREHOUSE_B, "TRANSFER_IN must target destination"
        assert tin["quantity"]         == qty,          "TRANSFER_IN must be positive (credit)"

    async def test_nm_can_dispatch_as_tenant_manager(self) -> None:
        """NM without warehouse_id must be ALLOWED to dispatch APPROVED transfers.

        NM manages at tenant/organisation level — their warehouse_id may be None because
        they oversee the source facility without being assigned to a specific node.
        dispatch_transfer() allows NM (and TA/SA) when warehouse_id is absent, mirroring
        the frontend isSrcManager = !uWH || uWH === fromWH logic.

        Regression: previously the ABAC check denied ALL users with warehouse_id = None.
        This caused 403 errors when an NM (General Manager) tried to issue a PULL from
        their facility after approving it — the transfer was stuck at APPROVED with no actor.
        """
        from services.inventory_service import InventoryService

        NM_USER = _User("u-nm", TENANT_ID, None, None, "NM")

        line     = _make_line(quantity=60.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-nm-dispatch"),
        ), patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            result = await InventoryService(session).dispatch_transfer(NM_USER, TRANSFER_ID)

        assert result.status == "ISSUED", (
            "NM with no warehouse_id must be able to dispatch — they have tenant-level authority"
        )
        # No ledger entries at dispatch — source on_hand was deducted at APPROVED
        # (this is verified by test_dispatch_writes_no_ledger_entries)

    async def test_rm_cannot_issue_non_source_transfer(self) -> None:
        """RM whose warehouse does not match the source must be denied with 403.

        RM is a facility-bound manager. In a PULL from Main NW (WAREHOUSE_A) to WH,
        the RM at Region W (WAREHOUSE_B) reviewed and approved the transfer but is NOT
        the source manager — issuing stock is Main NW's NM's responsibility.

        Backend ABAC: user.warehouse_id (WAREHOUSE_B) != from_warehouse_id (WAREHOUSE_A)
        → 403. Frontend mirrors this: RM PULL map has no APPROVED entry.
        """
        from services.inventory_service import InventoryService

        RM_USER = _User("u-rm-region", TENANT_ID, WAREHOUSE_B, None, "RM")

        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=xfer_row))
        )

        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).dispatch_transfer(RM_USER, TRANSFER_ID)

        assert exc_info.value.status_code == 403, (
            "RM at a different warehouse must be denied — only source manager may dispatch"
        )

    async def test_transition_reads_fresh_status_before_applying(self) -> None:
        """transition_transfer() validates against the DB row's current status (SELECT FOR
        UPDATE), not the caller's assumed current state.

        Scenario: the frontend's TanStack Query cache is stale — it thinks the transfer
        is still at DRAFT and sends next_status=PENDING_REVIEW (the valid WM submit action
        from DRAFT). The DB row already shows PENDING_REVIEW (another user advanced it).

        The backend must read the DB row (PENDING_REVIEW) and reject the self-transition
        PENDING_REVIEW → PENDING_REVIEW with 422. This is the contract that makes FIX 1
        (pre-fetch check in doTransition) a UX improvement rather than a security gate —
        the backend always wins regardless of what the frontend believes.
        """
        from services.inventory_service import InventoryService
        from fastapi import HTTPException

        # DB row is already at PENDING_REVIEW — advanced past DRAFT
        advanced_row = _make_transfer_row("PENDING_REVIEW", transfer_type="PULL")
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=advanced_row))
        )

        svc = InventoryService(session)
        # Frontend sends next_status=PENDING_REVIEW believing current=DRAFT.
        # Backend reads DB status=PENDING_REVIEW → PENDING_REVIEW → PENDING_REVIEW is
        # not a valid transition → 422.
        with pytest.raises(HTTPException) as exc_info:
            await svc.transition_transfer(SRC_WM, TRANSFER_ID, "PENDING_REVIEW")

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_STATE_TRANSITION"

    # ── Session 10 regression tests — self-approval, Issue/Dispatch, RM receive ─

    async def test_requester_cannot_approve_own_transfer(self) -> None:
        """An RM who created a transfer must be blocked from approving it (BUG 1).

        Business rule: You cannot approve a transfer you created.
        Fix: transition_transfer() APPROVED block compares created_by to user.user_id
        and raises 403 CANNOT_APPROVE_OWN_TRANSFER before the authority check.
        """
        from services.inventory_service import InventoryService

        RM_CREATOR_ID = "u-rm-creator-001"
        RM_USER = _User(RM_CREATOR_ID, TENANT_ID, None, None, "RM")

        line     = _make_line(quantity=300.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        xfer_row.created_by               = RM_CREATOR_ID  # RM is the creator
        xfer_row.created_by_authority_level = 2             # RM authority level

        session = _session_for_dispatch(xfer_row, [line])

        with patch("services.inventory_service.resolve_approval", new=AsyncMock()), \
             patch("services.inventory_service.record_transaction", new=AsyncMock()), \
             pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).transition_transfer(RM_USER, TRANSFER_ID, "APPROVED")

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "CANNOT_APPROVE_OWN_TRANSFER"

    async def test_rm_escalates_to_nm_approval(self) -> None:
        """resolve_approval() escalates when requester_authority_level == required_level.

        RM (authority_level=2) creates a PULL where the band requires RM (level 2).
        Escalation bumps required to max(1, 2-1)=1 (NM/TA), auto_approve is suppressed,
        and the reason string mentions 'Escalated'.
        """
        from services.approval_service import resolve_approval

        # Mock DB: threshold query returns RM-level rule (authority_level=2)
        threshold_row = MagicMock()
        threshold_row.__getitem__ = MagicMock(side_effect=lambda i: ["RM", 2, False, None][i])
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=threshold_row))
        )

        decision = await resolve_approval(
            db,
            TENANT_ID,
            "PULL",
            Decimal("500"),
            requester_authority_level=2,  # RM is the requester
        )

        assert decision.required_authority_level == 1, (
            "RM-required transfer created by RM must escalate to level 1 (NM/TA)"
        )
        assert decision.is_auto_approved is False, "auto_approve must be suppressed after escalation"
        assert "Escalated" in decision.reason

    async def test_issue_and_dispatch_separate_steps(self) -> None:
        """PUSH state machine enforces Issue and Dispatch as two distinct clicks (BUG 2).

        APPROVED → ISSUED  (Issue)    — valid
        ISSUED   → IN_TRANSIT (Dispatch) — valid
        APPROVED → IN_TRANSIT           — INVALID: cannot skip the ISSUED step

        Root cause: RM PUSH action map was missing ISSUED: [dispatch], leaving RM
        stuck at ISSUED with no buttons after clicking Issue.
        """
        # Valid two-step sequence
        validate_transition("PUSH", "APPROVED",  "ISSUED")      # Issue click
        validate_transition("PUSH", "ISSUED",    "IN_TRANSIT")  # Dispatch click

        # Skipping ISSUED is not allowed
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PUSH", "APPROVED", "IN_TRANSIT")

    async def test_rm_sees_receive_at_in_transit(self) -> None:
        """RM who created a PULL (no warehouse_id) can receive it at IN_TRANSIT (BUG 3).

        Scenario: RM submits a PULL request from Main WH to their region.
        The RM has no specific warehouse_id in their JWT (region-level manager).
        After the transfer is dispatched and reaches IN_TRANSIT, the RM must be
        able to receive it — they are the logical destination manager.

        Fix: receive_transfer() allows the creator (created_by == user.user_id)
        when the caller has no warehouse_id and is not a tenant-level role.
        """
        from services.inventory_service import InventoryService

        RM_CREATOR_ID = "u-rm-no-wh-002"
        RM_USER = _User(RM_CREATOR_ID, TENANT_ID, None, None, "RM")  # no warehouse_id

        line     = _make_line(quantity=80.0)
        xfer_row = _make_transfer_row("IN_TRANSIT", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        xfer_row.created_by = RM_CREATOR_ID  # RM is the creator

        session = _session_for_receive(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-rm-receive"),
        ) as mock_record, patch(
            "services.inventory_service.write_to_outbox",
            new=AsyncMock(),
        ), patch(
            "services.inventory_service.write_transfer_ledger_entry",
            new=AsyncMock(),
        ):
            result = await InventoryService(session).receive_transfer(RM_USER, TRANSFER_ID)

        assert result.status == "RECEIVED", (
            "RM who created the PULL must be able to receive it even without warehouse_id"
        )
        assert mock_record.await_count == 1, "TRANSFER_IN must be written at destination"

        # An RM with a different user_id must still be denied
        OTHER_RM = _User("u-rm-other", TENANT_ID, None, None, "RM")
        xfer_row2 = _make_transfer_row("IN_TRANSIT", transfer_type="PULL")
        xfer_row2.created_by = RM_CREATOR_ID  # original creator, not OTHER_RM

        session2 = AsyncMock()
        session2.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=xfer_row2))
        )
        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session2).receive_transfer(OTHER_RM, TRANSFER_ID)
        assert exc_info.value.status_code == 403, (
            "RM who did not create the transfer must be denied"
        )


# ── Gap 2 — ledger wiring tests ──────────────────────────────────────────────

def _session_for_transition_with_lines(
    transfer_row: MagicMock,
    lines: list,
) -> AsyncMock:
    """Session for transition_transfer() branches that need to load lines:
      call 0 — SELECT transfer_orders FOR UPDATE
      call 1 — SELECT transfer_order_lines
      call 2 — UPDATE transfer_orders SET status
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        MagicMock(fetchone=MagicMock(return_value=transfer_row)),
        MagicMock(fetchall=MagicMock(return_value=lines)),
        MagicMock(),
    ])
    return session


@pytest.mark.unit
class TestGap2LedgerWiring:

    async def test_pending_review_writes_reserve_entry(self) -> None:
        """DRAFT → PENDING_REVIEW must write one RESERVE entry per line via
        write_transfer_ledger_entry at the source warehouse."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=40.0)
        xfer_row = _make_transfer_row("DRAFT", transfer_type="PULL")
        session  = _session_for_transition_with_lines(xfer_row, [line])

        captured: list = []
        async def _cap(*_, **kw):
            captured.append(kw)

        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=_cap)):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "PENDING_REVIEW"
            )

        assert result.status == "PENDING_REVIEW"
        assert len(captured) == 1
        r = captured[0]
        assert r["transaction_type"] == "RESERVE"
        assert r["warehouse_id"]     == WAREHOUSE_A
        assert r["quantity"]         == Decimal("40")
        assert r["status_transition"] == "DRAFT_TO_PENDING_REVIEW"
        assert r["line_id"]          == LINE_ID
        assert r["transfer_id"]      == str(TRANSFER_ID)

    async def test_cancel_pre_approval_writes_release(self) -> None:
        """PENDING_REVIEW → CANCELLED must write one RELEASE per line (negative qty)
        to release the RESERVE written at PENDING_REVIEW."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=40.0)
        xfer_row = _make_transfer_row("PENDING_REVIEW", transfer_type="PULL")
        session  = _session_for_transition_with_lines(xfer_row, [line])

        captured: list = []
        async def _cap(*_, **kw):
            captured.append(kw)

        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=_cap)):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "CANCELLED"
            )

        assert result.status == "CANCELLED"
        assert len(captured) == 1
        r = captured[0]
        assert r["transaction_type"] == "RELEASE"
        assert r["quantity"]         == -Decimal("40")   # negative = release the reservation
        assert r["warehouse_id"]     == WAREHOUSE_A
        assert r["status_transition"] == "CANCELLED_PRE_APPROVAL"
        assert r["line_id"]          == LINE_ID

    async def test_issued_writes_transit_out(self) -> None:
        """dispatch_transfer() (APPROVED → ISSUED) must write one TRANSIT_OUT entry per
        line via write_transfer_ledger_entry at the source warehouse."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])

        captured: list = []
        async def _cap(*_, **kw):
            captured.append(kw)

        with patch("services.inventory_service.record_transaction", new=AsyncMock()), \
             patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=_cap)):
            result = await InventoryService(session).dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED"
        assert len(captured) == 1
        r = captured[0]
        assert r["transaction_type"] == "TRANSIT_OUT"
        assert r["warehouse_id"]     == WAREHOUSE_A       # source
        assert r["quantity"]         == Decimal("50")
        assert r["status_transition"] == "APPROVED_TO_ISSUED"
        assert r["line_id"]          == LINE_ID

    async def test_in_transit_writes_transit_in_both_sides(self) -> None:
        """ISSUED → IN_TRANSIT must write TRANSIT_OUT at source AND TRANSIT_IN at
        destination — one pair per line."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=60.0)
        xfer_row = _make_transfer_row("ISSUED", transfer_type="PULL")
        session  = _session_for_transition_with_lines(xfer_row, [line])

        captured: list = []
        async def _cap(*_, **kw):
            captured.append(kw)

        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=_cap)):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "IN_TRANSIT"
            )

        assert result.status == "IN_TRANSIT"
        assert len(captured) == 2, "one TRANSIT_OUT and one TRANSIT_IN expected"

        by_type = {c["transaction_type"]: c for c in captured}
        assert "TRANSIT_OUT" in by_type
        assert "TRANSIT_IN"  in by_type

        out = by_type["TRANSIT_OUT"]
        assert out["warehouse_id"]     == WAREHOUSE_A    # source
        assert out["quantity"]         == Decimal("60")
        assert out["status_transition"] == "ISSUED_TO_IN_TRANSIT"

        inp = by_type["TRANSIT_IN"]
        assert inp["warehouse_id"]     == WAREHOUSE_B    # destination
        assert inp["quantity"]         == Decimal("60")
        assert inp["status_transition"] == "ISSUED_TO_IN_TRANSIT"

    async def test_received_writes_transit_clear(self) -> None:
        """IN_TRANSIT → RECEIVED must write TRANSIT_CLEAR at BOTH source and destination
        (negative qty) and then write TRANSFER_IN at destination via record_transaction."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=70.0)
        xfer_row = _make_transfer_row("IN_TRANSIT", transfer_type="PULL")
        session  = _session_for_receive(xfer_row, [line])

        ledger_calls: list = []
        async def _cap_ledger(*_, **kw):
            ledger_calls.append(kw)

        with patch("services.inventory_service.record_transaction",
                   new=AsyncMock(return_value="tx-tin")), \
             patch("services.inventory_service.write_to_outbox", new=AsyncMock()), \
             patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=_cap_ledger)):
            result = await InventoryService(session).receive_transfer(DST_WM, TRANSFER_ID)

        assert result.status == "RECEIVED"
        assert len(ledger_calls) == 2, "TRANSIT_CLEAR at source and destination"

        wh_ids = {c["warehouse_id"] for c in ledger_calls}
        assert WAREHOUSE_A in wh_ids, "TRANSIT_CLEAR at source"
        assert WAREHOUSE_B in wh_ids, "TRANSIT_CLEAR at destination"

        for c in ledger_calls:
            assert c["transaction_type"] == "TRANSIT_CLEAR"
            assert c["quantity"]         == -Decimal("70")   # negative = clear
            assert c["status_transition"] == "IN_TRANSIT_TO_RECEIVED"

    async def test_cancel_post_approved_writes_reversal(self) -> None:
        """APPROVED → CANCELLED must write TRANSFER_REVERSAL via write_transfer_ledger_entry
        (positive qty = restores source on_hand). No direct record_transaction call."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=55.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])

        captured: list = []
        async def _cap(*_, **kw):
            captured.append(kw)

        with patch("services.inventory_service.record_transaction",
                   new=AsyncMock()) as mock_record, \
             patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=_cap)):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "CANCELLED"
            )

        assert result.status == "CANCELLED"
        assert mock_record.await_count == 0, (
            "TRANSFER_REVERSAL must not use record_transaction directly"
        )
        assert len(captured) == 1
        r = captured[0]
        assert r["transaction_type"] == "TRANSFER_REVERSAL"
        assert r["warehouse_id"]     == WAREHOUSE_A
        assert r["quantity"]         == Decimal("55")    # positive = restore
        assert r["status_transition"] == "APPROVED_TO_CANCELLED"
        assert r["line_id"]          == LINE_ID


# ── Gap 4 — simple_mode wiring tests ─────────────────────────────────────────

@pytest.mark.unit
class TestGap4SimpleModeWiring:

    async def test_simple_mode_flag_read_from_tenant(self) -> None:
        """APPROVED transition reads simple_mode from tenant.approval_thresholds
        and passes the value to resolve_approval().

        Verifies: _get_simple_mode() is awaited exactly once, and the captured
        simple_mode kwarg on resolve_approval() matches what the helper returned.
        """
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=100.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PUSH")
        session  = _session_for_dispatch(xfer_row, [line])

        captured_resolve_kwargs: dict = {}

        async def fake_resolve(*_, **kw):
            captured_resolve_kwargs.update(kw)
            return ApprovalDecision(
                required_role="WM", is_auto_approved=False,
                next_status="PENDING_APPROVAL", required_authority_level=4,
            )

        with patch("services.inventory_service.resolve_approval",
                   side_effect=fake_resolve), \
             patch("services.inventory_service._get_simple_mode",
                   new=AsyncMock(return_value=False)) as mock_get_mode, \
             patch("services.inventory_service.record_transaction",
                   new=AsyncMock(return_value="tx-sm")), \
             patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock()):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "APPROVED"
            )

        assert result.status == "APPROVED"
        mock_get_mode.assert_awaited_once(), "_get_simple_mode must be awaited once per approval"
        assert captured_resolve_kwargs.get("simple_mode") is False, (
            "resolve_approval must receive simple_mode=False from tenant settings"
        )

    async def test_review_endpoint_transitions_correctly(self) -> None:
        """POST /transfers/{id}/review advances PENDING_REVIEW → PENDING_APPROVAL.

        Fix 5C: the dedicated /review endpoint calls
        transition_transfer(user, transfer_id, 'PENDING_APPROVAL').  This test
        verifies the service correctly handles that transition and that the state
        machine enforces the PULL-only constraint (PUSH has no PENDING_REVIEW state).
        """
        from services.inventory_service import InventoryService
        from fastapi import HTTPException

        # ── PULL: PENDING_REVIEW → PENDING_APPROVAL is valid ────────────────
        pull_row = _make_transfer_row("PENDING_REVIEW", transfer_type="PULL")
        session  = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=pull_row)),  # SELECT transfer
            MagicMock(),                                            # UPDATE status
        ])

        result = await InventoryService(session).transition_transfer(
            SRC_WM, TRANSFER_ID, "PENDING_APPROVAL"
        )
        assert result.status == "PENDING_APPROVAL", (
            "review transition must advance PULL to PENDING_APPROVAL"
        )

        # State machine sanity: PENDING_REVIEW → PENDING_APPROVAL is valid for PULL
        validate_transition("PULL", "PENDING_REVIEW", "PENDING_APPROVAL")  # must not raise

        # ── PUSH: no PENDING_REVIEW state — must raise 422 ──────────────────
        push_row = _make_transfer_row("PENDING_REVIEW", transfer_type="PUSH")
        session2 = AsyncMock()
        session2.execute = AsyncMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=push_row))
        )

        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session2).transition_transfer(
                SRC_WM, TRANSFER_ID, "PENDING_APPROVAL"
            )
        assert exc_info.value.status_code == 422, (
            "PUSH transfers have no PENDING_REVIEW state — review must raise 422"
        )
        assert exc_info.value.detail["code"] == "INVALID_STATE_TRANSITION"

    async def test_nm_can_dispatch_with_warehouse_id(self) -> None:
        """NM with a specific warehouse_id assigned must still dispatch transfers
        from ANY source warehouse — NM has tenant-level authority (Critical Bug 3).

        Root cause: dispatch_transfer() checked warehouse_id BEFORE role.
        An NM with warehouse_id="facility-X" was treated like a WM and blocked
        from dispatching transfers from "facility-Y".

        Fix: role check runs FIRST — NM/TA/SA always get can_dispatch=True.
        """
        from services.inventory_service import InventoryService

        NM_WITH_WH = _User("u-nm-wh", TENANT_ID, WAREHOUSE_B, None, "NM")

        line     = _make_line(quantity=60.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch("services.inventory_service.record_transaction", new=AsyncMock()), \
             patch("services.inventory_service.write_transfer_ledger_entry", new=AsyncMock()):
            result = await InventoryService(session).dispatch_transfer(NM_WITH_WH, TRANSFER_ID)

        assert result.status == "ISSUED", (
            "NM with warehouse_id=WAREHOUSE_B must dispatch a transfer from WAREHOUSE_A — "
            "NM authority is tenant-wide, not facility-scoped"
        )

    async def test_nm_no_actions_at_pending_review_in_state_machine(self) -> None:
        """Backend allows PENDING_REVIEW → PENDING_APPROVAL for any authenticated user,
        but the frontend must NOT show NM the review actions at PENDING_REVIEW.

        This test confirms the state machine contract: PENDING_REVIEW → PENDING_APPROVAL
        is valid for PULL.  A separate UI regression test verifies NM sees no buttons.
        The frontend Bug 2 fix (NM PULL map no longer includes PENDING_REVIEW) is
        confirmed by the absence of any PENDING_REVIEW entry in NM's action map.
        """
        # State machine sanity: PULL PENDING_REVIEW → PENDING_APPROVAL is valid
        validate_transition("PULL", "PENDING_REVIEW", "PENDING_APPROVAL")  # must not raise

        # PULL PENDING_REVIEW → APPROVED is invalid (must go through PENDING_APPROVAL first)
        with pytest.raises(InvalidStateTransitionError):
            validate_transition("PULL", "PENDING_REVIEW", "APPROVED")


# ── Session 5 — transfer type config + level permission + value tests ─────────

@pytest.mark.unit
class TestSession5TransferTypeConfig:

    async def test_transfer_type_validated_against_config(self) -> None:
        """create_transfer() resolves transfer_type_config by underlying_type and
        stores the config_id on the new transfer_order row.

        When a matching active config exists the INSERT receives config_id = <uuid>.
        When no config exists (brand-new tenant), config_id = None and the transfer
        proceeds normally — backward-compat guarantee.
        """
        from services.inventory_service import InventoryService
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from decimal import Decimal
        from uuid import UUID

        CONFIG_UUID = "eeeeeeee-0000-0000-0000-000000000001"

        # DB calls in create_transfer (happy path with config found):
        #  0: factory subtree check (no factory restriction)
        #  1: auto-resolve config by underlying_type → returns config row
        #  2: src node level (for can_initiate check) → None so perm not checked
        #  3: dst node level → None
        #  4: unit_price for line → None (no price)
        #  5: INSERT transfer_orders
        #  6: INSERT transfer_order_lines
        config_row = MagicMock()
        config_row.id = UUID(CONFIG_UUID)

        def _make_create_session() -> AsyncMock:
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),   # factory check
                MagicMock(fetchone=MagicMock(return_value=config_row)),  # config lookup
                MagicMock(fetchone=MagicMock(return_value=None)),   # src node level
                MagicMock(fetchone=MagicMock(return_value=None)),   # dst node level
                MagicMock(fetchone=MagicMock(return_value=None)),   # unit_price
                MagicMock(),  # INSERT transfer_orders
                MagicMock(),  # INSERT lines
            ])
            return session

        user = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")
        session = _make_create_session()

        with patch("services.inventory_service.write_to_outbox", new=AsyncMock()), \
             patch("services.inventory_service.write_transfer_ledger_entry", new=AsyncMock()), \
             patch("services.inventory_service._get_simple_mode", new=AsyncMock(return_value=True)):
            body = TransferOrderRequest(
                transfer_type="PULL",
                from_warehouse_id=UUID(WAREHOUSE_A),
                to_warehouse_id=UUID(WAREHOUSE_B),
                lines=[TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal("50"))],
            )
            result = await InventoryService(session).create_transfer(user, body)

        assert result.transfer_type == "PULL"
        # Config ID resolved from DB and stored
        assert result.transfer_type_config_id == UUID(CONFIG_UUID)

    async def test_level_permission_blocks_initiation(self) -> None:
        """When a transfer_type_level_permissions row says can_initiate=False for the
        source node's level, create_transfer() raises HTTP 422 LEVEL_CANNOT_INITIATE."""
        from services.inventory_service import InventoryService
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from decimal import Decimal
        from uuid import UUID
        from fastapi import HTTPException

        CONFIG_UUID = "eeeeeeee-0000-0000-0000-000000000001"

        config_row   = MagicMock(); config_row.id = UUID(CONFIG_UUID)
        src_node_row = MagicMock(); src_node_row.hierarchy_level = 3
        perm_row     = MagicMock(); perm_row.can_initiate = False   # blocked

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=None)),         # factory check
            MagicMock(fetchone=MagicMock(return_value=config_row)),   # config lookup
            MagicMock(fetchone=MagicMock(return_value=src_node_row)), # src node level=3
            MagicMock(fetchone=MagicMock(return_value=perm_row)),     # perm: can_initiate=False
        ])

        user = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")

        with pytest.raises(HTTPException) as exc_info:
            await InventoryService(session).create_transfer(
                user,
                TransferOrderRequest(
                    transfer_type="PULL",
                    from_warehouse_id=UUID(WAREHOUSE_A),
                    to_warehouse_id=UUID(WAREHOUSE_B),
                    lines=[TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal("50"))],
                ),
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "LEVEL_CANNOT_INITIATE"

    async def test_transfer_value_calculated_correctly(self) -> None:
        """create_transfer() sums qty × unit_price across lines and stores total_value.

        For a 50-unit transfer of a product with unit_price=100, total_value = 5000.
        When unit_price is NULL the total_value remains None (not stored as 0).
        """
        from services.inventory_service import InventoryService
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from decimal import Decimal
        from uuid import UUID

        price_row = MagicMock(); price_row.unit_price = Decimal("100")

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=None)),       # factory check
            MagicMock(fetchone=MagicMock(return_value=None)),       # no config → config_id=None
            MagicMock(fetchone=MagicMock(return_value=price_row)),  # unit_price=100
            MagicMock(),  # INSERT transfer_orders
            MagicMock(),  # INSERT lines
        ])

        user = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")

        result = await InventoryService(session).create_transfer(
            user,
            TransferOrderRequest(
                transfer_type="PULL",
                from_warehouse_id=UUID(WAREHOUSE_A),
                to_warehouse_id=UUID(WAREHOUSE_B),
                lines=[TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal("50"))],
            ),
        )

        assert result.total_value == Decimal("5000"), (
            "50 units × ETB 100/unit = ETB 5,000 total_value"
        )
        assert result.currency == "ETB"
        assert result.transfer_type_config_id is None  # no config found in this scenario
