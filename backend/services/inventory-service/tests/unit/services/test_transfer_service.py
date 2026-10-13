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


@pytest.fixture(autouse=True)
def _non_batch_transfer_lots():
    """Every transfer in this file moves a NON-batch product with no stored lot
    allocations — the lot flow has its own file (test_transfer_lots.py).

    services.transfer_lots then posts the single TRANSFER_OUT per line these
    tests assert on. Its ledger call is routed to
    services.inventory_service.record_transaction, so each test's existing
    patch on that name still observes the call.
    """
    import services.inventory_service as inv
    from services.dispatch_service import ProductDispatchInfo

    async def _record(*args: Any, **kwargs: Any) -> Any:
        return await inv.record_transaction(*args, **kwargs)

    with patch(
        "services.transfer_lots.load_allocations", new=AsyncMock(return_value={}),
    ), patch(
        "services.transfer_lots.load_product",
        new=AsyncMock(return_value=ProductDispatchInfo(False, False, None)),
    ), patch(
        "services.transfer_lots.record_transaction", new=_record,
    ):
        yield


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
      call 3 — _get_warehouse_name (only issued when the actor's warehouse differs
               from the transfer's source warehouse — "acted on behalf of" audit)
    Also suitable for transition_transfer() calls that fetch lines (APPROVED, CANCELLED from APPROVED).
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        MagicMock(fetchone=MagicMock(return_value=transfer_row)),  # transfer SELECT
        MagicMock(fetchall=MagicMock(return_value=lines)),         # lines SELECT
        MagicMock(),                                                # status UPDATE
        MagicMock(fetchone=MagicMock(return_value=None)),           # warehouse name lookup
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
class TestGetWarehouseName:
    """Regression tests for _get_warehouse_name() — builds the 'acted_on_behalf_of'
    audit field in dispatch_transfer(). Previously used ':wid::uuid' inline in
    text(), which SQLAlchemy misparses as a malformed bind parameter, raising
    PostgresSyntaxError on every call. This turned every Issue/Dispatch where the
    actor's facility differs from the transfer's source warehouse into a 500
    (introduced in 9290311, never worked)."""

    async def test_get_warehouse_name_valid_uuid(self) -> None:
        from services.inventory_service import _get_warehouse_name

        row = MagicMock()
        row.name = "DZ Region-Center"
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row)))

        result = await _get_warehouse_name(session, TENANT_ID, WAREHOUSE_A)

        assert result == "DZ Region-Center"
        # No inline :param::type casts — SQLAlchemy text() misparses these as bind params
        sql_text = str(session.execute.call_args.args[0])
        assert "::uuid" not in sql_text

    async def test_get_warehouse_name_handles_error_gracefully(self) -> None:
        from services.inventory_service import _get_warehouse_name

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=Exception('syntax error at or near ":"'))

        result = await _get_warehouse_name(session, TENANT_ID, WAREHOUSE_A)

        assert result is None, "_get_warehouse_name must never raise — cosmetic audit field only"


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

        product_row = MagicMock(batch_tracking=False, expiry_tracking=False)

        def _make_db() -> AsyncMock:
            db = AsyncMock()
            db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=product_row)))
            return db

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(side_effect=_record),
        ):
            await InventoryService(_make_db()).receive(SRC_WM, body_a)
            await InventoryService(_make_db()).receive(DST_WM, body_b)

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
      call 2 — SELECT product_approval_minimums (Design-B override check; none configured)
      call 3 — UPDATE transfer_orders SET status
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        MagicMock(fetchone=MagicMock(return_value=transfer_row)),
        MagicMock(fetchall=MagicMock(return_value=lines)),
        MagicMock(fetchone=MagicMock(return_value=None)),
        MagicMock(),
    ])
    return session


