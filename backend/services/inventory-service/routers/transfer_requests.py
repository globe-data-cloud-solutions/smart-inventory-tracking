"""Transfer request router — warehouse-to-warehouse stock pull requests.

Based on reference transfer_requests.py but with two key differences:
  1. Async session (AsyncSession, await) instead of sync Session
  2. Notification written to the outbox in the SAME transaction as the
     transfer_request row (Outbox pattern) — never post-commit direct emit.
"""
from __future__ import annotations

import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.dependencies import get_db_session
from shared.outbox.schemas import TransferRequestedPayload
from shared.outbox.writer import write_to_outbox
from shared.permissions.middleware import require_permission
from shared.permissions.registry import PERMISSIONS
from shared.utils.responses import SuccessResponse
from shared.utils.tenant_scope import effective_tenant_id
from schemas.analytics import TransferRequestCreate, TransferRequestOut

router = APIRouter()


async def _enrich(row: Any, session: AsyncSession) -> TransferRequestOut:
    """Join warehouse and product names onto a transfer_request row."""
    rw = (await session.execute(
        text("SELECT name FROM warehouses WHERE id = :id"), {"id": str(row.requesting_warehouse_id)}
    )).fetchone()
    sw = (await session.execute(
        text("SELECT name FROM warehouses WHERE id = :id"), {"id": str(row.source_warehouse_id)}
    )).fetchone()
    pr = (await session.execute(
        text("SELECT name, sku FROM products WHERE id = :id"), {"id": str(row.product_id)}
    )).fetchone()

    return TransferRequestOut(
        id=row.id,
        tenant_id=row.tenant_id,
        requesting_warehouse_id=row.requesting_warehouse_id,
        requesting_warehouse_name=rw.name if rw else "Unknown",
        source_warehouse_id=row.source_warehouse_id,
        source_warehouse_name=sw.name if sw else "Unknown",
        product_id=row.product_id,
        product_name=pr.name if pr else "Unknown",
        product_sku=pr.sku if pr else "N/A",
        quantity=row.quantity,
        required_date=getattr(row, "required_date", None),
        notes=getattr(row, "notes", None),
        status=row.status,
        created_at=row.created_at,
    )


@router.post("/", status_code=201, response_model=SuccessResponse[TransferRequestOut])
@require_permission(PERMISSIONS.TRANSFER_CREATE)
async def create_transfer_request(
    body: TransferRequestCreate,
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferRequestOut]:
    """Submit a pull request for stock. The source warehouse is notified via the outbox."""
    if body.requesting_warehouse_id == body.source_warehouse_id:
        raise HTTPException(status_code=400, detail="Requesting and source warehouse must differ")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    req_id = str(uuid.uuid4())

    # Resolve names for the outbox payload (before the INSERT, same session)
    rw_row = (await db.execute(
        text("SELECT name FROM warehouses WHERE id = :id"),
        {"id": str(body.requesting_warehouse_id)},
    )).fetchone()
    pr_row = (await db.execute(
        text("SELECT name FROM products WHERE id = :id"),
        {"id": str(body.product_id)},
    )).fetchone()

    await db.execute(
        text("""
            INSERT INTO transfer_requests
              (id, tenant_id, requesting_warehouse_id, source_warehouse_id,
               product_id, quantity, required_date, notes, status, created_by)
            VALUES
              (:id, :tid, :req_wh, :src_wh,
               :pid, :qty, :req_date, :notes, 'PENDING', :uid)
        """),
        {
            "id":       req_id,
            "tid":      str(user.tenant_id),
            "req_wh":   str(body.requesting_warehouse_id),
            "src_wh":   str(body.source_warehouse_id),
            "pid":      str(body.product_id),
            "qty":      str(body.quantity),
            "req_date": body.required_date,
            "notes":    body.notes,
            "uid":      str(user.user_id),
        },
    )

    # Notify source warehouse via Outbox — same transaction, atomic
    await write_to_outbox(
        db,
        str(user.tenant_id),
        "TransferRequested",
        TransferRequestedPayload(
            transfer_request_id=req_id,
            requesting_warehouse_id=str(body.requesting_warehouse_id),
            requesting_warehouse_name=rw_row.name if rw_row else "Unknown",
            source_warehouse_id=str(body.source_warehouse_id),
            product_id=str(body.product_id),
            product_name=pr_row.name if pr_row else "Unknown",
            quantity=float(body.quantity),
            required_date=body.required_date.isoformat() if body.required_date else None,
        ),
    )

    row = (await db.execute(
        text("SELECT * FROM transfer_requests WHERE id = :id"), {"id": req_id}
    )).fetchone()

    return SuccessResponse(data=await _enrich(row, db))


@router.get("/", response_model=SuccessResponse[List[TransferRequestOut]])
@require_permission(PERMISSIONS.TRANSFER_LIST)
async def list_transfer_requests(
    source_warehouse_id: Optional[uuid.UUID]  = Query(None),
    product_id:          Optional[uuid.UUID]  = Query(None),
    status:              Optional[str]         = Query(None),
    tenant_id:           Optional[uuid.UUID]  = Query(None),
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[List[TransferRequestOut]]:
    tid = effective_tenant_id(user, tenant_id)

    clauses = []
    params: dict = {}
    if tid:
        clauses.append("tenant_id = :tid")
        params["tid"] = str(tid)
    if source_warehouse_id:
        clauses.append("source_warehouse_id = :swid")
        params["swid"] = str(source_warehouse_id)
    if product_id:
        clauses.append("product_id = :pid")
        params["pid"] = str(product_id)
    if status:
        clauses.append("status = :status")
        params["status"] = status

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = text(f"SELECT * FROM transfer_requests {where} ORDER BY created_at DESC LIMIT 200")
    rows = (await db.execute(sql, params)).fetchall()

    return SuccessResponse(data=[await _enrich(r, db) for r in rows])


@router.patch("/{request_id}/status", response_model=SuccessResponse[TransferRequestOut])
@require_permission(PERMISSIONS.TRANSFER_APPROVE)
async def update_request_status(
    request_id: uuid.UUID,
    new_status: str = Query(..., pattern="^(APPROVED|REJECTED|FULFILLED|CANCELLED)$"),
    user=Depends(lambda: None),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse[TransferRequestOut]:
    row = (await db.execute(
        text(
            "SELECT * FROM transfer_requests "
            "WHERE id = :id AND tenant_id = :tid FOR UPDATE"
        ),
        {"id": str(request_id), "tid": str(user.tenant_id)},
    )).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Transfer request not found")

    await db.execute(
        text(
            "UPDATE transfer_requests SET status = :status, updated_at = now() WHERE id = :id"
        ),
        {"status": new_status, "id": str(request_id)},
    )

    updated = (await db.execute(
        text("SELECT * FROM transfer_requests WHERE id = :id"), {"id": str(request_id)}
    )).fetchone()

    return SuccessResponse(data=await _enrich(updated, db))
