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
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.product import (
    ApprovalMinimumEntry, ApprovalMinimumResponse,
    ApprovalMinimumsUpsertRequest, ProductApprovalMinimumsResponse,
    ApprovalRuleEntry, ApprovalRuleResponse,
    ApprovalRulesUpsertRequest, ProductApprovalRulesResponse,
    BrandCreateRequest, BrandResponse,
    CategoryCreateRequest, CategoryResponse,
    NextSkuResponse,
    PackagingTypeCreateRequest, PackagingTypeResponse,
    ProductCreateRequest, ProductResponse,
    TypeCodeCreateRequest, TypeCodeResponse,
    UomCreateRequest, UomResponse,
)

router = APIRouter()


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
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    base_select = (
        "SELECT p.id, p.sku, p.name, p.short_name, p.description, "
        "p.unit, p.pack_size, p.reorder_point, p.unit_price, p.currency, "
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
                  "ORDER BY similarity(p.name, :q) DESC LIMIT 50"
            ),
            {"tid": str(user.tenant_id), "q": q},
        )
    else:
        result = await db.execute(
            text(
                base_select
                + "WHERE p.tenant_id = :tid AND p.is_active = true "
                  "ORDER BY p.name LIMIT 200"
            ),
            {"tid": str(user.tenant_id)},
        )
    rows = result.fetchall()
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
                "category":         r.category,
                "brand":            r.brand,
                "type_code":        r.type_code,
                "packaging_type":   r.packaging_type,
                "units_per_package": r.units_per_package,
            }
            for r in rows
        ]
    )


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
      429  sku_cap_reached (PRODUCER tenants only)
    """
    tid = str(user.tenant_id)
    uid = str(user.user_id) if getattr(user, "user_id", None) else None

    # 1. Lock tenant row for SKU cap check (CLAUDE.md §24 rule 16).
    tenant_result = await db.execute(
        text(
            "SELECT organisation_type, sku_cap FROM tenants WHERE id = :tid FOR UPDATE"
        ),
        {"tid": tid},
    )
    tenant = tenant_result.fetchone()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. SKU cap — PRODUCER tenants only.
    if tenant.organisation_type == "PRODUCER" and tenant.sku_cap:
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM products WHERE tenant_id = :tid AND is_active = true"),
            {"tid": tid},
        )
        if (count_result.scalar() or 0) >= tenant.sku_cap:
            raise HTTPException(
                status_code=429,
                detail={
                    "code":           "sku_cap_reached",
                    "upgrade_prompt": True,
                    "message":        "SKU cap reached for this tenant's plan",
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
            tenant_id=uuid.UUID(tid),
            created_at=now,
            created_by=uuid.UUID(uid) if uid else None,
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
            SELECT id, transaction_type, min_authority_level, created_by,
                   created_at, updated_at
            FROM   product_approval_minimums
            WHERE  product_id = :pid AND tenant_id = :tid
            ORDER BY transaction_type
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
    """Replace all product-level authority floor overrides.

    Entries with min_authority_level=None delete the override for that tx_type.
    Send an empty list to clear all overrides.
    Audit log written in the same transaction (CLAUDE.md §8, §14).
    """
    tid = str(user.tenant_id)
    pid = product_id
    now = datetime.now(timezone.utc)

    await db.execute(
        text("DELETE FROM product_approval_minimums "
             "WHERE product_id = :pid AND tenant_id = :tid"),
        {"pid": pid, "tid": tid},
    )

    for entry in body.entries:
        if entry.min_authority_level is None:
            continue
        await db.execute(
            text("""
                INSERT INTO product_approval_minimums
                  (tenant_id, product_id, transaction_type, min_authority_level,
                   created_by, created_at, updated_at)
                VALUES
                  (:tid, :pid, :tx_type, :min_auth, :by, :now, :now)
            """),
            {
                "tid":      tid,
                "pid":      pid,
                "tx_type":  entry.transaction_type,
                "min_auth": entry.min_authority_level,
                "by":       str(user.user_id),
                "now":      now,
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
