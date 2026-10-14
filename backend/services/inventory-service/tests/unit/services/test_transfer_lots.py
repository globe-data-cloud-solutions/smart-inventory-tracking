"""Unit tests for the transfer lot flow (services/transfer_lots.py) and its
wiring into InventoryService and the approve endpoint.

No real database: _FakeDB answers each statement by its SQL text, and a small
in-memory _World holds lot balances, stored allocations and the ledger calls,
so the real engine code (allocate, validate_manual_selection, record_override)
runs against it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from services import dispatch_service, transfer_lots
from services.dispatch_service import CandidateLot

TENANT_ID   = "10000000-0000-0000-0000-000000000001"
WAREHOUSE_A = "20000000-0000-0000-0000-000000000001"   # source
WAREHOUSE_B = "20000000-0000-0000-0000-000000000002"   # destination
PRODUCT_ID  = "aaaaaaaa-0000-0000-0000-000000000001"
PRODUCT_2   = "aaaaaaaa-0000-0000-0000-000000000002"
TRANSFER_ID = UUID("cccccccc-0000-0000-0000-000000000001")
LINE_1      = "11111111-0000-0000-0000-000000000001"
LINE_2      = "11111111-0000-0000-0000-000000000002"
LOT_A       = "0000000a-0000-0000-0000-000000000000"   # older
LOT_B       = "0000000b-0000-0000-0000-000000000000"
USER_ID     = "u-approver"
KEY_PREFIX  = f"transfer:{TRANSFER_ID}:approve:out"
TODAY       = date.today()
T0          = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class _User:
    user_id: str
    tenant_id: str
    warehouse_id: Optional[str]
    region_id: Optional[str]
    role: str


APPROVER = _User(USER_ID, TENANT_ID, None, None, "NM")


def _line(line_id: str = LINE_1, qty: str = "100", product_id: str = PRODUCT_ID) -> SimpleNamespace:
    return SimpleNamespace(id=line_id, product_id=product_id, quantity=Decimal(qty))


def _transfer_row(status: str, steps: Optional[list] = None, step: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        transfer_type="PULL",
        from_warehouse_id=WAREHOUSE_A,
        to_warehouse_id=WAREHOUSE_B,
        tenant_id=TENANT_ID,
        created_by="u-creator",
        created_by_authority_level=4,
        resolved_approval_steps=steps,
        current_approval_step=step,
        total_value=None,
        product_override_applied=False,
        is_self_approved=False,
        reference_number=None,
        from_warehouse_name=None,
        to_warehouse_name=None,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


class _World:
    """In-memory stand-in for the tables the lot flow touches."""

    def __init__(
        self,
        *,
        batch: bool = True,
        expiry: bool = False,
        lots: Optional[dict[str, tuple[str, Optional[date], int, str]]] = None,
    ) -> None:
        # products: id -> (batch_tracking, expiry_tracking, dispatch_strategy)
        self.products = {PRODUCT_ID: (batch, expiry, None), PRODUCT_2: (False, False, None)}
        # lots at the SOURCE: lot_id -> [lot_number, expiry_date, hours_after_T0, quantity]
        self.lots = {
            k: [v[0], v[1], v[2], Decimal(v[3])]
            for k, v in (lots or {
                LOT_A: ("LOT-A", None, 0, "60"),
                LOT_B: ("LOT-B", None, 1, "80"),
            }).items()
        }
        self.transfer_row: Any = None
        self.lines: list = []
        self.allocations: list[dict] = []
        self.overrides: list[dict] = []
        self.ledger: list[dict] = []     # record_transaction kwargs
        self.audit: list[dict] = []      # write_transfer_ledger_entry kwargs
        self.keys: set[str] = set()
        self.events: list[str] = []

    # ── statements ──
    async def execute(self, stmt: Any, params: Optional[dict] = None) -> MagicMock:
        sql, params = str(stmt), params or {}
        result = MagicMock()
        if "INSERT INTO transfer_line_allocations" in sql:
            self.allocations.append(dict(params))
        elif "INSERT INTO lot_allocation_overrides" in sql:
            self.overrides.append(dict(params))
            result.fetchone.return_value = SimpleNamespace(id=f"override-{len(self.overrides)}")
        elif "FROM transfer_line_allocations" in sql:
            result.fetchall.return_value = [
                SimpleNamespace(
                    transfer_line_id=a["line_id"],
                    lot_id=a["lot_id"],
                    lot_number=self.lots[a["lot_id"]][0],
                    expiry_date=self.lots[a["lot_id"]][1],
                    quantity=Decimal(a["qty"]),
                    is_override=a["is_override"],
                    product_id=a["pid"],
                )
                for a in sorted(self.allocations, key=lambda a: a["lot_id"])
            ]
        elif "FROM inventory_balances" in sql and "FOR UPDATE" in sql:
            self.events.append("lock_balance")
        elif "FROM products" in sql:
            batch, expiry, strategy = self.products[params["pid"]]
            result.fetchone.return_value = SimpleNamespace(
                batch_tracking=batch, expiry_tracking=expiry, dispatch_strategy=strategy
            )
        elif "FROM stock_lots" in sql:
            result.fetchall.return_value = [
                SimpleNamespace(id=k, lot_number=v[0], expiry_date=v[1])
                for k, v in self.lots.items()
            ]
        elif "FROM transfer_order_lines tol" in sql:
            # list / detail line items (joined to products)
            result.fetchall.return_value = [
                SimpleNamespace(
                    line_id=line.id,
                    product_id=line.product_id,
                    product_name=f"Product {line.product_id}",
                    sku=f"SKU-{line.product_id}",
                    quantity=line.quantity,
                    uom="bags",
                )
                for line in self.lines
            ]
        elif "FROM transfer_order_lines" in sql:
            result.fetchall.return_value = self.lines
        elif "FROM transfer_orders" in sql:
            result.fetchone.return_value = self.transfer_row
        return result

    # ── engine / ledger stand-ins ──
    async def load_candidate_lots(self, db, tenant_id, product_id, warehouse_id, lock=False):
        self.events.append("lock_lots" if lock else "read_lots")
        return [
            CandidateLot(k, v[0], v[1], T0 + timedelta(hours=v[2]), v[3])
            for k, v in sorted(self.lots.items())
            if v[3] > 0
        ]

    async def record_transaction(self, db, **kw: Any) -> str:
        if kw["idempotency_key"] in self.keys:
            raise HTTPException(status_code=409, detail={"code": "DUPLICATE_TRANSACTION"})
        self.keys.add(kw["idempotency_key"])
        self.ledger.append(kw)
        if kw.get("lot_id") and kw["warehouse_id"] == WAREHOUSE_A:
            self.lots[kw["lot_id"]][3] += kw["quantity"]
        return f"tx-{len(self.ledger)}"

    async def write_transfer_ledger_entry(self, **kw: Any) -> None:
        self.audit.append(kw)

    def allocate_spy(self):
        real = dispatch_service.allocate

        async def _spy(*args: Any, **kwargs: Any):
            self.events.append("allocate")
            return await real(*args, **kwargs)

        return _spy

    def db(self) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=self.execute)
        return session


@pytest.fixture
def world_patches():
    """Route the engine's lot reads and every ledger write to a _World."""

    def _apply(world: _World):
        return (
            patch("services.dispatch_service.load_candidate_lots", new=world.load_candidate_lots),
            patch("services.transfer_lots.load_candidate_lots", new=world.load_candidate_lots),
            patch("services.transfer_lots.record_transaction", new=world.record_transaction),
            patch("services.transfer_lots.write_transfer_ledger_entry",
                  new=world.write_transfer_ledger_entry),
            patch("services.transfer_lots.allocate", new=world.allocate_spy()),
        )

    return _apply


