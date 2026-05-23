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

    async def test_dispatch_reserves_destination_only(self) -> None:
        """dispatch_transfer() (APPROVED → ISSUED) writes one ledger entry per line:
          RESERVE at destination — books in_transit_in.
        Source on_hand was already deducted at APPROVED via transition_transfer(); dispatch
        must NOT write another TRANSFER_OUT."""
        from services.inventory_service import InventoryService

        line      = _make_line(quantity=50.0)
        xfer_row  = _make_transfer_row("APPROVED", transfer_type="PULL")
        session   = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-dispatched"),
        ) as mock_record:
            svc    = InventoryService(session)
            result = await svc.dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED"
        # One ledger entry per line: only RESERVE at destination
        assert mock_record.await_count == 1

        calls = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}
        assert "TRANSFER_OUT" not in calls, "TRANSFER_OUT must NOT be written at dispatch"

        rsrv = calls["RESERVE"]
        assert rsrv["warehouse_id"] == WAREHOUSE_B        # destination WH reserved
        assert rsrv["quantity"]     == Decimal("50")       # positive = in_transit booking
        assert rsrv["reference_id"] == str(TRANSFER_ID)

    async def test_received_transition_credits_destination_balance(self) -> None:
        """receive_transfer() (IN_TRANSIT → RECEIVED) writes two ledger entries per line:
          1. RELEASE at destination   — clears the in_transit_in booking
          2. TRANSFER_IN at destination — credits on_hand
        Source on_hand was already deducted at APPROVED; NO TRANSFER_OUT at receive."""
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
        ):
            svc    = InventoryService(session)
            result = await svc.receive_transfer(DST_WM, TRANSFER_ID)

        assert result.status == "RECEIVED"
        # Two ledger entries per line: RELEASE + TRANSFER_IN at destination only
        assert mock_record.await_count == 2

        calls = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}
        assert "TRANSFER_OUT" not in calls, "TRANSFER_OUT must NOT be written at receive (deducted at APPROVED)"
        rel  = calls["RELEASE"]
        tin  = calls["TRANSFER_IN"]

        assert rel["warehouse_id"]  == WAREHOUSE_B        # destination — clearing booking
        assert rel["quantity"]      == -Decimal("30")      # negative = release
        assert rel["reference_id"]  == str(TRANSFER_ID)

        assert tin["warehouse_id"]  == WAREHOUSE_B        # destination WH credited
        assert tin["quantity"]      == Decimal("30")       # positive = credit
        assert tin["reference_id"]  == str(TRANSFER_ID)

    async def test_cancelled_from_approved_reverses_source_balance(self) -> None:
        """A PULL transfer cancelled while in APPROVED state must write a compensating
        RETURN at source to restore on_hand — because TRANSFER_OUT was written at APPROVED.

        1. Allows APPROVED → CANCELLED (valid in PULL machine).
        2. Writes exactly one RETURN at source (positive quantity, restores on_hand).
        """
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])  # SELECT transfer, SELECT lines, UPDATE

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(),
        ) as mock_record:
            svc    = InventoryService(session)
            result = await svc.transition_transfer(SRC_WM, TRANSFER_ID, "CANCELLED")

        assert result.status == "CANCELLED"
        assert mock_record.await_count == 1

        calls = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}
        ret = calls["RETURN"]
        assert ret["warehouse_id"] == WAREHOUSE_A,        "RETURN must target source warehouse"
        assert ret["quantity"]     == Decimal("50"),       "RETURN quantity must be positive (restore)"
        assert ret["reference_id"] == str(TRANSFER_ID)

        # State machine sanity: APPROVED → CANCELLED is valid for PULL
        validate_transition("PULL", "APPROVED", "CANCELLED")  # must not raise

    # ── Regression tests for BUGs 1–3 ────────────────────────────────────────

    async def test_issued_does_not_deduct_source_on_hand(self) -> None:
        """dispatch_transfer() (APPROVED → ISSUED) must NOT deduct source warehouse on_hand.
        Source on_hand was already deducted at APPROVED via transition_transfer().
        dispatch_transfer() only writes a RESERVE at destination; no TRANSFER_OUT at source."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=120.0)
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PUSH",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-issued"),
        ) as mock_record:
            svc    = InventoryService(session)
            result = await svc.dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED", "status must advance to ISSUED"

        transfer_out_calls = [
            kw for _, kw in mock_record.call_args_list
            if kw.get("transaction_type") == "TRANSFER_OUT"
        ]
        assert len(transfer_out_calls) == 0, "TRANSFER_OUT must NOT be written at dispatch"

        reserve_calls = [
            kw for _, kw in mock_record.call_args_list
            if kw.get("transaction_type") == "RESERVE"
        ]
        assert len(reserve_calls) == 1, "exactly one RESERVE at destination per line"
        assert reserve_calls[0]["warehouse_id"] == WAREHOUSE_B, "destination WH must be reserved"
        assert reserve_calls[0]["quantity"] == Decimal("120"), "quantity must be positive"

    async def test_in_transit_shows_on_both_sides(self) -> None:
        """dispatch_transfer() writes a RESERVE at destination to track in_transit_in.
        Source in_transit_out is derived from transfer status in the display layer.
        No TRANSFER_OUT at source during dispatch — deduction was already made at APPROVED."""
        from services.inventory_service import InventoryService

        qty      = Decimal("75")
        line     = _make_line(quantity=float(qty))
        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL",
                                      from_wh=WAREHOUSE_A, to_wh=WAREHOUSE_B)
        session  = _session_for_dispatch(xfer_row, [line])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-both-sides"),
        ) as mock_record:
            svc    = InventoryService(session)
            result = await svc.dispatch_transfer(SRC_WM, TRANSFER_ID)

        assert result.status == "ISSUED"

        calls_by_type = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}

        # Source side — no TRANSFER_OUT at dispatch; deduction deferred to receive
        assert "TRANSFER_OUT" not in calls_by_type, "TRANSFER_OUT must NOT be written at dispatch"

        # Destination side — RESERVE books in_transit_in
        assert "RESERVE" in calls_by_type, "RESERVE missing — destination in_transit_in not tracked"
        dst = calls_by_type["RESERVE"]
        assert dst["warehouse_id"] == WAREHOUSE_B
        assert dst["quantity"]     == qty
        assert dst["reference_id"] == str(TRANSFER_ID)

    async def test_received_clears_in_transit_credits_destination(self) -> None:
        """receive_transfer() (IN_TRANSIT → RECEIVED) must:
          a. Write a RELEASE at destination to clear the in_transit_in booking.
          b. Write a TRANSFER_IN at destination to credit on_hand.
        Must NOT write TRANSFER_OUT at source — deduction was already made at APPROVED."""
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
        ):
            svc    = InventoryService(session)
            result = await svc.receive_transfer(DST_WM, TRANSFER_ID)

        assert result.status == "RECEIVED"

        calls_by_type = {kw["transaction_type"]: kw for _, kw in mock_record.call_args_list}

        # Source must NOT get another TRANSFER_OUT — already written at APPROVED
        assert "TRANSFER_OUT" not in calls_by_type, "TRANSFER_OUT must NOT be written at receive"

        # In-transit clearing — must reverse the RESERVE written at dispatch
        assert "RELEASE" in calls_by_type, "RELEASE missing — in_transit_in not cleared on receive"
        rel = calls_by_type["RELEASE"]
        assert rel["warehouse_id"] == WAREHOUSE_B, "RELEASE must target destination"
        assert rel["quantity"]     == -qty,         "RELEASE must be negative (reversal)"

        # On-hand credit — stock is now physically at destination
        assert "TRANSFER_IN" in calls_by_type, "TRANSFER_IN missing — destination on_hand not credited"
        tin = calls_by_type["TRANSFER_IN"]
        assert tin["warehouse_id"] == WAREHOUSE_B, "TRANSFER_IN must target destination"
        assert tin["quantity"]     == qty,          "TRANSFER_IN must be positive (credit)"

        assert rel["reference_id"] == tin["reference_id"] == str(TRANSFER_ID)

    async def test_approved_transition_writes_transfer_out_at_source(self) -> None:
        """transition_transfer() (PENDING_APPROVAL → APPROVED) must write one TRANSFER_OUT
        per line at source — this is when On Hand deducts (reservation converts to a hard
        deduction at APPROVED per CLAUDE.md §17)."""
        from services.inventory_service import InventoryService

        line     = _make_line(quantity=50.0)
        xfer_row = _make_transfer_row("PENDING_APPROVAL", transfer_type="PULL")
        session  = _session_for_dispatch(xfer_row, [line])  # SELECT transfer, SELECT lines, UPDATE

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(return_value="tx-approved"),
        ) as mock_record:
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

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(side_effect=_record),
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