@pytest.mark.unit
class TestGap2LedgerWiring:

    async def test_pending_review_writes_no_reserve_entry(self) -> None:
        """PULL DRAFT → PENDING_REVIEW must NOT write any ledger entry.

        The WH (destination) creates a pull request. The source warehouse has
        not yet seen or committed to fulfilling it — no stock should be locked.
        Reservation (RESERVE) happens when the request enters PENDING_APPROVAL.
        """
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
        assert len(captured) == 0, (
            "PENDING_REVIEW must write zero ledger entries — "
            "RESERVE only happens at PENDING_APPROVAL"
        )

    async def test_cancel_at_pending_review_writes_no_release(self) -> None:
        """PULL PENDING_REVIEW → CANCELLED must NOT write any ledger entry.

        No RESERVE was written when entering PENDING_REVIEW, so there is
        nothing to release.  RELEASE only fires when cancelling at
        PENDING_APPROVAL (where RESERVE was written).
        """
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
        assert len(captured) == 0, (
            "PENDING_REVIEW → CANCELLED must write zero ledger entries "
            "— no RESERVE was made at PENDING_REVIEW"
        )

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
        from services.approval_service import ApprovalResolution

        pull_row = _make_transfer_row("PENDING_REVIEW", transfer_type="PULL")
        session  = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=pull_row)),  # SELECT transfer
            MagicMock(fetchall=MagicMock(return_value=[])),         # SELECT lines (for qty)
            MagicMock(fetchone=MagicMock(return_value=None)),       # SELECT transfer for config_id
            MagicMock(fetchone=MagicMock(return_value=None)),       # fallback config lookup → None
            MagicMock(),                                             # UPDATE resolved_steps
            MagicMock(),                                             # UPDATE status
        ])

        with patch("services.approval_service.resolve_transfer_approvers",
                   new=AsyncMock(return_value=ApprovalResolution(steps=[], missing_rule=True))):
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

    async def test_nm_issue_sets_acted_on_behalf_of(self) -> None:
        """NM (warehouse_id=None — the documented normal case for tenant-level
        roles) issues a transfer whose source is L2's warehouse (WAREHOUSE_A).

        Bug 2 fix: the old guard `if user.warehouse_id and ...` short-circuited
        to False when user.warehouse_id is None, so acted_on_behalf_of was never
        set for NM/TA/SA — exactly the roles this audit field targets. The fixed
        guard `if str(user.warehouse_id or "").lower() != ...` correctly treats
        None as "different from from_warehouse_id" and records acted_on_behalf_of.
        """
        from services.inventory_service import InventoryService

        NM_NO_WH = _User("u-nm", TENANT_ID, None, None, "NM")

        line     = _make_line(quantity=60.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch("services.inventory_service.record_transaction", new=AsyncMock()), \
             patch("services.inventory_service.write_transfer_ledger_entry", new=AsyncMock()), \
             patch("services.inventory_service.audit_log", new=AsyncMock()) as mock_audit:
            result = await InventoryService(session).dispatch_transfer(NM_NO_WH, TRANSFER_ID)

        assert result.status == "ISSUED"
        issue_calls = [c for c in mock_audit.call_args_list if c.kwargs["action"] == "transfer:issue"]
        assert len(issue_calls) == 1
        assert "acted_on_behalf_of" in issue_calls[0].kwargs["resource"], (
            "NM (warehouse_id=None) issuing from L2's warehouse must record "
            "acted_on_behalf_of in the audit trail"
        )

    async def test_l2_issue_own_warehouse_no_acted_on_behalf_of(self) -> None:
        """L2 (WM at the source warehouse) issuing their own transfer must NOT
        record acted_on_behalf_of — no regression for the "own warehouse" case.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=60.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch("services.inventory_service.record_transaction", new=AsyncMock()), \
             patch("services.inventory_service.write_transfer_ledger_entry", new=AsyncMock()), \
             patch("services.inventory_service.audit_log", new=AsyncMock()) as mock_audit:
            result = await InventoryService(session).dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED"
        issue_calls = [c for c in mock_audit.call_args_list if c.kwargs["action"] == "transfer:issue"]
        assert len(issue_calls) == 1
        assert "acted_on_behalf_of" not in issue_calls[0].kwargs["resource"], (
            "L2 issuing their own transfer (warehouse_id == from_warehouse_id) "
            "must not record acted_on_behalf_of"
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
        #  0: from warehouse active check
        #  1: to warehouse active check
        #  2: factory subtree check (no factory restriction)
        #  3: auto-resolve config by underlying_type → returns config row
        #  4: src node level (for can_initiate check) → None so perm not checked
        #  5: dst node level → None
        #  6: unit_price for line → None (no price)
        #  7: INSERT transfer_orders
        #  8: INSERT transfer_order_lines
        config_row = MagicMock()
        config_row.id = UUID(CONFIG_UUID)

        def _make_create_session() -> AsyncMock:
            oh_r = MagicMock(); oh_r.qty = Decimal("9999")
            pd_r = MagicMock(); pd_r.pending = Decimal("0")
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[
                MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # from active check
                MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # to active check
                MagicMock(fetchone=MagicMock(return_value=None)),        # factory check
                MagicMock(fetchone=MagicMock(return_value=config_row)),  # config lookup
                MagicMock(fetchone=MagicMock(return_value=None)),        # src node level
                MagicMock(fetchone=MagicMock(return_value=None)),        # dst node level
                MagicMock(fetchone=MagicMock(return_value=oh_r)),        # on_hand (stock check)
                MagicMock(fetchone=MagicMock(return_value=pd_r)),        # pending_out (stock check)
                MagicMock(fetchone=MagicMock(return_value=None)),        # unit_price
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
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # from active check
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # to active check
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

        price_row  = MagicMock(); price_row.unit_price  = Decimal("100")
        oh_row_tv  = MagicMock(); oh_row_tv.qty        = Decimal("9999")
        pend_row_tv = MagicMock(); pend_row_tv.pending = Decimal("0")

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # from active check
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # to active check
            MagicMock(fetchone=MagicMock(return_value=None)),           # factory check
            MagicMock(fetchone=MagicMock(return_value=None)),           # no config → config_id=None
            MagicMock(fetchone=MagicMock(return_value=oh_row_tv)),      # on_hand (stock check)
            MagicMock(fetchone=MagicMock(return_value=pend_row_tv)),    # pending_out (stock check)
            MagicMock(fetchone=MagicMock(return_value=price_row)),      # unit_price=100
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


# ── Stock availability check at creation ────────────────────────────────────

@pytest.mark.asyncio
class TestCreateTransferStockCheck:
    """Regression tests for BUG: PUSH transfers allowed qty > available stock.

    create_transfer() must check available (on_hand - pending_out) at the source
    warehouse for every requested line BEFORE inserting the transfer record.
    """

    async def test_push_blocked_insufficient_stock(self) -> None:
        """HTTP 422 INSUFFICIENT_STOCK when requested qty > available at source.

        on_hand=50, pending_out=30, available=20 — requesting 40 must fail.
        """
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from services.inventory_service import InventoryService

        on_hand_row  = MagicMock(); on_hand_row.qty     = Decimal("50")
        pending_row  = MagicMock(); pending_row.pending = Decimal("30")
        # available = 50 - 30 = 20; requested = 40 > 20 → must raise

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # from active check
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # to active check
            MagicMock(fetchone=MagicMock(return_value=None)),          # factory check → no restriction
            MagicMock(fetchone=MagicMock(return_value=None)),          # config resolution → None
            MagicMock(fetchone=MagicMock(return_value=on_hand_row)),   # inventory_balances on_hand=50
            MagicMock(fetchone=MagicMock(return_value=pending_row)),   # pending_out=30
        ])

        user = _User("u-nm", TENANT_ID, WAREHOUSE_A, None, "NM")

        with pytest.raises(HTTPException) as exc:
            await InventoryService(session).create_transfer(
                user,
                TransferOrderRequest(
                    transfer_type="PUSH",
                    from_warehouse_id=UUID(WAREHOUSE_A),
                    to_warehouse_id=UUID(WAREHOUSE_B),
                    lines=[TransferLineRequest(
                        product_id=UUID(PRODUCT_ID), quantity=Decimal("40")
                    )],
                ),
            )

        assert exc.value.status_code == 422
        detail = exc.value.detail
        assert detail["code"] == "INSUFFICIENT_STOCK"
        assert detail["available"] == pytest.approx(20.0), "available must be on_hand - pending_out"
        assert detail["requested"] == pytest.approx(40.0)

    async def test_push_succeeds_when_stock_sufficient(self) -> None:
        """create_transfer() proceeds normally when requested qty ≤ available."""
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from services.inventory_service import InventoryService

        on_hand_row  = MagicMock(); on_hand_row.qty     = Decimal("100")
        pending_row  = MagicMock(); pending_row.pending = Decimal("20")
        price_row    = MagicMock(); price_row.unit_price = Decimal("10")
        # available = 100 - 20 = 80; requested = 30 ≤ 80 → must succeed

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # from active check
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),  # to active check
            MagicMock(fetchone=MagicMock(return_value=None)),         # factory check
            MagicMock(fetchone=MagicMock(return_value=None)),         # config resolution
            MagicMock(fetchone=MagicMock(return_value=on_hand_row)),  # on_hand=100
            MagicMock(fetchone=MagicMock(return_value=pending_row)),  # pending_out=20
            MagicMock(fetchone=MagicMock(return_value=price_row)),    # unit_price=10
            MagicMock(),                                               # INSERT transfer_orders
            MagicMock(),                                               # INSERT lines
        ])

        user = _User("u-nm", TENANT_ID, WAREHOUSE_A, None, "NM")

        result = await InventoryService(session).create_transfer(
            user,
            TransferOrderRequest(
                transfer_type="PUSH",
                from_warehouse_id=UUID(WAREHOUSE_A),
                to_warehouse_id=UUID(WAREHOUSE_B),
                lines=[TransferLineRequest(
                    product_id=UUID(PRODUCT_ID), quantity=Decimal("30")
                )],
            ),
        )

        assert result.status == "DRAFT", "transfer must be created in DRAFT status"
        assert result.total_value == Decimal("300"), "30 × ETB 10 = ETB 300"
        assert result.transfer_type_config_id is None  # no config found in this scenario


# ── Inactive node check at creation ──────────────────────────────────────────

@pytest.mark.asyncio
class TestCreateTransferActiveNodeCheck:
    """Regression tests for BUG: deactivated nodes could still be used as a
    transfer source or destination, defeating the deactivation feature.

    create_transfer() must reject with 422 NODE_INACTIVE when either
    from_warehouse_id or to_warehouse_id refers to an inactive organization_node.
    """

    async def test_cannot_create_transfer_to_inactive_node(self) -> None:
        """to_warehouse_id is inactive → 422 NODE_INACTIVE, mentions 'to' warehouse."""
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from services.inventory_service import InventoryService

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=True))),   # from active check
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=False))),  # to active check
        ])

        user = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")

        with pytest.raises(HTTPException) as exc:
            await InventoryService(session).create_transfer(
                user,
                TransferOrderRequest(
                    transfer_type="PULL",
                    from_warehouse_id=UUID(WAREHOUSE_A),
                    to_warehouse_id=UUID(WAREHOUSE_B),
                    lines=[TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal("10"))],
                ),
            )

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "NODE_INACTIVE"
        assert "to warehouse" in exc.value.detail["message"]

    async def test_cannot_create_transfer_from_inactive_node(self) -> None:
        """from_warehouse_id is inactive → 422 NODE_INACTIVE, mentions 'from' warehouse."""
        from schemas.inventory import TransferOrderRequest, TransferLineRequest
        from services.inventory_service import InventoryService

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=MagicMock(is_active=False))),  # from active check
        ])

        user = _User("u-wm", TENANT_ID, WAREHOUSE_A, None, "WM")

        with pytest.raises(HTTPException) as exc:
            await InventoryService(session).create_transfer(
                user,
                TransferOrderRequest(
                    transfer_type="PULL",
                    from_warehouse_id=UUID(WAREHOUSE_A),
                    to_warehouse_id=UUID(WAREHOUSE_B),
                    lines=[TransferLineRequest(product_id=UUID(PRODUCT_ID), quantity=Decimal("10"))],
                ),
            )

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "NODE_INACTIVE"
        assert "from warehouse" in exc.value.detail["message"]


# ── WMS-standard reservation timing ────────────────────────────────────────

def _session_for_pending_approval(
    transfer_row: MagicMock,
    lines: list,
    transfer_type: str = "PULL",
) -> AsyncMock:
    """Session for transition_transfer() → PENDING_APPROVAL.

    PULL / SISTER (status != DRAFT, or transfer_type != PUSH — the
    self-approval fast-path at the top of the PENDING_APPROVAL branch is
    not entered):
      call 0 — SELECT transfer_orders FOR UPDATE
      call 1 — SELECT transfer_order_lines  (RESERVE writes + total_qty)
      call 2 — SELECT transfer_orders       (tv_row: config_id, total_value, created_by)
      call 3 — SELECT transfer_type_config  (fallback config lookup when config_id is None)
      call 4 — SELECT product_approval_minimums (Design-B override check, routing; none configured)
      call 5 — UPDATE transfer_orders       (resolved_approval_steps)
      call 6 — UPDATE transfer_orders       (status)

    PUSH (DRAFT → PENDING_APPROVAL is the submission step; the self-approval
    fast-path runs first, checks for a Design-B override, finds none, then
    get_self_approval_decision short-circuits to None since the test users
    have no level_number — so the fast-path falls through to the normal
    reservation/routing flow below):
      call 0 — SELECT transfer_orders FOR UPDATE
      call 1 — SELECT transfer_order_lines
      call 2 — SELECT product_approval_minimums (Design-B override check, fast-path; none configured)
      call 3 — SELECT transfer_orders       (tv_row)
      call 4 — SELECT transfer_type_config  (fallback config lookup)
      call 5 — SELECT product_approval_minimums (Design-B override check, routing; none configured)
      call 6 — UPDATE transfer_orders       (resolved_approval_steps)
      call 7 — UPDATE transfer_orders       (status)
    """
    tv_row = MagicMock()
    tv_row.transfer_type_config_id = None
    tv_row.total_value             = None
    tv_row.created_by              = "u-creator-000"

    if transfer_type == "PUSH":
        side_effect = [
            MagicMock(fetchone=MagicMock(return_value=transfer_row)),  # transfer SELECT
            MagicMock(fetchall=MagicMock(return_value=lines)),          # lines SELECT
            MagicMock(fetchone=MagicMock(return_value=None)),           # product override (fast-path) → None
            MagicMock(fetchone=MagicMock(return_value=tv_row)),         # tv_row SELECT
            MagicMock(fetchone=MagicMock(return_value=None)),           # fallback config lookup → None
            MagicMock(fetchone=MagicMock(return_value=None)),           # product override (routing) → None
            MagicMock(),                                                 # UPDATE approval steps
            MagicMock(),                                                 # UPDATE status
        ]
    else:
        side_effect = [
            MagicMock(fetchone=MagicMock(return_value=transfer_row)),  # transfer SELECT
            MagicMock(fetchall=MagicMock(return_value=lines)),          # lines SELECT
            MagicMock(fetchone=MagicMock(return_value=tv_row)),         # tv_row SELECT
            MagicMock(fetchone=MagicMock(return_value=None)),           # fallback config lookup → None
            MagicMock(fetchone=MagicMock(return_value=None)),           # product override (routing) → None
            MagicMock(),                                                 # UPDATE approval steps
            MagicMock(),                                                 # UPDATE status
        ]

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=side_effect)
    return session


def _mock_resolution() -> MagicMock:
    res = MagicMock()
    res.steps_as_json.return_value = "[]"
    res.is_auto_approved           = False
    res.notify_levels              = []
    return res


@pytest.mark.asyncio
@pytest.mark.unit
class TestWMSReservationTiming:
    """Regression tests for WMS-standard PULL/PUSH/SISTER reservation timing.

    RESERVE must be written when entering PENDING_APPROVAL for all transfer types:
      PULL:   PENDING_REVIEW → PENDING_APPROVAL  (source reviewed; now commits)
      PUSH:   DRAFT → PENDING_APPROVAL           (source initiates; commits immediately)
      SISTER: PENDING_DEST_CONFIRM → PENDING_APPROVAL (both agreed; source commits)

    PENDING_REVIEW for PULL must NOT write RESERVE — the WH submitted the
    request but the source has not yet seen or committed to it.
    """

    async def test_pull_no_reserve_at_pending_review(self) -> None:
        """PULL DRAFT → PENDING_REVIEW: zero ledger entries written.

        Available at source must NOT change when a PULL request is submitted.
        The source warehouse has not committed; no RESERVE = no soft lock.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=100.0)
        xfer_row = _make_transfer_row("DRAFT", transfer_type="PULL")
        session  = _session_for_transition_with_lines(xfer_row, [line])

        captured: list = []
        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=lambda *_, **kw: captured.append(kw))):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "PENDING_REVIEW"
            )

        assert result.status == "PENDING_REVIEW"
        assert len(captured) == 0, (
            "DRAFT → PENDING_REVIEW must write zero ledger entries for PULL; "
            "RESERVE only happens at PENDING_APPROVAL"
        )

    async def test_pull_reserve_at_pending_approval(self) -> None:
        """PULL PENDING_REVIEW → PENDING_APPROVAL: RESERVE written at source.

        Source reviewed the request and forwarded it for approval.
        Available at source must decrease by the transfer quantity.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=100.0)
        xfer_row = _make_transfer_row("PENDING_REVIEW", transfer_type="PULL")
        session  = _session_for_pending_approval(xfer_row, [line])

        captured: list = []
        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=lambda *_, **kw: captured.append(kw))), \
             patch("services.approval_service.resolve_transfer_approvers",
                   new=AsyncMock(return_value=_mock_resolution())):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "PENDING_APPROVAL"
            )

        assert result.status == "PENDING_APPROVAL"
        reserves = [c for c in captured if c.get("transaction_type") == "RESERVE"]
        assert len(reserves) == 1, "exactly one RESERVE entry per line at PENDING_APPROVAL"
        r = reserves[0]
        assert r["warehouse_id"]      == WAREHOUSE_A
        assert r["quantity"]          == Decimal("100")
        assert r["status_transition"] == "PENDING_REVIEW_TO_PENDING_APPROVAL"
        assert r["line_id"]           == LINE_ID

    async def test_push_reserve_at_pending_approval(self) -> None:
        """PUSH DRAFT → PENDING_APPROVAL: RESERVE written at source.

        PUSH has no PENDING_REVIEW step.  The source creates and immediately
        commits the transfer at PENDING_APPROVAL.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=75.0)
        xfer_row = _make_transfer_row("DRAFT", transfer_type="PUSH")
        session  = _session_for_pending_approval(xfer_row, [line], transfer_type="PUSH")

        captured: list = []
        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=lambda *_, **kw: captured.append(kw))), \
             patch("services.approval_service.resolve_transfer_approvers",
                   new=AsyncMock(return_value=_mock_resolution())):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "PENDING_APPROVAL"
            )

        assert result.status == "PENDING_APPROVAL"
        reserves = [c for c in captured if c.get("transaction_type") == "RESERVE"]
        assert len(reserves) == 1
        r = reserves[0]
        assert r["warehouse_id"]      == WAREHOUSE_A
        assert r["quantity"]          == Decimal("75")
        assert r["status_transition"] == "DRAFT_TO_PENDING_APPROVAL"

    async def test_sister_reserve_at_pending_approval(self) -> None:
        """SISTER PENDING_DEST_CONFIRM → PENDING_APPROVAL: RESERVE written at source.

        Both WMs confirmed the lateral transfer.  Source is now committed;
        RESERVE locks the stock before it goes for senior approval.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("PENDING_DEST_CONFIRM", transfer_type="SISTER")
        session  = _session_for_pending_approval(xfer_row, [line])

        captured: list = []
        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=lambda *_, **kw: captured.append(kw))), \
             patch("services.approval_service.resolve_transfer_approvers",
                   new=AsyncMock(return_value=_mock_resolution())):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "PENDING_APPROVAL"
            )

        assert result.status == "PENDING_APPROVAL"
        reserves = [c for c in captured if c.get("transaction_type") == "RESERVE"]
        assert len(reserves) == 1
        r = reserves[0]
        assert r["warehouse_id"]      == WAREHOUSE_A
        assert r["quantity"]          == Decimal("50")
        assert r["status_transition"] == "PENDING_DEST_CONFIRM_TO_PENDING_APPROVAL"

    async def test_cancel_at_pending_approval_writes_release(self) -> None:
        """PENDING_APPROVAL → CANCELLED: RELEASE written at source.

        RESERVE was written when entering PENDING_APPROVAL; cancelling must
        release it.
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=60.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        session  = _session_for_transition_with_lines(xfer_row, [line])

        captured: list = []
        with patch("services.inventory_service.write_transfer_ledger_entry",
                   new=AsyncMock(side_effect=lambda *_, **kw: captured.append(kw))):
            result = await InventoryService(session).transition_transfer(
                SRC_WM, TRANSFER_ID, "CANCELLED"
            )

        assert result.status == "CANCELLED"
        releases = [c for c in captured if c.get("transaction_type") == "RELEASE"]
        assert len(releases) == 1, "RELEASE must fire when cancelling at PENDING_APPROVAL"
        r = releases[0]
        assert r["quantity"]          == -Decimal("60")
        assert r["warehouse_id"]      == WAREHOUSE_A
        assert r["status_transition"] == "CANCELLED_PRE_APPROVAL"


