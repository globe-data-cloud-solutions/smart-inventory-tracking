"""Unit tests for get_stock() analytics — specifically the double-deduction bug.

Root cause: pending_out_qty originally used status IN ('APPROVED','IN_TRANSIT').
At APPROVED, transition_transfer() writes a TRANSFER_OUT ledger entry that already
reduces inventory_balances.quantity (= current_stock). Including the APPROVED transfer
in pending_out_qty caused net_available = current_stock - pending_out_qty = 1900 - 100
= 1800, a double deduction.

Correct WMS Option A behaviour (per CLAUDE.md §17 and inventory-state.ts):
  pending_out_qty  = PENDING_REVIEW/PENDING_APPROVAL/PENDING_*_CONFIRM only
                     DRAFT is excluded: it carries no stock commitment and creates
                     no reservation — source Reserved must be 0 at DRAFT status.
  in_transit_out_qty = ISSUED/IN_TRANSIT (informational; On Hand already reduced at APPROVED)
  net_available    = current_stock - pending_out_qty   (in_transit_out NOT subtracted)

Column trace (qty = 100, source start = 2000):
  PENDING_APPROVAL : current_stock=2000, pending_out=100, in_transit_out=0, available=1900
  APPROVED         : current_stock=1900, pending_out=0,   in_transit_out=0, available=1900
  ISSUED           : current_stock=1900, pending_out=0,   in_transit_out=100, available=1900
  IN_TRANSIT       : current_stock=1900, pending_out=0,   in_transit_out=100, available=1900
  RECEIVED         : current_stock=1900, pending_out=0,   in_transit_out=0,   available=1900
"""
from __future__ import annotations

import pytest

from schemas.analytics import InventoryStockOut
from decimal import Decimal


@pytest.mark.unit
class TestInventoryStockOutSchema:

    def test_approved_transfer_does_not_double_deduct_available(self) -> None:
        """net_available must equal current_stock when pending_out_qty is 0.

        After APPROVED: current_stock is already reduced by the TRANSFER_OUT ledger entry.
        pending_out_qty must be 0 (APPROVED is not a soft hold).
        net_available = 1900 - 0 = 1900, not 1900 - 100 = 1800.
        """
        item = InventoryStockOut(
            product_id="aaaaaaaa-0000-0000-0000-000000000001",
            product_name="Cement 50kg",
            product_sku="CEM-001",
            warehouse_id="20000000-0000-0000-0000-000000000001",
            warehouse_name="AW North",
            current_stock=Decimal("1900"),   # already reduced by TRANSFER_OUT at APPROVED
            pending_out_qty=Decimal("0"),    # APPROVED is NOT a soft hold
            in_transit_out_qty=Decimal("0"),
            in_transit_in_qty=Decimal("0"),
            requested_qty=Decimal("0"),
        )
        assert item.net_available == Decimal("1900"), (
            "At APPROVED: current_stock already reflects the deduction. "
            "pending_out_qty must be 0. net_available must equal current_stock."
        )

    def test_pending_approval_reserves_without_reducing_on_hand(self) -> None:
        """net_available = current_stock - pending_out_qty at PENDING_APPROVAL.

        On Hand has NOT been reduced yet (no ledger entry). The soft hold is
        reflected in pending_out_qty, reducing available but not current_stock.
        """
        item = InventoryStockOut(
            product_id="aaaaaaaa-0000-0000-0000-000000000001",
            product_name="Cement 50kg",
            product_sku="CEM-001",
            warehouse_id="20000000-0000-0000-0000-000000000001",
            warehouse_name="AW North",
            current_stock=Decimal("2000"),    # On Hand not yet reduced
            pending_out_qty=Decimal("100"),   # soft hold at PENDING_APPROVAL
            in_transit_out_qty=Decimal("0"),
            in_transit_in_qty=Decimal("0"),
            requested_qty=Decimal("0"),
        )
        assert item.net_available == Decimal("1900"), (
            "At PENDING_APPROVAL: pending_out=100 reduces available to 1900, "
            "but current_stock stays at 2000 (no ledger entry yet)."
        )

    def test_issued_in_transit_out_is_informational_only(self) -> None:
        """in_transit_out_qty does NOT reduce net_available — it is informational.

        After ISSUED: current_stock=1900 (deducted at APPROVED), in_transit_out=100.
        net_available must still be 1900, not 1900 - 100 = 1800.
        """
        item = InventoryStockOut(
            product_id="aaaaaaaa-0000-0000-0000-000000000001",
            product_name="Cement 50kg",
            product_sku="CEM-001",
            warehouse_id="20000000-0000-0000-0000-000000000001",
            warehouse_name="AW North",
            current_stock=Decimal("1900"),
            pending_out_qty=Decimal("0"),
            in_transit_out_qty=Decimal("100"),  # informational: stock physically in transit
            in_transit_in_qty=Decimal("0"),
            requested_qty=Decimal("0"),
        )
        assert item.net_available == Decimal("1900"), (
            "in_transit_out_qty is informational. "
            "It must NOT be subtracted from net_available — On Hand already reflects the deduction."
        )

    def test_draft_transfer_does_not_reserve_stock(self) -> None:
        """DRAFT status must produce pending_out_qty=0 and net_available=current_stock.

        The SQL filter in get_stock() excludes 'DRAFT' from pending_out_qty by design
        (CLAUDE.md §17): a DRAFT transfer carries no stock commitment and can be
        discarded at any time. Reserved (soft hold) only begins at PENDING_REVIEW.
        """
        item = InventoryStockOut(
            product_id="aaaaaaaa-0000-0000-0000-000000000001",
            product_name="Cement 50kg",
            product_sku="CEM-001",
            warehouse_id="20000000-0000-0000-0000-000000000001",
            warehouse_name="AW North",
            current_stock=Decimal("2000"),
            pending_out_qty=Decimal("0"),    # DRAFT excluded — no soft hold
            in_transit_out_qty=Decimal("0"),
            in_transit_in_qty=Decimal("0"),
            requested_qty=Decimal("0"),
        )
        assert item.net_available == Decimal("2000"), (
            "At DRAFT: pending_out_qty must be 0. net_available must equal current_stock. "
            "The SQL filter enforces this by excluding DRAFT from the pending_out query."
        )

    def test_net_available_full_column_trace(self) -> None:
        """Full WMS Option A column trace for a qty=100 outbound transfer.

        Verifies available stays at 1900 from APPROVED through IN_TRANSIT.
        """
        PRODUCT_ID   = "aaaaaaaa-0000-0000-0000-000000000001"
        WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001"

        def _item(current: str, pending: str, transit_out: str) -> InventoryStockOut:
            return InventoryStockOut(
                product_id=PRODUCT_ID, product_name="X", product_sku="X-001",
                warehouse_id=WAREHOUSE_ID, warehouse_name="WH",
                current_stock=Decimal(current), pending_out_qty=Decimal(pending),
                in_transit_out_qty=Decimal(transit_out), in_transit_in_qty=Decimal("0"),
                requested_qty=Decimal("0"),
            )

        # PENDING_APPROVAL: On Hand=2000, soft hold=100, available=1900
        assert _item("2000", "100", "0").net_available == Decimal("1900")
        # APPROVED: On Hand=1900 (deducted), soft hold cleared, available=1900
        assert _item("1900", "0",   "0").net_available == Decimal("1900")
        # ISSUED: in_transit_out=100 (informational), available still 1900
        assert _item("1900", "0", "100").net_available == Decimal("1900")
        # IN_TRANSIT: same as ISSUED from source perspective
        assert _item("1900", "0", "100").net_available == Decimal("1900")