class _Patched:
    """Context manager applying a tuple of patches."""

    def __init__(self, patches: tuple) -> None:
        self._patches = patches

    def __enter__(self) -> None:
        for p in self._patches:
            p.start()

    def __exit__(self, *exc: Any) -> None:
        for p in reversed(self._patches):
            p.stop()


async def _post_out(world: _World, lines: list, **kw: Any) -> None:
    await transfer_lots.post_transfer_out(
        world.db(),
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        transfer_id=TRANSFER_ID,
        from_warehouse_id=WAREHOUSE_A,
        lines=lines,
        key_prefix=KEY_PREFIX,
        **kw,
    )


def _pick(lot_id: str, qty: str, line_id: str = LINE_1) -> list[dict]:
    return [{"line_id": line_id, "lots": [{"lot_id": lot_id, "quantity": Decimal(qty)}]}]


async def _approve(world: _World, **kw: Any):
    """Final approval through InventoryService.transition_transfer()."""
    from services.approval_service import ApprovalDecision
    from services.inventory_service import InventoryService

    with patch(
        "services.inventory_service.resolve_approval",
        new=AsyncMock(return_value=ApprovalDecision(
            required_role="WM", is_auto_approved=False,
            next_status="PENDING_APPROVAL", required_authority_level=4,
        )),
    ), patch(
        "services.inventory_service._get_simple_mode", new=AsyncMock(return_value=True),
    ), patch(
        "services.inventory_service.audit_log", new=AsyncMock(),
    ):
        return await InventoryService(world.db()).transition_transfer(
            APPROVER, TRANSFER_ID, "APPROVED", **kw
        )