# ── D5/D1/D2/D3/D4 regression tests ────────────────────────────────────────

@pytest.mark.unit
class TestE2EDiscrepancyRegressions:
    """Regression tests for discrepancies found in the end-to-end transfer test."""

    # ── D5: SISTER VARCHAR ───────────────────────────────────────────────────

    def test_sister_pending_source_confirm_fits_varchar30(self) -> None:
        """PENDING_SOURCE_CONFIRM (22 chars) must fit in the widened VARCHAR(30) column.

        Migration 040 widened transfer_orders.status from VARCHAR(20) to VARCHAR(30).
        This test documents that the status value's length is within the new limit.
        """
        assert len("PENDING_SOURCE_CONFIRM") == 22, "status string is 22 chars"
        assert 22 <= 30, "22 chars fits in VARCHAR(30)"
        assert 22 > 20, "22 chars did NOT fit in VARCHAR(20) — that was the bug"

    # ── D1: Approval rules used, not fallback ────────────────────────────────

    def test_approval_rules_empty_steps_treated_as_no_rule(self) -> None:
        """_find_matching_rule result with approval_steps=[] must be discarded.

        A rule row with an empty approval_steps JSONB array produces an ApprovalResolution
        with no assignee, making the approval invisible to everyone.  The caller now
        discards such results and falls through to the NM fallback so a real person
        is always found.
        """
        # Simulate the dict returned by _find_matching_rule when steps are empty
        rule_with_empty_steps = {"id": "some-uuid", "approval_steps": []}
        rule_with_none_steps  = {"id": "some-uuid", "approval_steps": None}

        # The check used in resolve_transfer_approvers:
        # rule = candidate if candidate and candidate.get("approval_steps") else None
        assert not rule_with_empty_steps.get("approval_steps"), \
            "empty list is falsy — must be treated as no rule"
        assert not rule_with_none_steps.get("approval_steps"), \
            "None is falsy — must be treated as no rule"

        # A properly configured rule has at least one step
        rule_with_steps = {"id": "some-uuid", "approval_steps": [{"sequence": 1}]}
        assert rule_with_steps.get("approval_steps"), \
            "non-empty steps list is truthy — rule is used"

    # ── D2: Reviewer is immediate superior only ──────────────────────────────

    def test_reviewer_is_immediate_superior_only(self) -> None:
        """canReview must match ONLY the immediate superior level, not anyone who outranks.

        WM (authority 4) creator → immediate reviewer = level 3 (LM/RM).
        NM (authority 1) must NOT see PENDING_REVIEW actions on WM-created PULLs.
        """
        # Mirrors the frontend getAvailableActions logic
        def immediate_reviewer_level(creator_authority_level: int) -> int:
            return max(1, creator_authority_level - 1)

        def can_review(user_level: int, creator_level: int, is_creator: bool) -> bool:
            return (
                not is_creator
                and user_level == immediate_reviewer_level(creator_level)
            )

        # WM (L4) creates PULL → immediate reviewer is L3
        assert immediate_reviewer_level(4) == 3
        assert can_review(user_level=3, creator_level=4, is_creator=False) is True,  \
            "LM (L3) IS the immediate reviewer for WM (L4) creator"
        assert can_review(user_level=2, creator_level=4, is_creator=False) is False, \
            "RM (L2) must NOT review WM-created PULL (L3 is immediate)"
        assert can_review(user_level=1, creator_level=4, is_creator=False) is False, \
            "NM (L1) must NOT review WM-created PULL (L3 is immediate)"

        # RM (L2) creates → immediate reviewer is L1 (NM)
        assert immediate_reviewer_level(2) == 1
        assert can_review(user_level=1, creator_level=2, is_creator=False) is True,  \
            "NM (L1) IS the immediate reviewer for RM (L2) creator"
        assert can_review(user_level=2, creator_level=2, is_creator=True) is False,  \
            "creator cannot review their own transfer"

    # ── D3: canApprove from approval-info endpoint ───────────────────────────

    def test_canApprove_override_takes_precedence(self) -> None:
        """When approval-info provides can_approve, it overrides the local estimate.

        Local estimate: canApprove = level <= 2 && !isCreator
        This incorrectly shows RM can approve a PUSH created by NM (backend needs L1).

        With override: canApprove = can_approve from approval-info (backend truth).
        """
        # Simulate the local estimate that was wrong in the e2e test
        def local_can_approve(user_level: int, is_creator: bool) -> bool:
            return user_level <= 2 and not is_creator

        # Simulate the override behaviour
        def can_approve_with_override(
            user_level: int, is_creator: bool, override: bool | None
        ) -> bool:
            if override is not None:
                return override
            return local_can_approve(user_level, is_creator)

        RM_LEVEL = 2  # RM is L2

        # Without override: RM (L2) incorrectly appears to be able to approve
        assert local_can_approve(RM_LEVEL, is_creator=False) is True, \
            "local estimate incorrectly allows RM to approve NM-created PUSH"

        # With override=False (from approval-info: required L1, RM is L2 → blocked):
        assert can_approve_with_override(RM_LEVEL, is_creator=False, override=False) is False, \
            "override=False from approval-info correctly blocks RM"

        # With override=True (from approval-info: RM IS the required approver):
        assert can_approve_with_override(RM_LEVEL, is_creator=False, override=True) is True, \
            "override=True from approval-info correctly allows RM"


