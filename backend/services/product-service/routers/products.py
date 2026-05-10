"""Product-service routes.

SKU generation convention (CLAUDE.md §24 rule 3):
  Every product has a tenant-scoped SKU.
  Format:  {sku_prefix}-{sku_counter:04d}   e.g. "ETH-0047"
  Generated inside the same DB transaction as the products INSERT,
  using SELECT FOR UPDATE on the tenants row (prevents race conditions).

Audit log and outbox are written inside the same transaction (CLAUDE.md §8, §14).
Both actions registered in registry.py before this file was written (CLAUDE.md §1).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.outbox.schemas import ProductCreatedPayload
from shared.outbox.writer import write_to_outbox
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from schemas.product import NextSkuResponse, ProductCreateRequest, ProductResponse

router = APIRouter()


# ── GET /next-sku — MUST appear before any /{id} route ───────────────────────

@router.get("/next-sku", response_model=SuccessResponse[NextSkuResponse])
@require_permission(PERMISSIONS.PRODUCT_READ_NEXT_SKU)
async def preview_next_sku(
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[NextSkuResponse]:
    """Non-mutating SKU preview.  Does NOT increment sku_counter.
    Used by the frontend AddProductPanel to show the pending SKU value.
    """
    result = await db.execute(
        text(
            "SELECT sku_prefix, sku_counter + 1 AS next_num "
            "FROM tenants WHERE id = :tid"
        ),
        {"tid": str(user.tenant_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    sku = f"{row.sku_prefix}-{row.next_num:04d}"
    return SuccessResponse(data=NextSkuResponse(sku=sku))


# ── GET / ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=SuccessResponse[list])
@require_permission(PERMISSIONS.PRODUCT_LIST)
async def list_products(
    q: Optional[str] = Query(None, description="pg_trgm name / SKU search"),
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[list]:
    if q:
        result = await db.execute(
            text(
                "SELECT id, sku, name, unit, pack_size FROM products "
                "WHERE tenant_id = :tid AND name % :q AND is_active = true "
                "ORDER BY similarity(name, :q) DESC LIMIT 50"
            ),
            {"tid": str(user.tenant_id), "q": q},
        )
    else:
        result = await db.execute(
            text(
                "SELECT id, sku, name, unit, pack_size FROM products "
                "WHERE tenant_id = :tid AND is_active = true "
                "ORDER BY name LIMIT 100"
            ),
            {"tid": str(user.tenant_id)},
        )
    rows = result.fetchall()
    return SuccessResponse(
        data=[
            {
                "id":        str(r.id),
                "sku":       r.sku,
                "name":      r.name,
                "unit":      getattr(r, "unit", None),
                "pack_size": getattr(r, "pack_size", None),
            }
            for r in rows
        ]
    )


# ── POST / ───────────────────────────────────────────────────────────────────

@router.post("/", status_code=201, response_model=SuccessResponse[ProductResponse])
@require_permission(PERMISSIONS.PRODUCT_CREATE)
async def create_product(
    body: ProductCreateRequest,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[ProductResponse]:
    """Create a new product with server-side atomic SKU generation.

    All writes happen in a single transaction (product, sku_counter, audit_log, outbox).

    Error codes:
      403  RBAC_DENIED / ABAC_DENIED
      409  duplicate_product_name
      422  invalid unit or pack_size
      429  sku_cap_reached (PRODUCER tenants only)
    """
    tid = str(user.tenant_id)
    uid = str(user.user_id) if getattr(user, "user_id", None) else None

    # 1. Lock tenant row — prevents concurrent sku_counter races.
    tenant_result = await db.execute(
        text(
            "SELECT organisation_type, sku_cap, sku_prefix, sku_counter "
            "FROM tenants WHERE id = :tid FOR UPDATE"
        ),
        {"tid": tid},
    )
    tenant = tenant_result.fetchone()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. SKU cap — PRODUCER tenants only (CLAUDE.md §24 rule 16 + §1 ABAC sku_cap).
    if tenant.organisation_type == "PRODUCER" and tenant.sku_cap:
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM products WHERE tenant_id = :tid AND is_active = true"),
            {"tid": tid},
        )
        if (count_result.scalar() or 0) >= tenant.sku_cap:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "sku_cap_reached",
                    "upgrade_prompt": True,
                    "message": "SKU cap reached for this tenant's plan",
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
                "code": "duplicate_product_name",
                "message": "A product with this name already exists in this tenant",
            },
        )

    # 4. Atomic SKU generation — same lock already held on tenants row.
    sku_result = await db.execute(
        text(
            "UPDATE tenants "
            "SET sku_counter = COALESCE(sku_counter, 0) + 1 "
            "WHERE id = :tid "
            "RETURNING sku_prefix, sku_counter"
        ),
        {"tid": tid},
    )
    sku_row = sku_result.fetchone()
    sku = f"{sku_row.sku_prefix}-{sku_row.sku_counter:04d}"

    # 5. INSERT product — idempotency guaranteed by UNIQUE(tenant_id, sku).
    product_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            "INSERT INTO products "
            "  (id, tenant_id, sku, name, unit_of_measure, unit, pack_size, "
            "   is_active, created_by) "
            "VALUES "
            "  (:id, :tid, :sku, :name, :uom, :unit, :pack_size, true, :uid)"
        ),
        {
            "id":        product_id,
            "tid":       tid,
            "sku":       sku,
            "name":      body.name,
            "uom":       body.unit,   # unit_of_measure for backward compat
            "unit":      body.unit,
            "pack_size": body.pack_size,
            "uid":       uid,
        },
    )

    # 6. Audit log — append-only, same transaction (CLAUDE.md §7 + §14).
    await db.execute(
        text(
            "INSERT INTO audit_logs "
            "  (id, tenant_id, user_id, role, action, resource_type, "
            "   resource_id, decision, abac_context) "
            "VALUES "
            "  (:id, :tid, :uid, :role, 'product:create', 'product', "
            "   :rid, 'GRANTED', :ctx::jsonb)"
        ),
        {
            "id":   str(uuid.uuid4()),
            "tid":  tid,
            "uid":  uid,
            "role": getattr(user, "role", None),
            "rid":  product_id,
            "ctx":  json.dumps(
                {"sku": sku, "name": body.name, "unit": body.unit, "pack_size": body.pack_size}
            ),
        },
    )

    # 7. Outbox — same transaction, never post-commit (CLAUDE.md §8, §24 rule 6).
    await write_to_outbox(
        db,
        tid,
        "ProductCreated",
        ProductCreatedPayload(
            product_id=product_id,
            sku=sku,
            name=body.name,
            unit=body.unit,
            pack_size=body.pack_size,
            created_by=uid or "system",
        ),
    )

    return SuccessResponse(
        data=ProductResponse(
            id=uuid.UUID(product_id),
            sku=sku,
            name=body.name,
            unit=body.unit,
            pack_size=body.pack_size,
            tenant_id=uuid.UUID(tid),
            created_at=now,
            created_by=uuid.UUID(uid) if uid else None,
        )
    )
