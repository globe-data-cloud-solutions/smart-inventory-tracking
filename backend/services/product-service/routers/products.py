"""Product-service routes.

SKU generation (CLAUDE.md §24 rule 3 — updated in migration 024):
  Format:  {TYPE_CODE}-{sequence:03d}   e.g. "BRD-001", "CEM-042"
  Type code is resolved from product_type_codes (find-or-create per tenant).
  Sequence = COUNT of existing products whose SKU starts with "{TYPE_CODE}-" + 1.
  The type_code row is locked FOR UPDATE to prevent concurrent SKU collisions.
  sku_override bypasses generation if the caller supplies a custom SKU.

All lookup tables (brands, type_codes, uoms, packaging_types, categories) are
per-tenant — RLS enforced at the DB layer.  Endpoints follow create-or-select:
POST returns existing row if name/code already exists for this tenant.

Audit log and outbox are written inside the same transaction (CLAUDE.md §8, §14).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db_session
from shared.outbox.schemas import ProductCreatedPayload
from shared.outbox.writer import write_to_outbox
from shared.permissions.middleware import require_permission
from shared.permissions.plan_middleware import _UPGRADE_TO
from shared.permissions.registry import PERMISSIONS
from shared.plans.usage import count_active_skus
from shared.utils.responses import SuccessResponse
from schemas.product import (
    ApprovalMinimumEntry, ApprovalMinimumResponse,
    ApprovalMinimumsUpsertRequest, ProductApprovalMinimumsResponse,
    ProductApprovalOverride,
    ApprovalRuleEntry, ApprovalRuleResponse,
    ApprovalRulesUpsertRequest, ProductApprovalRulesResponse,
    BrandCreateRequest, BrandResponse,
    CategoryCreateRequest, CategoryResponse,
    NextSkuResponse,
    PackagingTypeCreateRequest, PackagingTypeResponse,
    ProductCreateRequest, ProductResponse, ProductUpdateRequest,
    TypeCodeCreateRequest, TypeCodeResponse,
    UomCreateRequest, UomResponse,
)

router = APIRouter()


async def _raise_if_controlled(db: AsyncSession, tid: str, pid: str, role: Optional[str]) -> None:
    """Raise PRODUCT_CONTROLLED (403) if this product has an active Design-B
    approval override and the caller is not TA/SA.

    Shared by PATCH /{id}, POST /{id}/discontinue, and POST /{id}/reactivate —
    any state-changing action on a controlled product is Tenant-Admin-only.
    """
    if role in ("TA", "SA"):
        return
    is_controlled = bool((await db.execute(
        text(
            "SELECT 1 FROM product_approval_minimums "
            "WHERE tenant_id = :tid AND product_id = :pid "
            "AND is_active = TRUE AND approver_position_id IS NOT NULL "
            "LIMIT 1"
        ),
        {"tid": tid, "pid": pid},
    )).fetchone())
    if is_controlled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PRODUCT_CONTROLLED",
                "message": "This product has approval overrides configured and can only be edited by the Tenant Admin.",
            },
        )


# ── GET /next-sku — MUST appear before any /{id} route ───────────────────────

@router.get("/next-sku", response_model=SuccessResponse[NextSkuResponse])
@require_permission(PERMISSIONS.PRODUCT_READ_NEXT_SKU)
async def preview_next_sku(
    type_code: Optional[str] = Query(None, description="Type code prefix for SKU preview"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[NextSkuResponse]:
    """Non-mutating SKU preview.  Does NOT increment any counter.
    Returns {sku: 'BRD-004', counter: 4} for the next product with type_code=BRD.
    """
    if not type_code:
        return SuccessResponse(data=NextSkuResponse(sku="", counter=None))

    tc = type_code.strip().upper()
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM products "
            "WHERE tenant_id = :tid AND sku LIKE :prefix AND is_active = true"
        ),
        {"tid": str(user.tenant_id), "prefix": f"{tc}-%"},
    )
    count = int(count_result.scalar() or 0)
    next_num = count + 1
    sku = f"{tc}-{next_num:03d}"
    return SuccessResponse(data=NextSkuResponse(sku=sku, counter=next_num))


# ── GET / ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST)
async def list_products(
    q: Optional[str] = Query(None, description="pg_trgm name / SKU search"),
    active_only: bool = Query(True, description="Exclude discontinued products"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    base_select = (
        "SELECT p.id, p.sku, p.name, p.short_name, p.description, "
        "p.unit, p.pack_size, p.reorder_point, p.unit_price, p.currency, "
        "p.image_url, p.is_discontinued, "
        "p.batch_tracking, p.expiry_tracking, p.dispatch_strategy, "
        "pc.name AS category, "
        "pb.name AS brand, "
        "ptc.code AS type_code, "
        "ppt.name AS packaging_type, ppt.units_per_package "
        "FROM products p "
        "LEFT JOIN product_categories pc ON pc.id = p.category_id "
        "LEFT JOIN product_brands pb ON pb.id = p.brand_id "
        "LEFT JOIN product_type_codes ptc ON ptc.id = p.type_code_id "
        "LEFT JOIN product_packaging_types ppt ON ppt.id = p.packaging_type_id "
    )
    if q:
        result = await db.execute(
            text(
                base_select
                + "WHERE p.tenant_id = :tid AND p.name % :q AND p.is_active = true "
                  "AND (NOT :active_only OR p.is_discontinued = FALSE) "
                  "ORDER BY similarity(p.name, :q) DESC LIMIT 50"
            ),
            {"tid": str(user.tenant_id), "q": q, "active_only": active_only},
        )
    else:
        result = await db.execute(
            text(
                base_select
                + "WHERE p.tenant_id = :tid AND p.is_active = true "
                  "AND (NOT :active_only OR p.is_discontinued = FALSE) "
                  "ORDER BY p.name LIMIT 200"
            ),
            {"tid": str(user.tenant_id), "active_only": active_only},
        )
    rows = result.fetchall()

    # Computed approval_overrides — Design-B per-product overrides (migration 050),
    # keyed by product_id then transaction_type. Consumed by NewTransferPanel /
    # NewAdjustmentPanel (PART F) to render the lock icon + tooltip.
    overrides_by_product: dict[str, dict[str, ProductApprovalOverride]] = {}
    if rows:
        override_rows = (await db.execute(
            text("""
                SELECT pam.product_id, pam.transaction_type, pam.threshold_type,
                       pam.qty_threshold, pam.value_threshold, pam.note,
                       pos.title AS approver_title
                FROM   product_approval_minimums pam
                LEFT JOIN positions pos ON pos.id = pam.approver_position_id
                WHERE  pam.tenant_id = :tid
                  AND  pam.is_active = TRUE
                  AND  pam.approver_position_id IS NOT NULL
            """),
            {"tid": str(user.tenant_id)},
        )).fetchall()
        for o in override_rows:
            threshold = o.qty_threshold if o.threshold_type == "QUANTITY" else (
                o.value_threshold if o.threshold_type == "VALUE" else None
            )
            overrides_by_product.setdefault(str(o.product_id), {})[o.transaction_type] = (
                ProductApprovalOverride(
                    mode=o.threshold_type,
                    threshold=threshold,
                    approver_label=o.approver_title,
                    note=o.note,
                )
            )

    return SuccessResponse(
        data=[
            {
                "id":               str(r.id),
                "sku":              r.sku,
                "name":             r.name,
                "short_name":       r.short_name,
                "description":      r.description,
                "unit":             getattr(r, "unit", None),
                "pack_size":        getattr(r, "pack_size", None),
                "reorder_point":    float(r.reorder_point) if r.reorder_point is not None else None,
                "unit_price":       float(r.unit_price) if getattr(r, "unit_price", None) is not None else None,
                "currency":         getattr(r, "currency", None),
                "is_discontinued":  bool(r.is_discontinued),
                "image_url":        r.image_url,
                "category":         r.category,
                "brand":            r.brand,
                "type_code":        r.type_code,
                "packaging_type":   r.packaging_type,
                "units_per_package": r.units_per_package,
                "batch_tracking":   bool(r.batch_tracking),
                "expiry_tracking":  bool(r.expiry_tracking),
                "dispatch_strategy": r.dispatch_strategy,
                "approval_overrides": {
                    tx: o.model_dump(mode="json")
                    for tx, o in overrides_by_product.get(str(r.id), {}).items()
                },
                "is_controlled": bool(overrides_by_product.get(str(r.id))),
            }
            for r in rows
        ]
    )


# ── POST /{id}/discontinue ────────────────────────────────────────────────────

@router.post("/{product_id}/discontinue", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.PRODUCT_DISCONTINUE)
async def discontinue_product(
    product_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """Mark a product as discontinued. Blocked if any warehouse holds stock or pending transfers exist."""
    tid = str(user.tenant_id)
    pid = str(product_id)
    role = getattr(user, "role", None)

    # Controlled-product check (CLAUDE.md Design-B overrides) — same gate as PATCH /{id}.
    await _raise_if_controlled(db, tid, pid, role)

    # Check stock across all warehouses
    stock_rows = (await db.execute(
        text(
            "SELECT ib.warehouse_id::text, COALESCE(n.name, ib.warehouse_id::text) AS warehouse_name, "
            "SUM(ib.quantity) AS on_hand "
            "FROM inventory_balances ib "
            "LEFT JOIN organization_node n ON n.id = ib.warehouse_id "
            "WHERE ib.product_id = :pid AND ib.tenant_id = :tid "
            "GROUP BY ib.warehouse_id, n.name "
            "HAVING SUM(ib.quantity) > 0"
        ),
        {"pid": pid, "tid": tid},
    )).fetchall()

    if stock_rows:
        locations = [
            {"warehouse": r.warehouse_name, "on_hand": float(r.on_hand)}
            for r in stock_rows
        ]
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PRODUCT_HAS_STOCK",
                "message": "Cannot discontinue. Clear all stock first.",
                "locations": locations,
            },
        )

    # Check pending transfers
    pending_count = (await db.execute(
        text(
            "SELECT COUNT(*) FROM transfer_orders t "
            "WHERE t.tenant_id = :tid "
            "AND t.status IN ('PENDING_REVIEW','PENDING_APPROVAL','APPROVED','IN_TRANSIT') "
            "AND EXISTS ("
            "  SELECT 1 FROM transfer_order_lines tol "
            "  WHERE tol.transfer_order_id = t.id AND tol.product_id = :pid"
            ")"
        ),
        {"pid": pid, "tid": tid},
    )).scalar() or 0

    if pending_count > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PRODUCT_HAS_PENDING_TRANSACTIONS",
                "message": "Cannot discontinue. Pending transfers exist.",
            },
        )

    await db.execute(
        text(
            "UPDATE products SET is_discontinued = TRUE, updated_at = NOW() "
            "WHERE id = :pid AND tenant_id = :tid"
        ),
        {"pid": pid, "tid": tid},
    )
    return SuccessResponse(data={"product_id": pid, "is_discontinued": True})


# ── POST /{id}/reactivate ─────────────────────────────────────────────────────

@router.post("/{product_id}/reactivate", response_model=SuccessResponse[dict])
@require_permission(PERMISSIONS.PRODUCT_REACTIVATE)
async def reactivate_product(
    product_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[dict]:
    """Reactivate a discontinued product."""
    tid = str(user.tenant_id)
    pid = str(product_id)
    role = getattr(user, "role", None)

    # Controlled-product check (CLAUDE.md Design-B overrides) — same gate as PATCH /{id}.
    await _raise_if_controlled(db, tid, pid, role)

    await db.execute(
        text(
            "UPDATE products SET is_discontinued = FALSE, updated_at = NOW() "
            "WHERE id = :pid AND tenant_id = :tid"
        ),
        {"pid": pid, "tid": tid},
    )
    return SuccessResponse(data={"product_id": pid, "is_discontinued": False})


# ── POST / ───────────────────────────────────────────────────────────────────

@router.post("/", status_code=201, response_model=SuccessResponse[ProductResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE)
async def create_product(
    body: ProductCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductResponse]:
    """Create a new product.

    Lookup fields (category, brand, type_code, unit/uom, packaging_type) all use
    create-or-select: an existing row is returned if name/code matches for this tenant.

    SKU generation: locks the type_code row FOR UPDATE, counts existing products
    with that code prefix, then assigns {TYPE_CODE}-{N:03d}.  sku_override bypasses
    generation entirely (uniqueness still enforced by the UNIQUE constraint).

    Error codes:
      403  RBAC_DENIED / ABAC_DENIED
      409  duplicate_product_name | duplicate_sku
      422  invalid_type_code
      402  PLAN_LIMIT_REACHED, resource=skus (applies whenever tenant.sku_cap is
           set, any organisation_type) — same shape as the users/warehouses
           plan-limit errors in shared/permissions/plan_middleware.py.
    """
    tid = str(user.tenant_id)
    uid = str(user.user_id) if getattr(user, "user_id", None) else None

    # 1. Lock tenant row for SKU cap check (CLAUDE.md §24 rule 16).
    tenant_result = await db.execute(
        text(
            "SELECT organisation_type, sku_cap, plan_tier FROM tenants WHERE id = :tid FOR UPDATE"
        ),
        {"tid": tid},
    )
    tenant = tenant_result.fetchone()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. SKU cap — applies to every organisation type (CLAUDE.md §24 rule 16).
    if tenant.sku_cap:
        current = await count_active_skus(db, tid)
        if current >= tenant.sku_cap:
            plan_tier = str(tenant.plan_tier) if tenant.plan_tier else None
            raise HTTPException(
                status_code=402,
                detail={
                    "code":       "PLAN_LIMIT_REACHED",
                    "resource":   "skus",
                    "current":    current,
                    "limit":      tenant.sku_cap,
                    "plan_tier":  plan_tier,
                    "upgrade_to": _UPGRADE_TO.get(plan_tier),
                    "message": (
                        f"SKU limit reached ({current}/{tenant.sku_cap}). "
                        f"Upgrade to add more products."
                    ),
                },
            )

    # 3. Duplicate name guard (case-insensitive).
    dup = await db.execute(
        text(
            "SELECT id FROM products "
            "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:name) AND is_active = true"
        ),
        {"tid": tid, "name": body.name},
    )
    if dup.fetchone():
        raise HTTPException(
            status_code=409,
            detail={
                "code":    "duplicate_product_name",
                "message": "A product with this name already exists in this tenant",
            },
        )

    # 4. Resolve category — find or create.
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    if body.category:
        cat_row = (await db.execute(
            text("SELECT id, name FROM product_categories "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": body.category},
        )).fetchone()
        if cat_row:
            category_id, category_name = str(cat_row.id), cat_row.name
        else:
            category_id = str(uuid.uuid4())
            category_name = body.category
            await db.execute(
                text("INSERT INTO product_categories (id, tenant_id, name) "
                     "VALUES (:id, :tid, :n)"),
                {"id": category_id, "tid": tid, "n": category_name},
            )

    # 5. Resolve brand — find or create.
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    if body.brand:
        br_row = (await db.execute(
            text("SELECT id, name FROM product_brands "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": body.brand},
        )).fetchone()
        if br_row:
            brand_id, brand_name = str(br_row.id), br_row.name
        else:
            brand_id = str(uuid.uuid4())
            brand_name = body.brand
            await db.execute(
                text("INSERT INTO product_brands (id, tenant_id, name) "
                     "VALUES (:id, :tid, :n)"),
                {"id": brand_id, "tid": tid, "n": brand_name},
            )

    # 6. Resolve type_code — find or create, then lock FOR UPDATE for SKU generation.
    tc_row = (await db.execute(
        text("SELECT id, code FROM product_type_codes "
             "WHERE tenant_id = :tid AND UPPER(code) = :code AND is_active = true"),
        {"tid": tid, "code": body.type_code},
    )).fetchone()
    if tc_row:
        type_code_id = str(tc_row.id)
    else:
        type_code_id = str(uuid.uuid4())
        await db.execute(
            text("INSERT INTO product_type_codes (id, tenant_id, code) "
                 "VALUES (:id, :tid, :code)"),
            {"id": type_code_id, "tid": tid, "code": body.type_code},
        )

    # Lock the type_code row to prevent concurrent SKU sequence races.
    await db.execute(
        text("SELECT id FROM product_type_codes WHERE id = :id FOR UPDATE"),
        {"id": type_code_id},
    )

    # 7. Generate or validate SKU.
    if body.sku_override:
        sku = body.sku_override
        dup_sku = (await db.execute(
            text("SELECT id FROM products WHERE tenant_id = :tid AND sku = :sku"),
            {"tid": tid, "sku": sku},
        )).fetchone()
        if dup_sku:
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate_sku", "message": f"SKU '{sku}' already exists"},
            )
    else:
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM products "
                 "WHERE tenant_id = :tid AND sku LIKE :prefix AND is_active = true"),
            {"tid": tid, "prefix": f"{body.type_code}-%"},
        )
        seq = int(count_result.scalar() or 0) + 1
        sku = f"{body.type_code}-{seq:03d}"

    # 8. Resolve UOM — find or create in product_uoms (string stored on products.unit).
    uom_name = body.unit
    uom_row = (await db.execute(
        text("SELECT id FROM product_uoms "
             "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
        {"tid": tid, "n": uom_name},
    )).fetchone()
    if not uom_row:
        await db.execute(
            text("INSERT INTO product_uoms (id, tenant_id, name) VALUES (:id, :tid, :n)"),
            {"id": str(uuid.uuid4()), "tid": tid, "n": uom_name},
        )

    # 9. Resolve packaging type — find or create.
    packaging_type_id: Optional[str] = None
    packaging_type_name: Optional[str] = None
    resolved_units_per_package: Optional[int] = None
    if body.packaging_type:
        pt_row = (await db.execute(
            text("SELECT id, name, units_per_package FROM product_packaging_types "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": body.packaging_type},
        )).fetchone()
        if pt_row:
            packaging_type_id = str(pt_row.id)
            packaging_type_name = pt_row.name
            resolved_units_per_package = pt_row.units_per_package
        else:
            packaging_type_id = str(uuid.uuid4())
            packaging_type_name = body.packaging_type
            resolved_units_per_package = body.units_per_package or 1
            await db.execute(
                text("INSERT INTO product_packaging_types "
                     "  (id, tenant_id, name, units_per_package) "
                     "VALUES (:id, :tid, :n, :upp)"),
                {"id": packaging_type_id, "tid": tid,
                 "n": packaging_type_name, "upp": resolved_units_per_package},
            )

    # 10. INSERT product.
    product_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            "INSERT INTO products "
            "  (id, tenant_id, sku, name, short_name, description, "
            "   unit_of_measure, unit, pack_size, "
            "   category_id, brand_id, type_code_id, packaging_type_id, "
            "   reorder_point, unit_price, currency, is_active, created_by) "
            "VALUES "
            "  (:id, :tid, :sku, :name, :short_name, :description, "
            "   :uom, :unit, :pack_size, "
            "   :cat_id, :brand_id, :tc_id, :pt_id, "
            "   :reorder_point, :unit_price, :currency, true, :uid)"
        ),
        {
            "id":            product_id,
            "tid":           tid,
            "sku":           sku,
            "name":          body.name,
            "short_name":    body.short_name,
            "description":   body.description,
            "uom":           uom_name,
            "unit":          uom_name,
            "pack_size":     1,
            "cat_id":        category_id,
            "brand_id":      brand_id,
            "tc_id":         type_code_id,
            "pt_id":         packaging_type_id,
            "reorder_point": float(body.reorder_point) if body.reorder_point is not None else None,
            "unit_price":    float(body.unit_price) if body.unit_price is not None else None,
            "currency":      body.currency,
            "uid":           uid,
        },
    )

    # 11. Audit log — append-only, same transaction (CLAUDE.md §7 + §14).
    await db.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'product:create', 'product', "
            "   :rid, 'GRANTED', CAST(:ctx AS jsonb))"
        ),
        {
            "id":   str(uuid.uuid4()),
            "tid":  tid,
            "uid":  uid,
            "role": getattr(user, "role", None),
            "rid":  product_id,
            "ctx":  json.dumps({
                "sku":           sku,
                "name":          body.name,
                "type_code":     body.type_code,
                "unit":          uom_name,
                "category":      category_name,
                "brand":         brand_name,
                "unit_price":    str(body.unit_price) if body.unit_price is not None else None,
                "currency":      body.currency,
            }),
        },
    )

    # 12. Outbox — same transaction, never post-commit (CLAUDE.md §8, §24 rule 6).
    await write_to_outbox(
        db,
        tid,
        "ProductCreated",
        ProductCreatedPayload(
            product_id=product_id,
            sku=sku,
            name=body.name,
            unit=uom_name,
            pack_size=1,
            created_by=uid or "system",
        ),
    )

    return SuccessResponse(
        data=ProductResponse(
            id=uuid.UUID(product_id),
            sku=sku,
            name=body.name,
            short_name=body.short_name,
            description=body.description,
            unit=uom_name,
            pack_size=1,
            category=category_name,
            type_code=body.type_code,
            brand=brand_name,
            packaging_type=packaging_type_name,
            units_per_package=resolved_units_per_package,
            reorder_point=body.reorder_point,
            unit_price=body.unit_price,
            currency=body.currency,
            batch_tracking=False,
            expiry_tracking=False,
            dispatch_strategy=None,
            tenant_id=uuid.UUID(tid),
            created_at=now,
            created_by=uuid.UUID(uid) if uid else None,
        )
    )


# ── PATCH /{id} ───────────────────────────────────────────────────────────────

@router.patch("/{product_id}", response_model=SuccessResponse[ProductResponse])
@require_permission(PERMISSIONS.PRODUCT_UPDATE)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductResponse]:
    """Edit an existing product. SKU is immutable.

    TA/SA may edit any product. NM and below may only edit a product that
    has no active Design-B approval override (product_approval_minimums row
    with approver_position_id IS NOT NULL AND is_active = TRUE) — such a
    product is "controlled" and can only be edited by the Tenant Admin.
    """
    tid = str(user.tenant_id)
    pid = str(product_id)
    uid = str(user.user_id) if getattr(user, "user_id", None) else None
    role = getattr(user, "role", None)

    row = (await db.execute(
        text(
            "SELECT p.id, p.sku, p.name, p.short_name, p.description, "
            "p.unit, p.pack_size, p.reorder_point, p.unit_price, p.currency, "
            "p.image_url, "
            "p.batch_tracking, p.expiry_tracking, p.dispatch_strategy, "
            "p.category_id, p.brand_id, p.type_code_id, p.packaging_type_id, "
            "p.tenant_id, p.created_at, p.created_by, "
            "pc.name AS category, pb.name AS brand, ptc.code AS type_code, "
            "ppt.name AS packaging_type, ppt.units_per_package "
            "FROM products p "
            "LEFT JOIN product_categories pc ON pc.id = p.category_id "
            "LEFT JOIN product_brands pb ON pb.id = p.brand_id "
            "LEFT JOIN product_type_codes ptc ON ptc.id = p.type_code_id "
            "LEFT JOIN product_packaging_types ppt ON ppt.id = p.packaging_type_id "
            "WHERE p.id = :pid AND p.tenant_id = :tid AND p.is_active = true"
        ),
        {"pid": pid, "tid": tid},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")

    # Controlled-product check (CLAUDE.md Design-B overrides).
    await _raise_if_controlled(db, tid, pid, role)

    # Duplicate name guard (case-insensitive), excluding this product.
    if body.name is not None and body.name.lower() != row.name.lower():
        dup = (await db.execute(
            text(
                "SELECT id FROM products "
                "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:name) "
                "AND is_active = true AND id != :pid"
            ),
            {"tid": tid, "name": body.name, "pid": pid},
        )).fetchone()
        if dup:
            raise HTTPException(
                status_code=409,
                detail={
                    "code":    "duplicate_product_name",
                    "message": "A product with this name already exists in this tenant",
                },
            )

    set_clauses: list[str] = ["updated_at = NOW()"]
    params: dict[str, object] = {"pid": pid, "tid": tid}

    if body.name is not None:
        set_clauses.append("name = :name")
        params["name"] = body.name
    if body.short_name is not None:
        set_clauses.append("short_name = :short_name")
        params["short_name"] = body.short_name
    if body.description is not None:
        set_clauses.append("description = :description")
        params["description"] = body.description
    if body.reorder_point is not None:
        set_clauses.append("reorder_point = :reorder_point")
        params["reorder_point"] = float(body.reorder_point)
    if body.unit_price is not None:
        set_clauses.append("unit_price = :unit_price")
        params["unit_price"] = float(body.unit_price)
    if body.currency is not None:
        set_clauses.append("currency = :currency")
        params["currency"] = body.currency
    if body.image_url is not None:
        set_clauses.append("image_url = :image_url")
        params["image_url"] = body.image_url

    # Category — find or create.
    category_name = row.category
    if body.category is not None:
        cat_row = (await db.execute(
            text("SELECT id, name FROM product_categories "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": body.category},
        )).fetchone()
        if cat_row:
            category_id, category_name = str(cat_row.id), cat_row.name
        else:
            category_id = str(uuid.uuid4())
            category_name = body.category
            await db.execute(
                text("INSERT INTO product_categories (id, tenant_id, name) "
                     "VALUES (:id, :tid, :n)"),
                {"id": category_id, "tid": tid, "n": category_name},
            )
        set_clauses.append("category_id = :category_id")
        params["category_id"] = category_id

    # Brand — find or create.
    brand_name = row.brand
    if body.brand is not None:
        br_row = (await db.execute(
            text("SELECT id, name FROM product_brands "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": body.brand},
        )).fetchone()
        if br_row:
            brand_id, brand_name = str(br_row.id), br_row.name
        else:
            brand_id = str(uuid.uuid4())
            brand_name = body.brand
            await db.execute(
                text("INSERT INTO product_brands (id, tenant_id, name) "
                     "VALUES (:id, :tid, :n)"),
                {"id": brand_id, "tid": tid, "n": brand_name},
            )
        set_clauses.append("brand_id = :brand_id")
        params["brand_id"] = brand_id

    # Type code — find or create. SKU itself is never regenerated.
    type_code_value = row.type_code
    if body.type_code is not None:
        tc_row = (await db.execute(
            text("SELECT id, code FROM product_type_codes "
                 "WHERE tenant_id = :tid AND UPPER(code) = :code AND is_active = true"),
            {"tid": tid, "code": body.type_code},
        )).fetchone()
        if tc_row:
            type_code_id, type_code_value = str(tc_row.id), tc_row.code
        else:
            type_code_id = str(uuid.uuid4())
            type_code_value = body.type_code
            await db.execute(
                text("INSERT INTO product_type_codes (id, tenant_id, code) "
                     "VALUES (:id, :tid, :code)"),
                {"id": type_code_id, "tid": tid, "code": type_code_value},
            )
        set_clauses.append("type_code_id = :type_code_id")
        params["type_code_id"] = type_code_id

    # Unit / UOM — find or create in product_uoms; products.unit stores the raw string.
    unit_value = row.unit
    if body.unit is not None:
        unit_value = body.unit
        uom_row = (await db.execute(
            text("SELECT id FROM product_uoms "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": unit_value},
        )).fetchone()
        if not uom_row:
            await db.execute(
                text("INSERT INTO product_uoms (id, tenant_id, name) VALUES (:id, :tid, :n)"),
                {"id": str(uuid.uuid4()), "tid": tid, "n": unit_value},
            )
        set_clauses.append("unit = :unit")
        set_clauses.append("unit_of_measure = :unit")
        params["unit"] = unit_value

    # Packaging type — find or create.
    packaging_type_name = row.packaging_type
    units_per_package = row.units_per_package
    if body.packaging_type is not None:
        pt_row = (await db.execute(
            text("SELECT id, name, units_per_package FROM product_packaging_types "
                 "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
            {"tid": tid, "n": body.packaging_type},
        )).fetchone()
        if pt_row:
            packaging_type_id = str(pt_row.id)
            packaging_type_name = pt_row.name
            units_per_package = pt_row.units_per_package
        else:
            packaging_type_id = str(uuid.uuid4())
            packaging_type_name = body.packaging_type
            units_per_package = body.units_per_package or 1
            await db.execute(
                text("INSERT INTO product_packaging_types "
                     "  (id, tenant_id, name, units_per_package) "
                     "VALUES (:id, :tid, :n, :upp)"),
                {"id": packaging_type_id, "tid": tid,
                 "n": packaging_type_name, "upp": units_per_package},
            )
        set_clauses.append("packaging_type_id = :packaging_type_id")
        params["packaging_type_id"] = packaging_type_id

    await db.execute(
        text(f"UPDATE products SET {', '.join(set_clauses)} WHERE id = :pid AND tenant_id = :tid"),
        params,
    )

    # Audit log — append-only, same transaction (CLAUDE.md §7 + §14).
    await db.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'product:update', 'product', "
            "   :rid, 'GRANTED', CAST(:ctx AS jsonb))"
        ),
        {
            "id":   str(uuid.uuid4()),
            "tid":  tid,
            "uid":  uid,
            "role": role,
            "rid":  pid,
            "ctx":  json.dumps(body.model_dump(mode="json", exclude_none=True)),
        },
    )

    is_controlled = bool((await db.execute(
        text(
            "SELECT 1 FROM product_approval_minimums "
            "WHERE tenant_id = :tid AND product_id = :pid "
            "AND is_active = TRUE AND approver_position_id IS NOT NULL "
            "LIMIT 1"
        ),
        {"tid": tid, "pid": pid},
    )).fetchone())

    return SuccessResponse(
        data=ProductResponse(
            id=uuid.UUID(pid),
            sku=row.sku,
            name=body.name if body.name is not None else row.name,
            short_name=body.short_name if body.short_name is not None else row.short_name,
            description=body.description if body.description is not None else row.description,
            unit=unit_value,
            pack_size=row.pack_size,
            category=category_name,
            type_code=type_code_value,
            brand=brand_name,
            packaging_type=packaging_type_name,
            units_per_package=units_per_package,
            reorder_point=body.reorder_point if body.reorder_point is not None else row.reorder_point,
            unit_price=body.unit_price if body.unit_price is not None else row.unit_price,
            currency=body.currency if body.currency is not None else row.currency,
            image_url=body.image_url if body.image_url is not None else getattr(row, "image_url", None),
            is_controlled=is_controlled,
            batch_tracking=bool(row.batch_tracking),
            expiry_tracking=bool(row.expiry_tracking),
            dispatch_strategy=row.dispatch_strategy,
            tenant_id=uuid.UUID(tid),
            created_at=row.created_at,
            created_by=row.created_by,
        )
    )


# ── GET /categories/ ─────────────────────────────────────────────────────────

@router.get("/categories/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST_CATEGORIES)
async def list_categories(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    result = await db.execute(
        text("SELECT id, tenant_id, name FROM product_categories "
             "WHERE tenant_id = :tid AND is_active = true ORDER BY name"),
        {"tid": str(user.tenant_id)},
    )
    return SuccessResponse(
        data=[{"id": str(r.id), "tenant_id": str(r.tenant_id), "name": r.name}
              for r in result.fetchall()]
    )


# ── POST /categories/ ────────────────────────────────────────────────────────

@router.post("/categories/", status_code=201, response_model=SuccessResponse[CategoryResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE_CATEGORY)
async def create_category(
    body: CategoryCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[CategoryResponse]:
    tid = str(user.tenant_id)
    row = (await db.execute(
        text("SELECT id, name FROM product_categories "
             "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
        {"tid": tid, "n": body.name},
    )).fetchone()
    if row:
        return SuccessResponse(
            data=CategoryResponse(id=uuid.UUID(str(row.id)), name=row.name, tenant_id=uuid.UUID(tid))
        )
    cat_id = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO product_categories (id, tenant_id, name) VALUES (:id, :tid, :n)"),
        {"id": cat_id, "tid": tid, "n": body.name},
    )
    return SuccessResponse(
        data=CategoryResponse(id=uuid.UUID(cat_id), name=body.name, tenant_id=uuid.UUID(tid))
    )


# ── GET /brands/ ─────────────────────────────────────────────────────────────

@router.get("/brands/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST_BRANDS)
async def list_brands(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    result = await db.execute(
        text("SELECT id, tenant_id, name FROM product_brands "
             "WHERE tenant_id = :tid AND is_active = true ORDER BY name"),
        {"tid": str(user.tenant_id)},
    )
    return SuccessResponse(
        data=[{"id": str(r.id), "tenant_id": str(r.tenant_id), "name": r.name}
              for r in result.fetchall()]
    )


# ── POST /brands/ ────────────────────────────────────────────────────────────

@router.post("/brands/", status_code=201, response_model=SuccessResponse[BrandResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE_BRAND)
async def create_brand(
    body: BrandCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[BrandResponse]:
    tid = str(user.tenant_id)
    row = (await db.execute(
        text("SELECT id, name FROM product_brands "
             "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
        {"tid": tid, "n": body.name},
    )).fetchone()
    if row:
        return SuccessResponse(
            data=BrandResponse(id=uuid.UUID(str(row.id)), name=row.name, tenant_id=uuid.UUID(tid))
        )
    bid = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO product_brands (id, tenant_id, name) VALUES (:id, :tid, :n)"),
        {"id": bid, "tid": tid, "n": body.name},
    )
    return SuccessResponse(
        data=BrandResponse(id=uuid.UUID(bid), name=body.name, tenant_id=uuid.UUID(tid))
    )


# ── GET /type-codes/ ─────────────────────────────────────────────────────────

@router.get("/type-codes/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST_TYPE_CODES)
async def list_type_codes(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    result = await db.execute(
        text("SELECT id, tenant_id, code, description FROM product_type_codes "
             "WHERE tenant_id = :tid AND is_active = true ORDER BY code"),
        {"tid": str(user.tenant_id)},
    )
    return SuccessResponse(
        data=[
            {"id": str(r.id), "tenant_id": str(r.tenant_id),
             "code": r.code, "description": r.description}
            for r in result.fetchall()
        ]
    )


# ── POST /type-codes/ ────────────────────────────────────────────────────────

@router.post("/type-codes/", status_code=201, response_model=SuccessResponse[TypeCodeResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE_TYPE_CODE)
async def create_type_code(
    body: TypeCodeCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TypeCodeResponse]:
    tid = str(user.tenant_id)
    row = (await db.execute(
        text("SELECT id, code, description FROM product_type_codes "
             "WHERE tenant_id = :tid AND UPPER(code) = :code AND is_active = true"),
        {"tid": tid, "code": body.code},
    )).fetchone()
    if row:
        return SuccessResponse(
            data=TypeCodeResponse(
                id=uuid.UUID(str(row.id)), code=row.code,
                description=row.description, tenant_id=uuid.UUID(tid),
            )
        )
    tcid = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO product_type_codes (id, tenant_id, code, description) "
             "VALUES (:id, :tid, :code, :desc)"),
        {"id": tcid, "tid": tid, "code": body.code, "desc": body.description},
    )
    return SuccessResponse(
        data=TypeCodeResponse(
            id=uuid.UUID(tcid), code=body.code,
            description=body.description, tenant_id=uuid.UUID(tid),
        )
    )


# ── GET /uoms/ ───────────────────────────────────────────────────────────────

@router.get("/uoms/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST_UOMS)
async def list_uoms(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    result = await db.execute(
        text("SELECT id, tenant_id, name FROM product_uoms "
             "WHERE tenant_id = :tid AND is_active = true ORDER BY name"),
        {"tid": str(user.tenant_id)},
    )
    return SuccessResponse(
        data=[{"id": str(r.id), "tenant_id": str(r.tenant_id), "name": r.name}
              for r in result.fetchall()]
    )


# ── POST /uoms/ ──────────────────────────────────────────────────────────────

@router.post("/uoms/", status_code=201, response_model=SuccessResponse[UomResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE_UOM)
async def create_uom(
    body: UomCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[UomResponse]:
    tid = str(user.tenant_id)
    row = (await db.execute(
        text("SELECT id, name FROM product_uoms "
             "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
        {"tid": tid, "n": body.name},
    )).fetchone()
    if row:
        return SuccessResponse(
            data=UomResponse(id=uuid.UUID(str(row.id)), name=row.name, tenant_id=uuid.UUID(tid))
        )
    uid_val = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO product_uoms (id, tenant_id, name) VALUES (:id, :tid, :n)"),
        {"id": uid_val, "tid": tid, "n": body.name},
    )
    return SuccessResponse(
        data=UomResponse(id=uuid.UUID(uid_val), name=body.name, tenant_id=uuid.UUID(tid))
    )


# ── GET /packaging-types/ ────────────────────────────────────────────────────

@router.get("/packaging-types/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST_PACKAGING_TYPES)
async def list_packaging_types(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    result = await db.execute(
        text("SELECT id, tenant_id, name, units_per_package FROM product_packaging_types "
             "WHERE tenant_id = :tid AND is_active = true ORDER BY name"),
        {"tid": str(user.tenant_id)},
    )
    return SuccessResponse(
        data=[
            {"id": str(r.id), "tenant_id": str(r.tenant_id),
             "name": r.name, "units_per_package": r.units_per_package}
            for r in result.fetchall()
        ]
    )


# ── POST /packaging-types/ ───────────────────────────────────────────────────

@router.post("/packaging-types/", status_code=201,
             response_model=SuccessResponse[PackagingTypeResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE_PACKAGING_TYPE)
async def create_packaging_type(
    body: PackagingTypeCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[PackagingTypeResponse]:
    tid = str(user.tenant_id)
    row = (await db.execute(
        text("SELECT id, name, units_per_package FROM product_packaging_types "
             "WHERE tenant_id = :tid AND LOWER(name) = LOWER(:n) AND is_active = true"),
        {"tid": tid, "n": body.name},
    )).fetchone()
    if row:
        return SuccessResponse(
            data=PackagingTypeResponse(
                id=uuid.UUID(str(row.id)), name=row.name,
                units_per_package=row.units_per_package, tenant_id=uuid.UUID(tid),
            )
        )
    ptid = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO product_packaging_types (id, tenant_id, name, units_per_package) "
             "VALUES (:id, :tid, :n, :upp)"),
        {"id": ptid, "tid": tid, "n": body.name, "upp": body.units_per_package},
    )
    return SuccessResponse(
        data=PackagingTypeResponse(
            id=uuid.UUID(ptid), name=body.name,
            units_per_package=body.units_per_package, tenant_id=uuid.UUID(tid),
        )
    )


# ── Approval rule helpers ─────────────────────────────────────────────────────

async def _read_approval_rules(
    db: AsyncSession,
    tenant_id: str,
    product_id: Optional[str],
) -> ProductApprovalRulesResponse:
    """Read approval_rule rows for a product (product-level) or for the tenant.

    If product_id is provided but has no product-level rules, returns the
    tenant-level rules and sets is_using_defaults=True.
    """
    if product_id:
        result = await db.execute(
            text("""
                SELECT id, transaction_type, min_quantity, max_quantity,
                       approver_role, approval_order, product_id
                FROM   approval_rule
                WHERE  tenant_id   = :tid
                  AND  product_id  = :pid
                  AND  is_active   = true
                ORDER BY transaction_type, approval_order
            """),
            {"tid": tenant_id, "pid": product_id},
        )
        rows = result.fetchall()
        if rows:
            return ProductApprovalRulesResponse(
                product_id=uuid.UUID(product_id),
                rules=[
                    ApprovalRuleResponse(
                        id=uuid.UUID(str(r.id)),
                        transaction_type=r.transaction_type,
                        min_quantity=r.min_quantity,
                        max_quantity=r.max_quantity,
                        approver_role=r.approver_role,
                        approval_order=r.approval_order,
                        product_id=uuid.UUID(str(r.product_id)),
                        is_product_level=True,
                    )
                    for r in rows
                ],
                is_using_defaults=False,
            )

    # Fall through to tenant-level rules
    result = await db.execute(
        text("""
            SELECT id, transaction_type, min_quantity, max_quantity,
                   approver_role, approval_order, product_id
            FROM   approval_rule
            WHERE  tenant_id  = :tid
              AND  product_id IS NULL
              AND  is_active  = true
            ORDER BY transaction_type, approval_order
        """),
        {"tid": tenant_id},
    )
    rows = result.fetchall()
    return ProductApprovalRulesResponse(
        product_id=uuid.UUID(product_id) if product_id else None,
        rules=[
            ApprovalRuleResponse(
                id=uuid.UUID(str(r.id)),
                transaction_type=r.transaction_type,
                min_quantity=r.min_quantity,
                max_quantity=r.max_quantity,
                approver_role=r.approver_role,
                approval_order=r.approval_order,
                product_id=None,
                is_product_level=False,
            )
            for r in rows
        ],
        is_using_defaults=True,
    )


# ── GET /approval-rules/latest — MUST appear before /{product_id} routes ──────

@router.get("/approval-rules/latest",
            response_model=SuccessResponse[ProductApprovalRulesResponse])
@require_permission(PERMISSIONS.PRODUCT_VIEW_APPROVAL_RULES)
async def get_latest_approval_rules(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductApprovalRulesResponse]:
    """Return approval rules from the most recently created product that has
    product-level overrides.  Falls back to tenant-level rules.

    Used by the Add Product panel to pre-populate the Approval Thresholds section
    with the previous product's rules so the operator does not re-enter them.
    """
    tid = str(user.tenant_id)

    # Find the most recently created product that has product-level approval rules
    latest = await db.execute(
        text("""
            SELECT ar.product_id
            FROM   approval_rule ar
            JOIN   products p ON p.id = ar.product_id
            WHERE  ar.tenant_id    = :tid
              AND  ar.product_id IS NOT NULL
              AND  ar.is_active    = true
              AND  p.tenant_id     = :tid
              AND  p.is_active     = true
            ORDER BY p.created_at DESC
            LIMIT 1
        """),
        {"tid": tid},
    )
    row = latest.fetchone()
    pid = str(row[0]) if row else None
    data = await _read_approval_rules(db, tid, pid)
    return SuccessResponse(data=data)


# ── GET /{product_id}/approval-rules ─────────────────────────────────────────

@router.get("/{product_id}/approval-rules",
            response_model=SuccessResponse[ProductApprovalRulesResponse])
@require_permission(PERMISSIONS.PRODUCT_VIEW_APPROVAL_RULES)
async def get_product_approval_rules(
    product_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductApprovalRulesResponse]:
    """Return approval rules for a specific product.

    Returns product-level rules when the product has its own overrides.
    Returns tenant-level rules (is_using_defaults=True) when no product-level
    rules exist — so the caller always sees the effective rules.
    """
    tid = str(user.tenant_id)
    data = await _read_approval_rules(db, tid, product_id)
    return SuccessResponse(data=data)


# ── PUT /{product_id}/approval-rules ─────────────────────────────────────────

@router.put("/{product_id}/approval-rules",
            response_model=SuccessResponse[ProductApprovalRulesResponse])
@require_permission(PERMISSIONS.PRODUCT_MANAGE_APPROVAL_RULES)
async def upsert_product_approval_rules(
    product_id: str,
    body: ApprovalRulesUpsertRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductApprovalRulesResponse]:
    """Upsert product-level approval rules (TA and NM only).

    Replaces all existing product-level rules for this product with the
    supplied list.  Send an empty list to reset to tenant defaults.

    Audit log is written inside the same transaction (CLAUDE.md §8, §14).
    """
    tid = str(user.tenant_id)
    pid = product_id

    # Delete existing product-level rules for this product (replace semantics)
    await db.execute(
        text("DELETE FROM approval_rule "
             "WHERE tenant_id = :tid AND product_id = :pid"),
        {"tid": tid, "pid": pid},
    )

    # Insert new product-level rules
    for entry in body.rules:
        rid = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO approval_rule
                  (id, tenant_id, transaction_type, min_quantity, max_quantity,
                   approver_role, approval_order, product_id, is_active)
                VALUES
                  (:id, :tid, :tx_type, :min_qty, :max_qty,
                   :approver_role, :approval_order, :pid, true)
            """),
            {
                "id":             rid,
                "tid":            tid,
                "tx_type":        entry.transaction_type,
                "min_qty":        str(entry.min_quantity) if entry.min_quantity is not None else None,
                "max_qty":        str(entry.max_quantity) if entry.max_quantity is not None else None,
                "approver_role":  entry.approver_role,
                "approval_order": entry.approval_order,
                "pid":            pid,
            },
        )

    # Audit log (inside same transaction)
    await db.execute(
        text("""
            INSERT INTO audit_logs
              (tenant_id, user_id, role, action, resource_type, resource_id, decision)
            VALUES (:tid, :uid, :role, 'product:manage_approval_rules',
                    'product', :rid, 'GRANTED')
        """),
        {
            "tid":  tid,
            "uid":  str(user.user_id),
            "role": user.role,
            "rid":  uuid.UUID(pid),
        },
    )

    data = await _read_approval_rules(db, tid, pid)
    return SuccessResponse(data=data)