# ── post_transfer_out ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPostTransferOut:

    async def test_batch_line_split_across_two_lots(self, world_patches) -> None:
        """A batch line of 100 over LOT-A 60 / LOT-B 80 posts 60 + 40, one
        TRANSFER_OUT per lot, each key ending in :lot:<lot_id>."""
        world = _World()
        with _Patched(world_patches(world)):
            await _post_out(world, [_line()])

        assert [(c["transaction_type"], c["lot_id"], c["quantity"]) for c in world.ledger] == [
            ("TRANSFER_OUT", LOT_A, Decimal("-60")),
            ("TRANSFER_OUT", LOT_B, Decimal("-40")),
        ]
        assert [c["idempotency_key"] for c in world.ledger] == [
            f"{KEY_PREFIX}:line:{LINE_1}:lot:{LOT_A}",
            f"{KEY_PREFIX}:line:{LINE_1}:lot:{LOT_B}",
        ]
        for call in world.ledger:
            assert call["warehouse_id"] == WAREHOUSE_A
            assert call["reference_id"] == str(TRANSFER_ID)
        assert [c["lot_number"] for c in world.ledger] == ["LOT-A", "LOT-B"]
        assert [(a["lot_id"], a["qty"], a["is_override"]) for a in world.allocations] == [
            (LOT_A, "60", False), (LOT_B, "40", False),
        ]

    async def test_non_batch_line_posts_one_transfer_out_with_todays_key(self, world_patches) -> None:
        """A non-batch line keeps today's single TRANSFER_OUT and today's exact
        key; nothing is allocated, locked or inserted."""
        world = _World(batch=False)
        with _Patched(world_patches(world)):
            await _post_out(world, [_line()])

        assert len(world.ledger) == 1
        call = world.ledger[0]
        assert call == {
            "tenant_id": TENANT_ID,
            "transaction_type": "TRANSFER_OUT",
            "product_id": PRODUCT_ID,
            "warehouse_id": WAREHOUSE_A,
            "quantity": Decimal("-100"),
            "performed_by": USER_ID,
            "idempotency_key": f"transfer:{TRANSFER_ID}:approve:out:line:{LINE_1}",
            "reference_id": str(TRANSFER_ID),
        }
        assert world.allocations == []
        assert world.events == [], "no balance lock and no allocate() for a non-batch line"

    async def test_replay_reuses_stored_allocations(self, world_patches) -> None:
        """A replay finds the stored allocations: allocate() is not called again,
        the same keys are used, and nothing new is written."""
        world = _World()
        with _Patched(world_patches(world)):
            await _post_out(world, [_line()])
            keys_first = sorted(world.keys)
            lots_first = {k: v[3] for k, v in world.lots.items()}

            await _post_out(world, [_line()])

        assert world.events.count("allocate") == 1, "replay must not allocate again"
        assert sorted(world.keys) == keys_first
        assert len(world.ledger) == 2 and len(world.allocations) == 2
        assert {k: v[3] for k, v in world.lots.items()} == lots_first

    async def test_two_lines_same_product_second_sees_first_debits(self, world_patches) -> None:
        """Lines are processed ORDER BY (product_id, line id) one after another:
        line 1 drains LOT-A, so line 2 is planned against what is left."""
        world = _World()
        with _Patched(world_patches(world)):
            # Passed in reverse to prove the ordering is not the caller's.
            await _post_out(world, [_line(LINE_2, "40"), _line(LINE_1, "60")])

        assert [(a["line_id"], a["lot_id"], a["qty"]) for a in world.allocations] == [
            (LINE_1, LOT_A, "60"),
            (LINE_2, LOT_B, "40"),
        ]
        assert [c["idempotency_key"] for c in world.ledger] == [
            f"{KEY_PREFIX}:line:{LINE_1}:lot:{LOT_A}",
            f"{KEY_PREFIX}:line:{LINE_2}:lot:{LOT_B}",
        ]

    async def test_balance_row_locked_before_allocate(self, world_patches) -> None:
        """Lock order is balance row, then lots — the same as record_transaction()."""
        world = _World()
        with _Patched(world_patches(world)):
            await _post_out(world, [_line()])

        assert world.events == ["lock_balance", "allocate", "lock_lots"]

    async def test_selection_for_unknown_line_is_rejected(self, world_patches) -> None:
        world = _World()
        with _Patched(world_patches(world)):
            with pytest.raises(dispatch_service.DispatchError) as exc_info:
                await _post_out(world, [_line()], selections=_pick(LOT_A, "100", line_id=LINE_2))

        assert exc_info.value.code == "SELECTION_QTY_MISMATCH"
        assert exc_info.value.detail == {"line_id": LINE_2}
        assert world.ledger == []

    async def test_selection_for_non_batch_line_is_rejected(self, world_patches) -> None:
        world = _World(batch=False)
        with _Patched(world_patches(world)):
            with pytest.raises(dispatch_service.DispatchError) as exc_info:
                await _post_out(world, [_line()], selections=_pick(LOT_A, "100"))

        assert exc_info.value.code == "LOT_NOT_TRACKED"
        assert world.ledger == []