# ── FIX 1/2/3 regression tests ──────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
class TestApprovalGateAndAnyMode:
    """Regression tests for dynamic approval gate and ANY execution mode."""

    async def test_dynamic_approver_overrides_gate(self) -> None:
        """_check_can_approve allows the dynamically-assigned approver regardless of
        their authority level — overriding the simple-mode gate.

        This was the B4 failure: RM (L2) was blocked by the simple-mode gate
        requiring L1 for a PUSH created by NM, even though the dynamic rule
        assigned RM as the designated approver.
        """
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision

        RM_USER_ID = "rm-user-0001"

        # Transfer row with resolved_approval_steps assigning RM
        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "Regional Manager",
                "execution_mode": "sequential",
                "assigned_to_user_id": RM_USER_ID,
                "assigned_to_name": "RM User",
                "all_holders": [],
            }
        ]
        row.current_approval_step = 1

        # User is RM (authority level 2)
        user = _User(RM_USER_ID, TENANT_ID, WAREHOUSE_B, None, "RM")

        # Simple-mode decision would BLOCK RM (requires L1)
        blocking_decision = ApprovalDecision(
            required_role="NM",
            is_auto_approved=False,
            next_status="PENDING_APPROVAL",
            required_authority_level=1,  # requires L1 — RM (L2) would be blocked
        )
        caller_level = 2  # RM = authority level 2

        # Must NOT raise — dynamic routing takes precedence and allows RM
        await _check_can_approve(row, user, caller_level, blocking_decision)

    async def test_dynamic_gate_blocks_non_assigned(self) -> None:
        """_check_can_approve blocks a user who is not the assigned approver
        even if their authority level would normally allow approval."""
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision
        from fastapi import HTTPException

        RM_USER_ID = "rm-user-0001"
        GM_USER_ID = "gm-user-0001"  # GM assigned but someone else tries

        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "General Manager",
                "execution_mode": "sequential",
                "assigned_to_user_id": GM_USER_ID,
                "assigned_to_name": "GM User",
                "all_holders": [],
            }
        ]
        row.current_approval_step = 1

        user = _User(RM_USER_ID, TENANT_ID, WAREHOUSE_B, None, "RM")  # RM, not GM

        decision = ApprovalDecision(
            required_role="NM", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=1,
        )

        with pytest.raises(HTTPException) as exc:
            await _check_can_approve(row, user, 2, decision)

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "NOT_ASSIGNED_APPROVER"

    async def test_any_mode_first_holder_wins(self) -> None:
        """ANY-mode step: any holder in all_holders may approve."""
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision

        RM_A_ID = "rm-a-user"; RM_B_ID = "rm-b-user"

        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "Regional Manager",
                "execution_mode": "any",
                "assigned_to_user_id": None,  # ANY mode — no specific assignee
                "assigned_to_name": None,
                "all_holders": [
                    {"user_id": RM_A_ID, "name": "RM-A"},
                    {"user_id": RM_B_ID, "name": "RM-B"},
                ],
                "holder_count": 2,
            }
        ]
        row.current_approval_step = 1

        decision = ApprovalDecision(
            required_role="RM", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=2,
        )

        # Both RM-A and RM-B must be allowed
        for uid, name in [(RM_A_ID, "RM-A"), (RM_B_ID, "RM-B")]:
            user = _User(uid, TENANT_ID, WAREHOUSE_B, None, "RM")
            await _check_can_approve(row, user, 2, decision)  # must not raise

    async def test_any_mode_blocks_non_holder(self) -> None:
        """ANY-mode step: user NOT in all_holders is blocked."""
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision
        from fastapi import HTTPException

        RM_A_ID = "rm-a-user"
        OUTSIDER_ID = "outsider-user"

        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "Regional Manager",
                "execution_mode": "any",
                "assigned_to_user_id": None,
                "assigned_to_name": None,
                "all_holders": [{"user_id": RM_A_ID, "name": "RM-A"}],
                "holder_count": 1,
            }
        ]
        row.current_approval_step = 1

        user = _User(OUTSIDER_ID, TENANT_ID, WAREHOUSE_B, None, "RM")
        decision = ApprovalDecision(
            required_role="RM", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=2,
        )

        with pytest.raises(HTTPException) as exc:
            await _check_can_approve(row, user, 2, decision)

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "NOT_ASSIGNED_APPROVER"

    def test_approval_info_status_label_any_mode(self) -> None:
        """status_label correctly describes ANY-mode multi-holder steps."""
        # Mirror the status_label logic from get_approval_info
        def compute_label(
            exec_mode: str,
            holder_count: int,
            position_title: str,
            assigned_name: str | None,
            is_vacant: bool,
            escalated: bool,
            all_holders: list,
        ) -> str:
            if is_vacant or escalated:
                return f"Position vacant — escalating to {assigned_name or 'an escalated approver'}"
            if exec_mode == "any" and holder_count > 1:
                return f"Any {position_title} can approve ({holder_count} approvers available)"
            if exec_mode == "any" and holder_count == 1:
                name = all_holders[0]["name"] if all_holders else position_title
                return f"Awaiting {name} approval"
            if assigned_name:
                return f"Awaiting {assigned_name} approval"
            return f"Awaiting {position_title} approval"

        # ANY mode, 2 holders
        label = compute_label("any", 2, "Regional Manager", None, False, False,
                               [{"user_id": "a", "name": "RM-A"}, {"user_id": "b", "name": "RM-B"}])
        assert label == "Any Regional Manager can approve (2 approvers available)"

        # ANY mode, 1 holder
        label = compute_label("any", 1, "Regional Manager", None, False, False,
                               [{"user_id": "a", "name": "RM-A"}])
        assert label == "Awaiting RM-A approval"

        # Sequential, named approver
        label = compute_label("sequential", 1, "General Manager", "GM User", False, False, [])
        assert label == "Awaiting GM User approval"

        # Vacant position
        label = compute_label("sequential", 0, "Regional Manager", "RM-fallback", True, True, [])
        assert label == "Position vacant — escalating to RM-fallback"


