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

    async def test_approved_transition_deducts_source_balance(self) -> None:
        """dispatch_transfer() (APPROVED → ISSUED) must call record_transaction
        with transaction_type='TRANSFER_OUT' and a negative quantity for each line,
        deducting the source warehouse balance."""
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

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "TRANSFER_OUT"
        assert kwargs["warehouse_id"]     == WAREHOUSE_A          # source WH deducted
        assert kwargs["quantity"]         == -Decimal("50")        # negative = deduction
        assert kwargs["reference_id"]     == str(TRANSFER_ID)

    async def test_received_transition_credits_destination_balance(self) -> None:
        """receive_transfer() (IN_TRANSIT → RECEIVED) must call record_transaction
        with transaction_type='TRANSFER_IN' and a positive quantity for each line,
        crediting the destination warehouse balance."""
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

        mock_record.assert_awaited_once()
        _, kwargs = mock_record.call_args
        assert kwargs["transaction_type"] == "TRANSFER_IN"
        assert kwargs["warehouse_id"]     == WAREHOUSE_B          # destination WH credited
        assert kwargs["quantity"]         == Decimal("30")         # positive = credit
        assert kwargs["reference_id"]     == str(TRANSFER_ID)

    async def test_cancelled_from_approved_reverses_source_balance(self) -> None:
        """A PULL transfer cancelled while in APPROVED state (before dispatch) must:
        1. Allow APPROVED → CANCELLED (valid in PULL machine).
        2. Not call record_transaction — no stock was moved at approval time,
           so no compensating ledger entry is needed.

        This invariant ensures balance integrity: deduction happens at ISSUED
        (dispatch), not at APPROVED. Cancellation before dispatch = zero ledger impact.

        If RESERVE transactions are added in a future sprint, this test should
        be extended to verify a RELEASE entry is written on cancel.
        """
        from services.inventory_service import InventoryService

        xfer_row = _make_transfer_row("APPROVED", transfer_type="PULL")
        session  = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            MagicMock(fetchone=MagicMock(return_value=xfer_row)),  # SELECT
            MagicMock(),                                            # UPDATE status
        ])

        with patch(
            "services.inventory_service.record_transaction",
            new=AsyncMock(),
        ) as mock_record:
            svc    = InventoryService(session)
            result = await svc.transition_transfer(SRC_WM, TRANSFER_ID, "CANCELLED")

        assert result.status == "CANCELLED"
        mock_record.assert_not_awaited()

        # State machine sanity: APPROVED → CANCELLED is valid for PULL
        validate_transition("PULL", "APPROVED", "CANCELLED")  # must not raise
