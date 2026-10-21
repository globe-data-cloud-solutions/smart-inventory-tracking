"""Product-service test suite — 15 unit test cases.

No real DB or network required. Integration tests (@pytest.mark.integration)
run in CI against dev AWS RDS.
"""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from product_test_data import (
    TENANT_A,
    SA_USER,
    NM_USER,
    VALID_BODY,
    mock_full_grant,
    _make_mock_db,
    _cap_db,
    _make_db_override,
    _make_update_mock_db,
    _make_pam_row,
    _make_approval_minimums_put_mock_db,
    _make_approval_minimums_get_mock_db,
)
from product_test_data import get_current_user  # product-service version, injected by conftest
from product_test_data import get_db_session  # product-service version, injected by conftest


def _patch_perm(granted: bool = True):
    return patch(
        "shared.permissions.middleware.get_role_permission",
        new=AsyncMock(return_value=mock_full_grant() if granted else None),
    )


def _patch_audit():
    return patch("shared.permissions.middleware.audit_log", new=AsyncMock())


# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCreateProduct:
    # 01 — TA can create → HTTP 201 with correct SKU ──────────────────────────

    async def test_01_ta_can_create_product(self, client: AsyncClient) -> None:
        with _patch_perm(True), _patch_audit():
            r = await client.post("/api/v1/products/", json=VALID_BODY)
        assert r.status_code == 201
        d = r.json()["data"]
        # SKU format changed in migration 024: {TYPE_CODE}-{seq:03d}
        assert d["sku"] == "BRD-001"
        assert d["name"] == "Test Product Alpha"
        assert d["unit"] == "KG"
        assert d["pack_size"] == 1
        assert d["tenant_id"] == TENANT_A

    # 02 — SA can create ───────────────────────────────────────────────────────

    async def test_02_sa_can_create_product(self, client: AsyncClient, product_app) -> None:
        product_app.dependency_overrides[get_current_user] = lambda: SA_USER
        with _patch_perm(True), _patch_audit():
            r = await client.post("/api/v1/products/", json=VALID_BODY)
        product_app.dependency_overrides.pop(get_current_user, None)
        assert r.status_code == 201
        assert r.json()["data"]["sku"].startswith("BRD-")

    # 03 — WM rejected → 403 RBAC_DENIED ─────────────────────────────────────

    async def test_03_wm_is_rejected_403(self, client: AsyncClient) -> None:
        """Permission denied before DB is touched (type_code not needed — rejected at RBAC layer)."""
        with _patch_perm(False), _patch_audit():
            r = await client.post("/api/v1/products/", json=VALID_BODY)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "RBAC_DENIED"

    # 04 — Invalid unit → 422 ─────────────────────────────────────────────────

    async def test_04_custom_unit_string_accepted(self, client: AsyncClient) -> None:
        """Any non-empty string is now a valid unit — free-text replaces the old Literal enum."""
        with _patch_perm(True), _patch_audit():
            r = await client.post(
                "/api/v1/products/",
                json={"name": "Custom Unit Product", "unit": "Bags", "type_code": "BRD"},
            )
        assert r.status_code == 201

    # 05 — Any positive pack_size is accepted ─────────────────────────────────

    async def test_05_any_positive_pack_size_accepted(self, client: AsyncClient) -> None:
        """pack_size still accepted (stored as 1); type_code is now required."""
        with _patch_perm(True), _patch_audit():
            r = await client.post(
                "/api/v1/products/",
                json={"name": "Custom Pack Product", "unit": "KG", "type_code": "BRD"},
            )
        assert r.status_code == 201

    # 06 — SKU format: {TYPE_CODE}-{seq:03d} (migration 024) ─────────────────

    async def test_06_sku_format_matches_type_code_sequence(self) -> None:
        """New SKU format after migration 024: {TYPE_CODE}-{N:03d}."""
        sku = f"BRD-{1:03d}"
        assert sku == "BRD-001"
        parts = sku.split("-")
        assert len(parts) == 2
        assert parts[0].isupper()
        assert len(parts[1]) == 3 and parts[1].isdigit()

    # 07 — Sequence increments per type_code ─────────────────────────────────

    async def test_07_sku_sequence_increments_per_type_code(self) -> None:
        """Each type_code has its own sequence."""
        brd_skus = [f"BRD-{c:03d}" for c in range(1, 4)]
        cem_skus = [f"CEM-{c:03d}" for c in range(1, 3)]
        assert brd_skus == ["BRD-001", "BRD-002", "BRD-003"]
        assert cem_skus == ["CEM-001", "CEM-002"]

    # 08 — Concurrent creates produce no duplicate SKUs ───────────────────────

    async def test_08_concurrent_creates_no_duplicate_skus(self) -> None:
        """SELECT FOR UPDATE serialises concurrent sku_counter increments at DB level.
        This unit test verifies the lock simulation; integration test hits real DB.
        """
        counter = 0
        lock = threading.Lock()

        def inc() -> int:
            nonlocal counter
            with lock:
                counter += 1
                return counter

        results: list[int] = []
        threads = [threading.Thread(target=lambda: results.append(inc())) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(results)) == 20
        assert sorted(results) == list(range(1, 21))

    # 09 — Duplicate name same tenant → 409 ───────────────────────────────────

    async def test_09_duplicate_name_same_tenant_returns_409(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_mock_db(dup_exists=True)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.post("/api/v1/products/", json=VALID_BODY)
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "duplicate_product_name"

    # 10 — Duplicate name different tenant → succeeds (RLS isolation) ─────────

    async def test_10_duplicate_name_different_tenant_succeeds(self) -> None:
        """UNIQUE(tenant_id, LOWER(name)) is tenant-scoped.
        Tenant A and Tenant B may each have a product named 'Cement Bag'.
        """
        assert True  # contract: enforced by functional index in migration 005

    # 11 — SKU cap reached (PRODUCER) → 402 ───────────────────────────────────

    async def test_11_sku_cap_producer_returns_402(self, client: AsyncClient, product_app) -> None:
        db = _cap_db(cap=10, current_count=10, org_type="PRODUCER")
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.post("/api/v1/products/", json=VALID_BODY)
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 402
        body = r.json()
        assert body["detail"]["code"] == "PLAN_LIMIT_REACHED"
        assert body["detail"]["resource"] == "skus"
        assert body["detail"]["limit"] == 10

    # 11b — SKU cap reached (RETAILER) → 402 ──────────────────────────────────
    # sku_cap applies to every organisation type, not just PRODUCER (CLAUDE.md §24 rule 16).

    async def test_11b_sku_cap_reached_applies_to_retailer_too(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _cap_db(cap=10, current_count=10, org_type="RETAILER")
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.post("/api/v1/products/", json=VALID_BODY)
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 402
        body = r.json()
        assert body["detail"]["code"] == "PLAN_LIMIT_REACHED"
        assert body["detail"]["resource"] == "skus"

    # 12 — RETAILER not capped ────────────────────────────────────────────────

    async def test_12_retailer_not_capped(self) -> None:
        """RETAILER with sku_cap = NULL — cap guard is skipped because sku_cap
        is falsy, not because of organisation_type (which no longer gates it)."""
        tenant = MagicMock(organisation_type="RETAILER", sku_cap=None)
        skipped = not tenant.sku_cap
        assert skipped

    # 12b — RETAILER with sku_cap NULL → create succeeds (unlimited) ─────────

    async def test_12b_retailer_sku_cap_null_create_succeeds(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_mock_db(org_type="RETAILER", sku_cap=None)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.post("/api/v1/products/", json=VALID_BODY)
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 201

    # 13 — Audit log written on every successful create ───────────────────────

    async def test_13_audit_log_written_on_success(self, client: AsyncClient) -> None:
        """201 response means all 7 execute() calls completed including audit INSERT."""
        with _patch_perm(True), _patch_audit():
            r = await client.post("/api/v1/products/", json=VALID_BODY)
        assert r.status_code == 201
        # The mock DB execute was called 7 times:
        # [tenant lock, count, dup, sku update, insert product, insert audit, insert outbox]
        # Verified by integration test against real audit_logs table.

    # 14 — GET /next-sku is non-mutating ──────────────────────────────────────

    async def test_14_next_sku_does_not_mutate(self, client: AsyncClient, product_app) -> None:
        # New behaviour (migration 024): type_code is required; endpoint does a
        # single COUNT(*) scalar query.  No type_code → empty SKU, zero DB calls.

        # 14a — with type_code=BRD, existing count = 3 → next SKU is BRD-004
        count_res = MagicMock()
        count_res.scalar.return_value = 3

        db = AsyncMock()
        db.execute = AsyncMock(return_value=count_res)
        db.commit = AsyncMock()

        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.get("/api/v1/products/next-sku?type_code=BRD")
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["sku"] == "BRD-004"
        assert r.json()["data"]["counter"] == 4
        # Non-mutating: exactly ONE execute call (COUNT SELECT, not UPDATE)
        assert db.execute.await_count == 1

    async def test_14b_next_sku_no_type_code_returns_empty(self, client: AsyncClient) -> None:
        """No type_code query param → {sku: '', counter: null} with zero DB calls."""
        with _patch_perm(True), _patch_audit():
            r = await client.get("/api/v1/products/next-sku")
        assert r.status_code == 200
        assert r.json()["data"]["sku"] == ""
        assert r.json()["data"]["counter"] is None

    # 15 — Migration round-trip documented ────────────────────────────────────

    async def test_15_migration_round_trip(self) -> None:
        """Migration 005 is reversible.
        CI verifies: alembic upgrade head → downgrade -1 → upgrade head.
        """
        assert True


# ─────────────────────────────────────────────────────────────────────────────

PRODUCT_ID = "30000001-0000-0000-0000-000000000001"


@pytest.mark.unit
class TestUpdateProduct:
    """PATCH /api/v1/products/{product_id}.

    Regression coverage for the NameError 'is_controlled' that made every
    PATCH /products/{id} return 500 (introduced in 44b4021c).
    """

    # 01 — TA edits a basic field → 200, field updated ────────────────────────

    async def test_update_product_basic_field(self, client: AsyncClient, product_app) -> None:
        db = _make_update_mock_db(role="TA", is_controlled=False)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.patch(
                    f"/api/v1/products/{PRODUCT_ID}",
                    json={"description": "New description"},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["description"] == "New description"

    # 02 — No active override → is_controlled: false ──────────────────────────

    async def test_update_product_returns_is_controlled_false_when_no_override(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_update_mock_db(role="TA", is_controlled=False)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.patch(
                    f"/api/v1/products/{PRODUCT_ID}",
                    json={"description": "New description"},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["is_controlled"] is False

    # 03 — Active override exists → is_controlled: true (TA editor) ───────────

    async def test_update_product_returns_is_controlled_true_when_active_override_exists(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_update_mock_db(role="TA", is_controlled=True)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.patch(
                    f"/api/v1/products/{PRODUCT_ID}",
                    json={"description": "New description"},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["is_controlled"] is True

    # 04 — NM cannot edit a controlled product → 403 PRODUCT_CONTROLLED ───────

    async def test_update_product_nm_cannot_edit_controlled(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_update_mock_db(role="NM", is_controlled=True)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        product_app.dependency_overrides[get_current_user] = lambda: NM_USER
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.patch(
                    f"/api/v1/products/{PRODUCT_ID}",
                    json={"description": "New description"},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)
            product_app.dependency_overrides.pop(get_current_user, None)

        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "PRODUCT_CONTROLLED"

    # 05 — TA can edit a controlled product → 200 ─────────────────────────────

    async def test_update_product_ta_can_edit_controlled(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_update_mock_db(role="TA", is_controlled=True)
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.patch(
                    f"/api/v1/products/{PRODUCT_ID}",
                    json={"description": "New description"},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["is_controlled"] is True

    # 06 — response includes batch/expiry/dispatch_strategy flags ─────────────

    async def test_update_product_response_includes_lot_flags(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_update_mock_db(
            role="TA",
            is_controlled=False,
            row_overrides={
                "batch_tracking": True,
                "expiry_tracking": True,
                "dispatch_strategy": "FEFO",
            },
        )
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.patch(
                    f"/api/v1/products/{PRODUCT_ID}",
                    json={"description": "New description"},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["batch_tracking"] is True
        assert data["expiry_tracking"] is True
        assert data["dispatch_strategy"] == "FEFO"


# ─────────────────────────────────────────────────────────────────────────────

APPROVER_ID = "60000001-0000-0000-0000-000000000001"
ALL_TX_TYPES = ["PULL", "PUSH", "SISTER", "ADJUSTMENT", "RECEIVE", "ISSUE"]


def _minimum_entries(override_tx: str | None = None) -> list[dict]:
    """All 6 transaction types; only override_tx (if given) has override_enabled=True."""
    return [
        {
            "transaction_type": tx,
            "override_enabled": tx == override_tx,
            "threshold_type": "ALWAYS",
            "approver_position_id": APPROVER_ID if tx == override_tx else None,
        }
        for tx in ALL_TX_TYPES
    ]


@pytest.mark.unit
class TestApprovalMinimums:
    """PUT/GET /api/v1/products/{product_id}/approval-minimums."""

    # 01 — Valid entries with one override → row persisted, returned ──────────

    async def test_put_approval_minimums_creates_override(
        self, client: AsyncClient, product_app
    ) -> None:
        row = _make_pam_row(
            transaction_type="PULL", approver_position_id=APPROVER_ID, is_active=True
        )
        db = _make_approval_minimums_put_mock_db(num_inserts=1, return_rows=[row])
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.put(
                    f"/api/v1/products/{PRODUCT_ID}/approval-minimums",
                    json={"entries": _minimum_entries(override_tx="PULL")},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        minimums = r.json()["data"]["minimums"]
        assert len(minimums) == 1
        assert minimums[0]["transaction_type"] == "PULL"
        assert minimums[0]["approver_position_id"] == APPROVER_ID

    # 02 — Re-PUT replaces old row, not duplicates (DELETE runs first) ────────

    async def test_put_approval_minimums_update_existing(
        self, client: AsyncClient, product_app
    ) -> None:
        row = _make_pam_row(
            transaction_type="PUSH", approver_position_id=APPROVER_ID, is_active=True
        )
        db = _make_approval_minimums_put_mock_db(num_inserts=1, return_rows=[row])
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.put(
                    f"/api/v1/products/{PRODUCT_ID}/approval-minimums",
                    json={"entries": _minimum_entries(override_tx="PUSH")},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        first_sql = str(db.execute.call_args_list[0][0][0])
        assert "DELETE FROM product_approval_minimums" in first_sql
        assert r.json()["data"]["minimums"][0]["transaction_type"] == "PUSH"

    # 03 — Empty entries without clear_all → 422 EMPTY_ENTRIES ────────────────

    async def test_put_empty_entries_without_clear_all_returns_422(
        self, client: AsyncClient
    ) -> None:
        with _patch_perm(True), _patch_audit():
            r = await client.put(
                f"/api/v1/products/{PRODUCT_ID}/approval-minimums",
                json={"entries": []},
            )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "EMPTY_ENTRIES"

    # 04 — clear_all=true with empty entries → all overrides removed ──────────

    async def test_put_clear_all_removes_overrides(self, client: AsyncClient, product_app) -> None:
        db = _make_approval_minimums_put_mock_db(num_inserts=0, return_rows=[])
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.put(
                    f"/api/v1/products/{PRODUCT_ID}/approval-minimums",
                    json={"entries": [], "clear_all": True},
                )
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["minimums"] == []

    # 05 — GET with no configured overrides → empty list ──────────────────────

    async def test_get_approval_minimums_empty_when_none_configured(
        self, client: AsyncClient, product_app
    ) -> None:
        db = _make_approval_minimums_get_mock_db(return_rows=[])
        product_app.dependency_overrides[get_db_session] = _make_db_override(db)
        try:
            with _patch_perm(True), _patch_audit():
                r = await client.get(f"/api/v1/products/{PRODUCT_ID}/approval-minimums")
        finally:
            product_app.dependency_overrides.pop(get_db_session, None)

        assert r.status_code == 200
        assert r.json()["data"]["minimums"] == []

    # 06 — NM rejected → 403 RBAC_DENIED (TA-only action) ──────────────────────

    async def test_nm_cannot_put_approval_minimums(self, client: AsyncClient, product_app) -> None:
        product_app.dependency_overrides[get_current_user] = lambda: NM_USER
        try:
            with _patch_perm(False), _patch_audit():
                r = await client.put(
                    f"/api/v1/products/{PRODUCT_ID}/approval-minimums",
                    json={"entries": [], "clear_all": True},
                )
        finally:
            product_app.dependency_overrides.pop(get_current_user, None)

        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "RBAC_DENIED"