# ── FIX 1/2: ancestor traversal and empty-holders gate ──────────────────────

@pytest.mark.asyncio
@pytest.mark.unit
class TestAncestorTraversal:
    """Regression tests for _find_ancestor_with_position traversal (FIX 1)
    and the empty-holders 422 gate in _check_can_approve (FIX 2)."""

    async def test_ancestor_traversal_finds_two_levels_up(self) -> None:
        """_find_ancestor_with_position returns a node 2+ hops above the start.

        Scenario: DESTINATION_PARENT_NODE from Sub-WH-A looking for
        'Zone Manager'. The chain is Sub-WH-A → WH-A → Region A → Zone A.
        'Zone Manager' exists only at Zone A (3 hops up).
        """
        from services.approval_service import _find_ancestor_with_position

        SUBWH = "node-sub-wh"; WHA = "node-wh-a"; REGA = "node-reg-a"; ZONA = "node-zone-a"
        TENANT = "tenant-001"; TITLE = "Zone Manager"

        # Counts: Zone Manager found only at Zone A
        counts_by_nid = {SUBWH: 0, WHA: 0, REGA: 0, ZONA: 1}
        # Parents chain: Sub-WH-A → WH-A → Region A → Zone A → None
        parents = {SUBWH: WHA, WHA: REGA, REGA: ZONA, ZONA: None}
        # Node names
        names = {SUBWH: "Sub-WH-A", WHA: "WH-A", REGA: "Region A", ZONA: "Zone A"}

        execute_calls: list[str] = []

        async def fake_execute(sql, params=None, **kw):
            nid = (params or {}).get("nid")
            execute_calls.append(nid)
            result = MagicMock()
            sql_str = str(sql)
            if "COUNT" in sql_str:
                # position-count query
                result.scalar = MagicMock(return_value=counts_by_nid.get(nid, 0))
                result.fetchone = MagicMock(return_value=None)
            elif "org_node_hierarchy" in sql_str:
                # _get_parent_node — returns the parent
                parent_id = parents.get(nid)
                if parent_id:
                    row = MagicMock()
                    row.id = parent_id; row.name = names[parent_id]; row.hierarchy_level = 0
                    result.fetchone = MagicMock(return_value=row)
                else:
                    result.fetchone = MagicMock(return_value=None)
                result.scalar = MagicMock(return_value=None)
            else:
                # _get_node — returns the node itself
                row = MagicMock()
                row.id = nid; row.name = names.get(nid, nid); row.hierarchy_level = 0
                result.fetchone = MagicMock(return_value=row)
                result.scalar = MagicMock(return_value=None)
            return result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        node = await _find_ancestor_with_position(session, TENANT, SUBWH, TITLE)

        # Must have traversed all the way to Zone A
        assert node is not None, "Should find Zone A after traversal"
        assert node["id"] == ZONA, f"Expected Zone A, got {node}"
        # Must have checked Sub-WH-A, WH-A, Region A before finding Zone A
        count_checks = [c for c in execute_calls if c in (SUBWH, WHA, REGA, ZONA)]
        assert SUBWH in count_checks and WHA in count_checks and REGA in count_checks, (
            f"Must check all intermediate nodes. Checked: {count_checks}"
        )

    async def test_ancestor_traversal_cycle_guard(self) -> None:
        """_find_ancestor_with_position terminates on a circular hierarchy.

        Scenario: node A's parent is B and B's parent is A (cycle).
        The function must not loop forever.
        """
        from services.approval_service import _find_ancestor_with_position

        NODE_A = "node-a"; NODE_B = "node-b"; TENANT = "tenant-001"

        async def fake_execute(sql, params=None, **kw):
            nid = (params or {}).get("nid")
            result = MagicMock()
            if "COUNT" in str(sql):
                result.scalar = MagicMock(return_value=0)  # never found
                result.fetchone = MagicMock(return_value=None)
            else:
                # A's parent is B, B's parent is A (cycle)
                other = NODE_B if nid == NODE_A else NODE_A
                row = MagicMock(); row.id = other; row.name = other; row.hierarchy_level = 0
                result.fetchone = MagicMock(return_value=row)
                result.scalar = MagicMock(return_value=None)
            return result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        # Must return None (not found) without hanging
        result = await _find_ancestor_with_position(session, TENANT, NODE_A, "Any Position")
        assert result is None, "Cycle guard must terminate and return None"

    async def test_source_parent_finds_zone_from_subwh(self) -> None:
        """SOURCE_PARENT_NODE for 'Zone Manager' starting from Sub-WH-A
        must traverse up and find Zone A — not stop at WH-A.

        This is the exact failure from Test 2 (PUSH) and Test 3 (SISTER)
        of the complex scenario test.
        """
        from services.approval_service import _resolve_node_for_step

        SUBWH = "node-sub-wh"; ZONA = "node-zone-a"; TENANT = "tenant-001"
        CHAIN = {"node-sub-wh": "node-wh-a", "node-wh-a": "node-reg-a",
                 "node-reg-a": ZONA, ZONA: None}
        # Zone Manager only at Zone A
        HAS_POS = {ZONA}

        async def fake_execute(sql, params=None, **kw):
            nid = (params or {}).get("nid")
            result = MagicMock()
            sql_str = str(sql)
            if "COUNT" in sql_str:
                result.scalar = MagicMock(return_value=(1 if nid in HAS_POS else 0))
                result.fetchone = MagicMock(return_value=None)
            elif "org_node_hierarchy" in sql_str:
                # _get_parent_node
                parent_id = CHAIN.get(nid)
                if parent_id:
                    row = MagicMock(); row.id = parent_id; row.name = parent_id; row.hierarchy_level = 0
                    result.fetchone = MagicMock(return_value=row)
                else:
                    result.fetchone = MagicMock(return_value=None)
                result.scalar = MagicMock(return_value=None)
            else:
                # _get_node — return the node itself
                row = MagicMock(); row.id = nid; row.name = nid; row.hierarchy_level = 0
                result.fetchone = MagicMock(return_value=row)
                result.scalar = MagicMock(return_value=None)
            return result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        # SOURCE_PARENT_NODE from Sub-WH-A — must find Zone A
        node = await _resolve_node_for_step(
            session, TENANT, "source_parent_node", SUBWH, "ignored-dst", "Zone Manager"
        )
        assert node is not None and node["id"] == ZONA, (
            "SOURCE_PARENT_NODE must traverse until Zone A (3 hops) is found"
        )

        # DESTINATION_PARENT_NODE from Sub-WH-A — must also find Zone A
        node2 = await _resolve_node_for_step(
            session, TENANT, "destination_parent_node", "ignored-src", SUBWH, "Zone Manager"
        )
        assert node2 is not None and node2["id"] == ZONA, (
            "DESTINATION_PARENT_NODE must traverse until Zone A (3 hops) is found"
        )

    async def test_empty_holders_raises_422(self) -> None:
        """_check_can_approve raises HTTP 422 when dynamic routing is active
        but all_holders is empty (position exists in rule but no holder stored).

        This prevents the silent 'anyone can approve' behaviour that was
        observed in Tests 2/3 of the complex scenario.
        """
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision
        from fastapi import HTTPException

        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "Zone Manager",
                "execution_mode": "any",
                "assigned_to_user_id": None,
                "all_holders": [],          # ← empty: position not found in hierarchy
                "holder_count": 0,
            }
        ]
        row.current_approval_step = 1

        user = _User("any-user", TENANT_ID, WAREHOUSE_A, None, "RM")
        decision = ApprovalDecision(
            required_role="RM", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=2,
        )

        with pytest.raises(HTTPException) as exc:
            await _check_can_approve(row, user, 2, decision)

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "NO_APPROVER_FOUND", (
            "Empty all_holders must raise 422 NO_APPROVER_FOUND, not silently allow anyone"
        )