# ── GET /{product_id}/approval-minimums ───────────────────────────────────────

async def _read_approval_minimums(
    db: AsyncSession,
    tenant_id: str,
    product_id: str,
) -> ProductApprovalMinimumsResponse:
    rows = (await db.execute(
        text("""
            SELECT pam.id, pam.transaction_type, pam.min_authority_level,
                   pam.threshold_type, pam.qty_threshold, pam.value_threshold,
                   pam.approver_position_id, pam.note, pam.is_active,
                   pos.title AS approver_title,
                   pam.created_by, pam.created_at, pam.updated_at
            FROM   product_approval_minimums pam
            LEFT JOIN positions pos ON pos.id = pam.approver_position_id
            WHERE  pam.product_id = :pid AND pam.tenant_id = :tid
            ORDER BY pam.transaction_type
        """),
        {"pid": product_id, "tid": tenant_id},
    )).fetchall()
    return ProductApprovalMinimumsResponse(
        product_id=uuid.UUID(product_id),
        minimums=[
            ApprovalMinimumResponse(
                id=uuid.UUID(str(r.id)),
                product_id=uuid.UUID(product_id),
                transaction_type=r.transaction_type,
                min_authority_level=r.min_authority_level,
                override_enabled=bool(r.is_active and r.approver_position_id is not None),
                threshold_type=r.threshold_type,
                qty_threshold=r.qty_threshold,
                value_threshold=r.value_threshold,
                approver_position_id=uuid.UUID(str(r.approver_position_id)) if r.approver_position_id else None,
                approver_label=r.approver_title,
                note=r.note,
                created_by=uuid.UUID(str(r.created_by)),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ],
    )


@router.get("/{product_id}/approval-minimums",
            response_model=SuccessResponse[ProductApprovalMinimumsResponse])
@require_permission(PERMISSIONS.PRODUCT_VIEW)
async def get_product_approval_minimums(
    product_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductApprovalMinimumsResponse]:
    """Return per-product authority floor overrides from product_approval_minimums."""
    data = await _read_approval_minimums(db, str(user.tenant_id), product_id)
    return SuccessResponse(data=data)


# ── PUT /{product_id}/approval-minimums ───────────────────────────────────────

@router.put("/{product_id}/approval-minimums",
            response_model=SuccessResponse[ProductApprovalMinimumsResponse])
@require_permission(PERMISSIONS.PRODUCT_MANAGE_APPROVAL_MINIMUMS)
async def upsert_product_approval_minimums(
    product_id: str,
    body: ApprovalMinimumsUpsertRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductApprovalMinimumsResponse]:
    """Replace all product-level approval configuration (authority floor + Design-B override).

    An entry is persisted only if min_authority_level is not None OR
    override_enabled is True; otherwise any existing row for that tx_type is
    dropped. Send entries=[] with clear_all=true to clear all overrides —
    a missing/empty entries list without clear_all is rejected with 422 so
    a malformed body cannot silently wipe existing configuration.
    Audit log written in the same transaction (CLAUDE.md §8, §14).
    """
    if not body.entries and not body.clear_all:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMPTY_ENTRIES",
                "message": "entries cannot be empty unless clear_all=true",
            },
        )

    tid = str(user.tenant_id)
    pid = product_id
    now = datetime.now(timezone.utc)

    await db.execute(
        text("DELETE FROM product_approval_minimums "
             "WHERE product_id = :pid AND tenant_id = :tid"),
        {"pid": pid, "tid": tid},
    )

    for entry in body.entries:
        if entry.min_authority_level is None and not entry.override_enabled:
            continue
        await db.execute(
            text("""
                INSERT INTO product_approval_minimums
                  (tenant_id, product_id, transaction_type, min_authority_level,
                   threshold_type, qty_threshold, value_threshold,
                   approver_position_id, note, is_active,
                   created_by, created_at, updated_at)
                VALUES
                  (:tid, :pid, :tx_type, :min_auth,
                   :threshold_type, :qty_threshold, :value_threshold,
                   :approver_position_id, :note, :is_active,
                   :by, :now, :now)
            """),
            {
                "tid":                  tid,
                "pid":                  pid,
                "tx_type":              entry.transaction_type,
                "min_auth":             entry.min_authority_level,
                "threshold_type":       entry.threshold_type,
                "qty_threshold":        entry.qty_threshold,
                "value_threshold":      entry.value_threshold,
                "approver_position_id": str(entry.approver_position_id) if entry.approver_position_id else None,
                "note":                 entry.note,
                "is_active":            entry.override_enabled,
                "by":                   str(user.user_id),
                "now":                  now,
            },
        )

    await db.execute(
        text("""
            INSERT INTO audit_logs
              (tenant_id, user_id, role, action, resource_type, resource_id, decision)
            VALUES (:tid, :uid, :role, 'product:manage_approval_minimums',
                    'product', :rid, 'GRANTED')
        """),
        {
            "tid":  tid,
            "uid":  str(user.user_id),
            "role": user.role,
            "rid":  uuid.UUID(pid),
        },
    )

    data = await _read_approval_minimums(db, tid, pid)
    return SuccessResponse(data=data)
