"""Shared test data and helper factories for product-service tests.

Placed at the service root (not inside tests/) so it is importable as
`product_test_data` when the product-service root is on sys.path, with
no risk of colliding with inventory-service's `tests` package.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock


@dataclass
class _User:
    user_id: str
    tenant_id: str
    role: str
    warehouse_id: Optional[str] = None
    region_id: Optional[str] = None


TENANT_A = "10000001-0000-0000-0000-000000000001"
TENANT_B = "99999999-0000-0000-0000-000000000099"

TA_USER = _User("10000001-0000-0000-0000-000000000010", TENANT_A, "TA")
SA_USER = _User("10000001-0000-0000-0000-000000000011", TENANT_A, "SA")
WM_USER = _User("10000001-0000-0000-0000-000000000012", TENANT_A, "WM",
                warehouse_id="20000001-0000-0000-0000-000000000001")

# type_code is now required.  SKU format: {TYPE_CODE}-{seq:03d}
VALID_BODY = {"name": "Test Product Alpha", "unit": "KG", "type_code": "BRD"}


def mock_full_grant() -> MagicMock:
    g = MagicMock()
    g.grant_type = "FULL"
    return g


def _make_mock_db(
    org_type: str = "PRODUCER",
    sku_cap: Optional[int] = None,
    dup_exists: bool = False,
    count_at_cap: bool = False,
    type_code_exists: bool = False,
) -> AsyncMock:
    """Build a mock AsyncSession whose execute() side_effect matches the new
    create_product() execution order:

    With no sku_cap, no dup, no category/brand/packaging_type (VALID_BODY):
      1  tenant lock            SELECT ... FROM tenants FOR UPDATE
      2  dup name check         SELECT ... FROM products WHERE LOWER(name)=...
      3  type_code find         SELECT ... FROM product_type_codes
      4  INSERT type_code       (if new, i.e. type_code_exists=False)
      5  type_code FOR UPDATE   SELECT id FROM product_type_codes FOR UPDATE
      6  SKU sequence count     SELECT COUNT(*) FROM products WHERE sku LIKE 'BRD-%'
      7  UOM find               SELECT ... FROM product_uoms
      8  INSERT uom             (if new UOM)
      9  INSERT product
      10 INSERT audit_logs
      11 INSERT outbox          (via write_to_outbox)
    """
    db = AsyncMock()

    # ── tenant row ────────────────────────────────────────────────────────
    tenant_row = MagicMock()
    tenant_row.organisation_type = org_type
    tenant_row.sku_cap = sku_cap
    tenant_res = MagicMock()
    tenant_res.fetchone.return_value = tenant_row

    # ── cap count (only used when sku_cap is set) ─────────────────────────
    count_cap_res = MagicMock()
    count_cap_res.scalar.return_value = sku_cap if count_at_cap else 0

    # ── dup name check ────────────────────────────────────────────────────
    dup_res = MagicMock()
    dup_res.fetchone.return_value = MagicMock(id="existing") if dup_exists else None

    # ── type_code find ────────────────────────────────────────────────────
    if type_code_exists:
        tc_row = MagicMock()
        tc_row.id = "tc-001"
        tc_row.code = "BRD"
        tc_find_res = MagicMock()
        tc_find_res.fetchone.return_value = tc_row
    else:
        tc_find_res = MagicMock()
        tc_find_res.fetchone.return_value = None

    # ── SKU sequence count → 0 so first product gets seq=1 (BRD-001) ────
    sku_count_res = MagicMock()
    sku_count_res.scalar.return_value = 0

    # ── UOM find: return None (new UOM) ─────────────────────────────────
    uom_find_res = MagicMock()
    uom_find_res.fetchone.return_value = None

    # ── generic default for INSERTs ───────────────────────────────────────
    def _default() -> MagicMock:
        m = MagicMock()
        m.fetchone.return_value = None
        m.scalar.return_value = 0
        return m

    if sku_cap and count_at_cap:
        # Stops at cap check
        db.execute = AsyncMock(side_effect=[tenant_res, count_cap_res])
    elif dup_exists:
        if sku_cap:
            db.execute = AsyncMock(side_effect=[tenant_res, count_cap_res, dup_res])
        else:
            db.execute = AsyncMock(side_effect=[tenant_res, dup_res])
    elif type_code_exists:
        # type_code found — no INSERT, one less call
        # 1 tenant, 2 dup, 3 tc_find, 4 tc_lock, 5 sku_count,
        # 6 uom_find, 7 INSERT uom, 8 INSERT product, 9 INSERT audit, 10 INSERT outbox
        db.execute = AsyncMock(side_effect=[
            tenant_res, dup_res, tc_find_res, _default(), sku_count_res,
            uom_find_res, _default(), _default(), _default(), _default(),
        ])
    else:
        # Full happy path: new type_code, new UOM
        # 1 tenant, 2 dup, 3 tc_find(None), 4 INSERT tc, 5 tc_lock,
        # 6 sku_count, 7 uom_find(None), 8 INSERT uom,
        # 9 INSERT product, 10 INSERT audit, 11 INSERT outbox
        db.execute = AsyncMock(side_effect=[
            tenant_res, dup_res, tc_find_res, _default(), _default(),
            sku_count_res, uom_find_res, _default(),
            _default(), _default(), _default(),
        ])

    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _cap_db(cap: int, current_count: int, org_type: str = "PRODUCER") -> AsyncMock:
    return _make_mock_db(
        org_type=org_type,
        sku_cap=cap,
        count_at_cap=(current_count >= cap),
    )


def _make_db_override(db: AsyncMock):
    """Returns an async generator function for use in app.dependency_overrides."""
    async def _override():
        yield db
    return _override