# ── approval through InventoryService ────────────────────────────────────────

@pytest.mark.unit
class TestApproveWithLots:

    async def test_expired_lots_shortfall_returns_422_with_expired_qty(self, world_patches) -> None:
        """Expired lots are never allocated: 60 expired + 80 usable cannot cover
        100, and the error says how much is sitting in expired lots."""
        world = _World(expiry=True, lots={
            LOT_A: ("LOT-A", TODAY - timedelta(days=1), 0, "60"),
            LOT_B: ("LOT-B", TODAY + timedelta(days=90), 1, "80"),
        })
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line()]

        with _Patched(world_patches(world)):
            with pytest.raises(HTTPException) as exc_info:
                await _approve(world)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {
            "code": "INSUFFICIENT_STOCK",
            "product_id": PRODUCT_ID,
            "requested": 100.0,
            "available": 80.0,
            "expired_qty": 60.0,
        }
        assert world.ledger == [] and world.allocations == []

    async def test_fefo_selection_differing_from_plan_without_grant_is_403(self, world_patches) -> None:
        world = _World(expiry=True, lots={
            LOT_A: ("LOT-A", TODAY + timedelta(days=30), 0, "60"),
            LOT_B: ("LOT-B", TODAY + timedelta(days=90), 1, "80"),
        })
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line(qty="50")]

        with _Patched(world_patches(world)):
            with pytest.raises(HTTPException) as exc_info:
                await _approve(
                    world, lot_selections=_pick(LOT_B, "50"),
                    override_reason="customer asked", can_fefo_override=False, can_lot_select=True,
                )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == {
            "code": "OVERRIDE_NOT_PERMITTED", "strategy": "FEFO", "line_id": LINE_1,
        }
        assert world.ledger == [] and world.overrides == [] and world.allocations == []

    async def test_fefo_override_with_blank_reason_is_422(self, world_patches) -> None:
        world = _World(expiry=True, lots={
            LOT_A: ("LOT-A", TODAY + timedelta(days=30), 0, "60"),
            LOT_B: ("LOT-B", TODAY + timedelta(days=90), 1, "80"),
        })
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line(qty="50")]

        with _Patched(world_patches(world)):
            with pytest.raises(HTTPException) as exc_info:
                await _approve(
                    world, lot_selections=_pick(LOT_B, "50"),
                    override_reason="   ", can_fefo_override=True,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {"code": "OVERRIDE_REASON_REQUIRED"}
        assert world.ledger == [] and world.overrides == [] and world.allocations == []

    async def test_selection_of_expired_lot_is_rejected_at_approve(self, world_patches) -> None:
        """A manual pick of an expired lot is refused even for an approver who
        holds both dispatch:fefo_override and dispatch:lot_select."""
        world = _World(expiry=True, lots={
            LOT_A: ("LOT-A", TODAY - timedelta(days=1), 0, "60"),
            LOT_B: ("LOT-B", TODAY + timedelta(days=90), 1, "80"),
        })
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line(qty="50")]

        with _Patched(world_patches(world)):
            with pytest.raises(HTTPException) as exc_info:
                await _approve(
                    world, lot_selections=_pick(LOT_A, "50"),
                    override_reason="customer asked", can_fefo_override=True, can_lot_select=True,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {"code": "LOT_EXPIRED", "lot_id": LOT_A, "lot_number": "LOT-A"}
        assert world.ledger == [] and world.overrides == [] and world.allocations == []

    async def test_fifo_override_with_lot_select_needs_no_reason(self, world_patches) -> None:
        """FIFO: dispatch:lot_select is enough and the reason is optional. The
        override is logged and the CHOSEN lot is posted, not the plan."""
        world = _World()
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line(qty="50")]

        with _Patched(world_patches(world)):
            result = await _approve(
                world, lot_selections=_pick(LOT_B, "50"),
                can_fefo_override=False, can_lot_select=True,
            )

        assert result.status == "APPROVED"
        assert len(world.overrides) == 1
        override = world.overrides[0]
        assert (override["strategy"], override["mtype"], override["ref"], override["reason"]) == (
            "FIFO", "TRANSFER", str(TRANSFER_ID), None,
        )
        assert [(a["lot_id"], a["qty"], a["is_override"], a["override_id"]) for a in world.allocations] == [
            (LOT_B, "50", True, "override-1"),
        ]
        assert [(c["lot_id"], c["quantity"]) for c in world.ledger] == [(LOT_B, Decimal("-50"))]

    async def test_selection_matching_plan_writes_no_override(self, world_patches) -> None:
        world = _World()
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line(qty="50")]

        with _Patched(world_patches(world)):
            result = await _approve(world, lot_selections=_pick(LOT_A, "50"))

        assert result.status == "APPROVED"
        assert world.overrides == []
        assert [(a["lot_id"], a["is_override"], a["override_id"]) for a in world.allocations] == [
            (LOT_A, False, None),
        ]
        assert [(c["lot_id"], c["quantity"]) for c in world.ledger] == [(LOT_A, Decimal("-50"))]

    async def test_selections_at_non_final_step_are_rejected(self, world_patches) -> None:
        """Step 1 of 2 does not post TRANSFER_OUT, so it cannot carry lot selections."""
        steps = [
            {"sequence": n, "execution_mode": "sequential", "assigned_to_user_id": USER_ID,
             "all_holders": [], "escalated": False, "status": "pending"}
            for n in (1, 2)
        ]
        world = _World()
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL", steps, 1), [_line()]

        with _Patched(world_patches(world)):
            with pytest.raises(HTTPException) as exc_info:
                await _approve(world, lot_selections=_pick(LOT_A, "100"))

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {"code": "LOT_SELECTION_NOT_ALLOWED"}
        assert world.ledger == [] and world.allocations == []

    async def test_selections_on_a_non_approve_transition_are_rejected(self, world_patches) -> None:
        from services.inventory_service import InventoryService

        world = _World()
        world.transfer_row, world.lines = _transfer_row("PENDING_APPROVAL"), [_line()]

        with _Patched(world_patches(world)):
            with pytest.raises(HTTPException) as exc_info:
                await InventoryService(world.db()).transition_transfer(
                    APPROVER, TRANSFER_ID, "CANCELLED", lot_selections=_pick(LOT_A, "100"),
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == {"code": "LOT_SELECTION_NOT_ALLOWED"}


# ── after approval: cancel, dispatch, receive ────────────────────────────────

def _approved_world(status: str) -> _World:
    """A transfer whose line of 100 was already split LOT-A 60 / LOT-B 40."""
    world = _World()
    world.transfer_row, world.lines = _transfer_row(status), [_line()]
    for lot_id, qty in ((LOT_A, "60"), (LOT_B, "40")):
        world.allocations.append({
            "line_id": LINE_1, "lot_id": lot_id, "qty": qty, "pid": PRODUCT_ID,
            "is_override": False, "override_id": None,
        })
    return world


@pytest.mark.unit
class TestLotsAfterApproval:

    async def test_cancel_after_approval_reverses_each_lot_at_source(self, world_patches) -> None:
        from services.inventory_service import InventoryService

        world = _approved_world("APPROVED")
        with _Patched(world_patches(world)), patch(
            "services.inventory_service.write_transfer_ledger_entry", new=AsyncMock(),
        ) as line_level:
            result = await InventoryService(world.db()).transition_transfer(
                APPROVER, TRANSFER_ID, "CANCELLED"
            )

        assert result.status == "CANCELLED"
        assert line_level.await_count == 0, "a line with allocations has no line-level reversal"
        assert [
            (c["transaction_type"], c["warehouse_id"], c["lot_id"], c["quantity"]) for c in world.audit
        ] == [
            ("TRANSFER_REVERSAL", WAREHOUSE_A, LOT_A, Decimal("60")),
            ("TRANSFER_REVERSAL", WAREHOUSE_A, LOT_B, Decimal("40")),
        ]
        assert [c["line_id"] for c in world.audit] == [f"{LINE_1}:{LOT_A}", f"{LINE_1}:{LOT_B}"]
        assert {c["status_transition"] for c in world.audit} == {"APPROVED_TO_CANCELLED"}

    async def test_dispatch_and_receive_move_the_same_lots(self, world_patches) -> None:
        """TRANSIT_* audit rows are written per lot with lot_id, and TRANSFER_IN
        credits the destination per lot on the SAME lot_ids."""
        from services.inventory_service import InventoryService

        src = _User("u-src", TENANT_ID, WAREHOUSE_A, None, "WM")
        dst = _User("u-dst", TENANT_ID, WAREHOUSE_B, None, "WM")
        world = _approved_world("APPROVED")

        with _Patched(world_patches(world)), patch(
            "services.inventory_service.write_transfer_ledger_entry", new=AsyncMock(),
        ) as line_level, patch(
            "services.inventory_service.record_transaction", new=AsyncMock(),
        ) as line_level_ledger, patch(
            "services.inventory_service.audit_log", new=AsyncMock(),
        ), patch(
            "services.inventory_service.write_to_outbox", new=AsyncMock(),
        ) as outbox:
            await InventoryService(world.db()).dispatch_transfer(src, TRANSFER_ID)
            world.transfer_row.status = "ISSUED"
            await InventoryService(world.db()).transition_transfer(src, TRANSFER_ID, "IN_TRANSIT")
            world.transfer_row.status = "IN_TRANSIT"
            result = await InventoryService(world.db()).receive_transfer(dst, TRANSFER_ID)

        assert result.status == "RECEIVED"
        assert line_level.await_count == 0 and line_level_ledger.await_count == 0

        audit = [
            (c["transaction_type"], c["status_transition"], c["warehouse_id"], c["lot_id"],
             c["quantity"], c["line_id"])
            for c in world.audit
        ]
        assert audit == [
            ("TRANSIT_OUT", "APPROVED_TO_ISSUED", WAREHOUSE_A, LOT_A, Decimal("60"), f"{LINE_1}:{LOT_A}"),
            ("TRANSIT_OUT", "APPROVED_TO_ISSUED", WAREHOUSE_A, LOT_B, Decimal("40"), f"{LINE_1}:{LOT_B}"),
            ("TRANSIT_OUT", "ISSUED_TO_IN_TRANSIT", WAREHOUSE_A, LOT_A, Decimal("60"), f"{LINE_1}:{LOT_A}"),
            ("TRANSIT_OUT", "ISSUED_TO_IN_TRANSIT", WAREHOUSE_A, LOT_B, Decimal("40"), f"{LINE_1}:{LOT_B}"),
            ("TRANSIT_IN", "ISSUED_TO_IN_TRANSIT", WAREHOUSE_B, LOT_A, Decimal("60"), f"{LINE_1}:{LOT_A}"),
            ("TRANSIT_IN", "ISSUED_TO_IN_TRANSIT", WAREHOUSE_B, LOT_B, Decimal("40"), f"{LINE_1}:{LOT_B}"),
            ("TRANSIT_CLEAR", "IN_TRANSIT_TO_RECEIVED", WAREHOUSE_A, LOT_A, Decimal("-60"), f"{LINE_1}:{LOT_A}"),
            ("TRANSIT_CLEAR", "IN_TRANSIT_TO_RECEIVED", WAREHOUSE_A, LOT_B, Decimal("-40"), f"{LINE_1}:{LOT_B}"),
            ("TRANSIT_CLEAR", "IN_TRANSIT_TO_RECEIVED", WAREHOUSE_B, LOT_A, Decimal("-60"), f"{LINE_1}:{LOT_A}:dest"),
            ("TRANSIT_CLEAR", "IN_TRANSIT_TO_RECEIVED", WAREHOUSE_B, LOT_B, Decimal("-40"), f"{LINE_1}:{LOT_B}:dest"),
        ]
        # Every audit key is unique: {transfer}:{type}:{transition}:{line_id}
        keys = [(c["transaction_type"], c["status_transition"], c["line_id"]) for c in world.audit]
        assert len(set(keys)) == len(keys)

        assert [
            (c["transaction_type"], c["warehouse_id"], c["lot_id"], c["lot_number"], c["quantity"],
             c["idempotency_key"])
            for c in world.ledger
        ] == [
            ("TRANSFER_IN", WAREHOUSE_B, LOT_A, "LOT-A", Decimal("60"),
             f"transfer:{TRANSFER_ID}:receive:in:line:{LINE_1}:lot:{LOT_A}"),
            ("TRANSFER_IN", WAREHOUSE_B, LOT_B, "LOT-B", Decimal("40"),
             f"transfer:{TRANSFER_ID}:receive:in:line:{LINE_1}:lot:{LOT_B}"),
        ]

        # StockTransferred stays one per line with the line total.
        transferred = [c.args for c in outbox.await_args_list if c.args[2] == "StockTransferred"]
        assert len(transferred) == 1
        assert transferred[0][3].quantity == 100.0

    async def test_get_transfer_returns_lot_allocations(self, world_patches) -> None:
        from services.inventory_service import InventoryService

        world = _approved_world("APPROVED")
        world.transfer_row.is_self_approved = False
        result = await InventoryService(world.db()).get_transfer(APPROVER, TRANSFER_ID)

        assert [
            (str(a.line_id), str(a.product_id), str(a.lot_id), a.lot_number, a.quantity, a.is_override)
            for a in result.lot_allocations
        ] == [
            (LINE_1, PRODUCT_ID, LOT_A, "LOT-A", Decimal("60"), False),
            (LINE_1, PRODUCT_ID, LOT_B, "LOT-B", Decimal("40"), False),
        ]


# ── approve endpoint ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestApproveEndpoint:

    @staticmethod
    def _response() -> Any:
        from schemas.inventory import TransferOrderResponse

        return TransferOrderResponse(
            transfer_id=TRANSFER_ID, transfer_type="PULL", status="APPROVED",
            from_warehouse_id=UUID(WAREHOUSE_A), to_warehouse_id=UUID(WAREHOUSE_B),
            created_at=datetime.now(timezone.utc),
        )

    async def test_approve_with_no_body_is_unchanged(self, client, wm_user) -> None:
        """POST /approve with no body still works and calls the service exactly
        as before — no lot arguments, no extra permission lookups."""
        from shared.permissions.middleware import PermissionResult

        check = AsyncMock(return_value=PermissionResult(allowed=True))
        with patch("shared.permissions.middleware.check_permission", check), \
             patch("routers.transfer.InventoryService") as svc_cls:
            svc_cls.return_value.transition_transfer = AsyncMock(return_value=self._response())
            resp = await client.post(f"/api/v1/inventory/transfers/{TRANSFER_ID}/approve")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "APPROVED"
        assert resp.json()["data"]["lot_allocations"] == []
        svc_cls.return_value.transition_transfer.assert_awaited_once_with(
            wm_user, TRANSFER_ID, "APPROVED"
        )
        assert [c.args[1].id for c in check.await_args_list] == ["transfer:approve"]

    async def test_approve_with_selections_resolves_both_grants(self, wm_user) -> None:
        """With lot_selections the router resolves dispatch:fefo_override (tenant)
        and dispatch:lot_select (at the SOURCE warehouse) and passes them on."""
        from routers.transfer import approve_transfer
        from schemas.inventory import TransferApproveRequest
        from shared.permissions.middleware import PermissionResult

        seen: dict[str, dict] = {}

        async def _check(user: Any, permission: Any, resource: dict, **_: Any) -> Any:
            seen[permission.id] = resource
            return PermissionResult(allowed=permission.id != "dispatch:fefo_override")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            fetchone=MagicMock(return_value=SimpleNamespace(from_warehouse_id=WAREHOUSE_A))
        ))
        body = TransferApproveRequest(
            lot_selections=[{"line_id": LINE_1, "lots": [{"lot_id": LOT_B, "quantity": "50"}]}],
            override_reason="short-dated stock held back",
        )

        with patch("shared.permissions.middleware.check_permission", new=_check), \
             patch("shared.billing.contract_stage.get_tenant_contract_stage",
                   AsyncMock(return_value={"stage": "ACTIVE", "contract_end": None,
                                           "read_only_since": None})), \
             patch("routers.transfer.InventoryService") as svc_cls:
            svc_cls.return_value.transition_transfer = AsyncMock(return_value=self._response())
            await approve_transfer(transfer_id=TRANSFER_ID, body=body, user=wm_user, db=db)

        svc_cls.return_value.transition_transfer.assert_awaited_once_with(
            wm_user, TRANSFER_ID, "APPROVED",
            lot_selections=body.lot_selections,
            override_reason="short-dated stock held back",
            can_fefo_override=False,
            can_lot_select=True,
        )
        assert seen["dispatch:fefo_override"] == {"tenant_id": wm_user.tenant_id}
        assert seen["dispatch:lot_select"] == {
            "tenant_id": wm_user.tenant_id, "warehouse_id": WAREHOUSE_A,
        }

    def test_approve_request_schema_limits(self) -> None:
        from pydantic import ValidationError
        from schemas.inventory import TransferApproveRequest

        assert TransferApproveRequest().lot_selections is None
        for bad in (
            {"lot_selections": [{"line_id": LINE_1, "lots": []}]},
            {"lot_selections": [{"line_id": LINE_1, "lots": [{"lot_id": LOT_A, "quantity": "0"}]}]},
            {"override_reason": "x" * 501},
            {"override_reason": "bad\x00reason"},
        ):
            with pytest.raises(ValidationError):
                TransferApproveRequest(**bad)