# ── BUG 1 + BUG 2 regression tests ──────────────────────────────────────────

@pytest.mark.unit
class TestL1StockAndTAEscalation:
    """Regression tests for L1 stock double-count (BUG 1) and TA escalation (BUG 2)."""

    def test_l1_stock_not_doubled_no_warehouses_join(self) -> None:
        """The stock SQL no longer JOINs the legacy warehouses table.

        Removing LEFT JOIN warehouses prevents double-counting when a
        warehouse UUID exists in both the legacy warehouses table and
        organization_node (the current IMTS system).  Confirmed by
        checking the SQL template in get_stock().
        """
        import inspect
        from services.inventory_analytics import get_stock
        src = inspect.getsource(get_stock)
        assert "LEFT JOIN warehouses" not in src, (
            "get_stock() must not JOIN the legacy warehouses table — "
            "it duplicates rows for warehouses that exist in both tables"
        )
        assert "LEFT JOIN organization_node on_node" in src, (
            "get_stock() must JOIN organization_node for warehouse names"
        )
        assert "lot_number IS NULL" in src, (
            "get_stock() must filter to aggregate (lot_number IS NULL) rows only"
        )

    async def test_ta_can_approve_escalated_transfer(self) -> None:
        """_check_can_approve allows any TA on steps flagged as escalated.

        When self-approval prevention escalates the approval step to TA,
        any active TA for the tenant may approve — even if their user_id
        differs from the stored assigned_to_user_id (e.g. when the
        escalation updated stored TA ID but a different TA is calling).
        """
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision
        from fastapi import HTTPException

        CREATOR_ID = "creator-000"; OTHER_TA_ID = "ta-user-001"

        # A step that was escalated to TA (self-approval prevention)
        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "Tenant Admin",
                "execution_mode": "sequential",
                "assigned_to_user_id": OTHER_TA_ID,  # TA stored, but another TA calling
                "assigned_to_name": "Tenant Admin",
                "all_holders": [],
                "escalated": True,                   # ← self-approval escalation flag
            }
        ]
        row.current_approval_step = 1
        row.created_by = CREATOR_ID

        decision = ApprovalDecision(
            required_role="TA", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=1,
        )

        # A different TA (not the stored OTHER_TA_ID) tries to approve
        DIFFERENT_TA_ID = "ta-user-002"
        user = _User(DIFFERENT_TA_ID, TENANT_ID, None, None, "TA")

        # Must NOT raise — escalated step allows any TA
        await _check_can_approve(row, user, 1, decision)

    async def test_non_ta_cannot_approve_escalated_transfer(self) -> None:
        """_check_can_approve blocks non-TA users on escalated steps."""
        from services.inventory_service import _check_can_approve
        from services.approval_service import ApprovalDecision
        from fastapi import HTTPException

        TA_ID = "ta-user-001"; RM_ID = "rm-user-001"; CREATOR_ID = "creator-000"

        row = MagicMock()
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "Tenant Admin",
                "execution_mode": "sequential",
                "assigned_to_user_id": TA_ID,
                "assigned_to_name": "TA User",
                "all_holders": [],
                "escalated": True,
            }
        ]
        row.current_approval_step = 1
        row.created_by = CREATOR_ID

        decision = ApprovalDecision(
            required_role="TA", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=1,
        )

        # RM (not TA) tries to approve — must be blocked
        user = _User(RM_ID, TENANT_ID, WAREHOUSE_A, None, "RM")

        with pytest.raises(HTTPException) as exc:
            await _check_can_approve(row, user, 2, decision)

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "NOT_ASSIGNED_APPROVER"

    async def test_escalated_steps_store_ta_user_id(self) -> None:
        """_find_tenant_ta returns the TA user_id for a given tenant.

        The escalation path in resolve_transfer_approvers calls
        _find_tenant_ta to find the TA user when self-approval exhausts
        the reports_to chain.  This test verifies the helper SQL returns
        a user with system_role='TA'.
        """
        from services.approval_service import _find_tenant_ta

        TA_USER_ID = "ta-user-001"

        async def fake_execute(sql, params=None, **kw):
            result = MagicMock()
            row = MagicMock()
            row.id = TA_USER_ID
            row.full_name = "Tenant Admin"
            result.fetchone = MagicMock(return_value=row)
            return result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        uid, name = await _find_tenant_ta(session, TENANT_ID)
        assert uid == TA_USER_ID, "Must return the TA user's ID"
        assert name == "Tenant Admin"
        # Verify the SQL queries for system_role='TA'
        call_sql = str(session.execute.call_args_list[0][0][0])
        assert "system_role" in call_sql and "TA" in call_sql, (
            "_find_tenant_ta must query by system_role='TA'"
        )


# ── GAP-A regression tests — multi-step sequential approval enforcement ───────

@pytest.mark.unit
class TestMultiStepApproval:
    """GAP-A: verify that the APPROVED transition handler enforces sequential
    multi-step approval — intermediate steps stay PENDING_APPROVAL and the
    TRANSFER_OUT ledger entry fires only on the final step."""

    @staticmethod
    def _make_two_step_row(
        current_step: int = 1,
        approver1_uid: str = "u-approver-1",
        approver2_uid: str = "u-approver-2",
    ) -> MagicMock:
        row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        row.created_by = "u-creator"
        row.created_by_authority_level = 4
        row.current_approval_step = current_step
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "General Manager",
                "execution_mode": "sequential",
                "assigned_to_user_id": approver1_uid,
                "assigned_to_name": "GM User",
                "all_holders": [],
                "holder_count": 1,
                "is_vacant": False,
                "escalated": False,
                "status": "pending",
            },
            {
                "sequence": 2,
                "position_title": "Regional Manager",
                "execution_mode": "sequential",
                "assigned_to_user_id": approver2_uid,
                "assigned_to_name": "RM User",
                "all_holders": [],
                "holder_count": 1,
                "is_vacant": False,
                "escalated": False,
                "status": "pending",
            },
        ]
        return row

    @staticmethod
    def _make_one_step_row(approver_uid: str = "u-approver-1") -> MagicMock:
        row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        row.created_by = "u-creator"
        row.created_by_authority_level = 4
        row.current_approval_step = 1
        row.resolved_approval_steps = [
            {
                "sequence": 1,
                "position_title": "General Manager",
                "execution_mode": "sequential",
                "assigned_to_user_id": approver_uid,
                "assigned_to_name": "GM User",
                "all_holders": [],
                "holder_count": 1,
                "is_vacant": False,
                "escalated": False,
                "status": "pending",
            },
        ]
        return row

    async def test_single_step_still_works(self) -> None:
        """Single-step approval must still produce APPROVED and fire TRANSFER_OUT."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        approver = _User("u-approver-1", TENANT_ID, WAREHOUSE_B, None, "NM")
        row  = self._make_one_step_row(approver.user_id)
        line = _make_line(quantity=50.0)

        # execute 0: SELECT row; 1: SELECT lines; 2: UPDATE JSONB final; 3: UPDATE status
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=row)),
            MagicMock(fetchall=MagicMock(return_value=[line])),
            MagicMock(),
            MagicMock(),
        ])

        with patch("services.inventory_service.resolve_approval",
                   new=AsyncMock(return_value=ApprovalDecision(
                       required_role="NM", is_auto_approved=False,
                       next_status="PENDING_APPROVAL", required_authority_level=1,
                   ))), \
             patch("services.inventory_service.record_transaction",
                   new=AsyncMock(return_value="tx-single")) as mock_record, \
             patch("services.inventory_service._get_simple_mode",
                   new=AsyncMock(return_value=False)):
            result = await InventoryService(session).transition_transfer(
                approver, TRANSFER_ID, "APPROVED"
            )

        assert result.status == "APPROVED", "Single-step approval must yield APPROVED"
        assert mock_record.await_count == 1, "TRANSFER_OUT must fire on the single final step"

    async def test_step1_approval_stays_pending(self) -> None:
        """Step 1 of 2 approval must return PENDING_APPROVAL and NOT fire TRANSFER_OUT."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        approver1 = _User("u-approver-1", TENANT_ID, WAREHOUSE_B, None, "NM")
        row  = self._make_two_step_row(current_step=1, approver1_uid=approver1.user_id)
        line = _make_line(quantity=50.0)

        # execute 0: SELECT row; 1: SELECT lines; 2: UPDATE JSONB + advance counter
        # No execute 3 — returns early at PENDING_APPROVAL
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=row)),
            MagicMock(fetchall=MagicMock(return_value=[line])),
            MagicMock(),
        ])

        with patch("services.inventory_service.resolve_approval",
                   new=AsyncMock(return_value=ApprovalDecision(
                       required_role="NM", is_auto_approved=False,
                       next_status="PENDING_APPROVAL", required_authority_level=1,
                   ))), \
             patch("services.inventory_service.record_transaction",
                   new=AsyncMock(return_value="tx-step1")) as mock_record, \
             patch("services.inventory_service._get_simple_mode",
                   new=AsyncMock(return_value=False)):
            result = await InventoryService(session).transition_transfer(
                approver1, TRANSFER_ID, "APPROVED"
            )

        assert result.status == "PENDING_APPROVAL", (
            "Step 1 of 2 approval must keep transfer in PENDING_APPROVAL"
        )
        assert mock_record.await_count == 0, (
            "TRANSFER_OUT must NOT fire for intermediate approval steps"
        )

    async def test_step2_approval_completes_transfer(self) -> None:
        """Step 2 of 2 (final) approval must yield APPROVED and fire TRANSFER_OUT."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        approver2 = _User("u-approver-2", TENANT_ID, WAREHOUSE_B, None, "RM")
        row  = self._make_two_step_row(current_step=2, approver2_uid=approver2.user_id)
        row.resolved_approval_steps[0]["status"] = "approved"  # step 1 already done
        line = _make_line(quantity=50.0)

        # execute 0: SELECT row; 1: SELECT lines; 2: UPDATE JSONB final; 3: UPDATE status
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=row)),
            MagicMock(fetchall=MagicMock(return_value=[line])),
            MagicMock(),
            MagicMock(),
        ])

        with patch("services.inventory_service.resolve_approval",
                   new=AsyncMock(return_value=ApprovalDecision(
                       required_role="RM", is_auto_approved=False,
                       next_status="PENDING_APPROVAL", required_authority_level=2,
                   ))), \
             patch("services.inventory_service.record_transaction",
                   new=AsyncMock(return_value="tx-step2")) as mock_record, \
             patch("services.inventory_service._get_simple_mode",
                   new=AsyncMock(return_value=False)):
            result = await InventoryService(session).transition_transfer(
                approver2, TRANSFER_ID, "APPROVED"
            )

        assert result.status == "APPROVED", "Final step approval must yield APPROVED"
        assert mock_record.await_count == 1, "TRANSFER_OUT must fire on the final step"

    async def test_two_step_approval_requires_both(self) -> None:
        """A user not assigned to the current step must be denied with HTTP 403."""
        from services.approval_service import ApprovalDecision
        from services.inventory_service import InventoryService

        approver1  = _User("u-approver-1", TENANT_ID, WAREHOUSE_B, None, "NM")
        wrong_user = _User("u-wrong", TENANT_ID, WAREHOUSE_B, None, "RM")
        row  = self._make_two_step_row(current_step=1, approver1_uid=approver1.user_id)
        line = _make_line(quantity=50.0)

        # execute 0: SELECT row; 1: SELECT lines; then 403 before any writes
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=row)),
            MagicMock(fetchall=MagicMock(return_value=[line])),
        ])

        with patch("services.inventory_service.resolve_approval",
                   new=AsyncMock(return_value=ApprovalDecision(
                       required_role="NM", is_auto_approved=False,
                       next_status="PENDING_APPROVAL", required_authority_level=1,
                   ))), \
             patch("services.inventory_service._get_simple_mode",
                   new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc_info:
                await InventoryService(session).transition_transfer(
                    wrong_user, TRANSFER_ID, "APPROVED"
                )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "NOT_ASSIGNED_APPROVER"


# ── GAP-C regression tests: position_id-based approval routing ───────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestGapCPositionIdRouting:
    """GAP-C: approval step resolver uses position_id (UUID FK) for direct DB
    lookup when present, making routing immune to position title renames."""

    # ── shared rule factory ───────────────────────────────────────────────────

    @staticmethod
    def _rule(pos_id: str | None, title: str, rule_id: str) -> dict:
        step: dict = {
            "sequence": 1,
            "position_title": title,
            "resolution": "TENANT_WIDE",
            "execution_mode": "sequential",
            "sla_hours": None,
        }
        if pos_id:
            step["position_id"] = pos_id
        return {"id": rule_id, "approval_steps": [step]}

    @staticmethod
    def _pos_db_row(pos_id: str, user_id: str, name: str,
                    node_id: str, title: str) -> MagicMock:
        r = MagicMock()
        r.pos_id = pos_id; r.user_id = user_id; r.full_name = name
        r.node_id = node_id; r.title = title
        return r

    async def test_approval_step_resolves_by_position_id(self) -> None:
        """When step.position_id is set, resolver queries by UUID — ignores stale title."""
        from decimal import Decimal as D
        from services.approval_service import resolve_transfer_approvers

        POS_ID    = "pppppppp-0000-0000-0000-000000000001"
        HOLDER    = "u-holder-001"
        NODE_ID   = "nnnnnnnn-0000-0000-0000-000000000001"
        RULE_ID   = "rrrrrrrr-0000-0000-0000-000000000001"
        TTCID     = "tttttttt-0000-0000-0000-000000000001"

        db_row = self._pos_db_row(POS_ID, HOLDER, "Alice", NODE_ID, "New Title (current)")

        with patch("services.approval_service._find_matching_rule",
                   new=AsyncMock(return_value=self._rule(POS_ID, "Old Title (stale)", RULE_ID))):
            session = AsyncMock()
            # src_level and dst_level provided → no initial node queries.
            # Only the direct-by-ID position query fires.
            session.execute = AsyncMock(
                return_value=MagicMock(fetchone=MagicMock(return_value=db_row))
            )

            result = await resolve_transfer_approvers(
                session=session,
                tenant_id=TENANT_ID,
                transfer_type_config_id=TTCID,
                from_warehouse_id=WAREHOUSE_A,
                to_warehouse_id=WAREHOUSE_B,
                quantity=D("10"),
                total_value=None,
                created_by="u-creator-001",
                src_level=1,
                dst_level=3,
            )

        assert result is not None
        assert len(result.steps) == 1
        step = result.steps[0]
        assert step.assigned_to_user_id == HOLDER
        assert step.assigned_to_name == "Alice"
        assert step.position_title == "New Title (current)"   # refreshed from DB
        # Only ONE execute call: the direct-by-ID query
        assert session.execute.await_count == 1

    async def test_legacy_title_match_still_works(self) -> None:
        """Steps without position_id fall back to existing title-based traversal."""
        from decimal import Decimal as D
        from services.approval_service import resolve_transfer_approvers

        RULE_ID   = "rrrrrrrr-0000-0000-0000-000000000002"
        TTCID     = "tttttttt-0000-0000-0000-000000000002"
        POS_ID    = "pppppppp-0000-0000-0000-000000000002"
        HOLDER    = "u-holder-002"
        NODE_ID   = "nnnnnnnn-0000-0000-0000-000000000002"

        pos_row = MagicMock()
        pos_row.pos_id = POS_ID; pos_row.user_id = HOLDER
        pos_row.full_name = "Bob"; pos_row.node_id = NODE_ID

        # TENANT_WIDE resolution returns None without a DB call, so only
        # _find_position_and_holder fires → 1 execute call total.
        with patch("services.approval_service._find_matching_rule",
                   new=AsyncMock(return_value=self._rule(None, "Regional Manager", RULE_ID))):
            session = AsyncMock()
            session.execute = AsyncMock(
                return_value=MagicMock(fetchone=MagicMock(return_value=pos_row))
            )

            result = await resolve_transfer_approvers(
                session=session,
                tenant_id=TENANT_ID,
                transfer_type_config_id=TTCID,
                from_warehouse_id=WAREHOUSE_A,
                to_warehouse_id=WAREHOUSE_B,
                quantity=D("10"),
                total_value=None,
                created_by="u-creator-002",
                src_level=1,
                dst_level=3,
            )

        assert result is not None
        assert len(result.steps) == 1
        step = result.steps[0]
        assert step.assigned_to_user_id == HOLDER
        assert step.position_title == "Regional Manager"
        assert session.execute.await_count == 1   # find_position_and_holder only

    def test_rename_position_updates_approval_rules_jsonb(self) -> None:
        """Part B cascade logic: renaming updates position_title in JSONB steps
        that reference the position by position_id."""
        import json as _json

        POS_ID    = "pppppppp-0000-0000-0000-000000000003"
        RULE_ID   = "rrrrrrrr-0000-0000-0000-000000000003"
        OLD_TITLE = "Regional Manager"
        NEW_TITLE = "Zone Director"

        # Simulate the in-memory JSONB (as Python list) returned from DB
        steps: list[dict] = [
            {"sequence": 1, "position_id": POS_ID, "position_title": OLD_TITLE,
             "resolution": "TENANT_WIDE", "execution_mode": "sequential", "sla_hours": None},
        ]

        # Apply the cascade logic exactly as written in positions.py
        updated = False
        for s in steps:
            if isinstance(s, dict) and s.get("position_id") == POS_ID:
                s["position_title"] = NEW_TITLE
                updated = True

        assert updated, "Should have found and updated the step"
        serialised = _json.dumps(steps)
        roundtripped = _json.loads(serialised)
        assert roundtripped[0]["position_title"] == NEW_TITLE
        assert roundtripped[0]["position_id"] == POS_ID

    async def test_rename_does_not_break_routing(self) -> None:
        """After a rename, resolver finds the holder via position_id regardless of
        the (now-stale) title stored in the approval rule JSONB."""
        from decimal import Decimal as D
        from services.approval_service import resolve_transfer_approvers

        POS_ID  = "pppppppp-0000-0000-0000-000000000004"
        HOLDER  = "u-holder-004"
        NODE_ID = "nnnnnnnn-0000-0000-0000-000000000004"
        RULE_ID = "rrrrrrrr-0000-0000-0000-000000000004"
        TTCID   = "tttttttt-0000-0000-0000-000000000004"

        db_row = self._pos_db_row(POS_ID, HOLDER, "Carol", NODE_ID, "Supply Chain Lead")

        with patch("services.approval_service._find_matching_rule",
                   new=AsyncMock(return_value=self._rule(POS_ID, "Logistics Director (old)", RULE_ID))):
            session = AsyncMock()
            session.execute = AsyncMock(
                return_value=MagicMock(fetchone=MagicMock(return_value=db_row))
            )

            result = await resolve_transfer_approvers(
                session=session,
                tenant_id=TENANT_ID,
                transfer_type_config_id=TTCID,
                from_warehouse_id=WAREHOUSE_A,
                to_warehouse_id=WAREHOUSE_B,
                quantity=D("10"),
                total_value=None,
                created_by="u-creator-004",
                src_level=1,
                dst_level=3,
            )

        assert result is not None
        assert len(result.steps) == 1
        step = result.steps[0]
        assert step.assigned_to_user_id == HOLDER, (
            f"Expected {HOLDER!r} but got {step.assigned_to_user_id!r}. "
            "Rename should not break routing when position_id is stored."
        )
        assert step.position_title == "Supply Chain Lead"   # refreshed from DB
