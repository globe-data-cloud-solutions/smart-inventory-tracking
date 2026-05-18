import { NextRequest, NextResponse } from "next/server";
import { demoReceipts, refCounter, type OpeningBalanceReceipt } from "../_demo-state";

export async function POST(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const callerRole = req.headers.get("X-User-Role") ?? "";

  const body = (await req.json()) as {
    warehouse_id?: string; warehouse_name?: string;
    product_id?: string;   product_name?: string; product_sku?: string;
    quantity?: number;     uom?: string;
    batch_number?: string; manufacture_date?: string; expiry_date?: string;
    notes?: string;        reference_document?: string;
    idempotency_key?: string;
    created_by?: string;
  };

  if (!body.warehouse_id || !body.product_id) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "warehouse_id and product_id are required" } },
      { status: 422 }
    );
  }
  const qty = Number(body.quantity ?? 0);
  if (!qty || qty <= 0) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "quantity must be greater than 0" } },
      { status: 422 }
    );
  }

  // Idempotency check
  if (body.idempotency_key) {
    const existing = demoReceipts.find((r) => r.idempotency_key === body.idempotency_key);
    if (existing) {
      return NextResponse.json(
        { success: false, error: { code: "DUPLICATE_TRANSACTION", message: "Duplicate idempotency key" }, data: existing },
        { status: 409 }
      );
    }
  }

  // Only WM, NM, TA, SA may create opening balance receipts
  const allowed = new Set(["WM", "NM", "TA", "SA"]);
  if (callerRole && !allowed.has(callerRole)) {
    return NextResponse.json(
      { success: false, error: { code: "ABAC_DENIED", message: "Insufficient role to create opening balance receipts" } },
      { status: 403 }
    );
  }

  const now = new Date().toISOString();
  const record: OpeningBalanceReceipt = {
    id:                 crypto.randomUUID(),
    tenant_slug:        tenantSlug,
    ref:                refCounter.next(),
    warehouse_id:       body.warehouse_id,
    warehouse_name:     body.warehouse_name ?? body.warehouse_id,
    product_id:         body.product_id,
    product_name:       body.product_name ?? body.product_id,
    product_sku:        body.product_sku ?? "",
    quantity:           qty,
    uom:                body.uom ?? "",
    batch_number:       body.batch_number ?? null,
    manufacture_date:   body.manufacture_date ?? null,
    expiry_date:        body.expiry_date ?? null,
    reason_code:        "OPENING_BALANCE",
    notes:              body.notes ?? "",
    reference_document: body.reference_document ?? null,
    idempotency_key:    body.idempotency_key ?? crypto.randomUUID(),
    created_by:         body.created_by ?? "",
    status:             "PENDING_APPROVAL",
    created_at:         now,
    posted_at:          null,
  };

  demoReceipts.unshift(record);

  return NextResponse.json(
    { success: true, data: record, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET(req: NextRequest) {
  const tenantSlug  = req.headers.get("X-Tenant-Slug") ?? "";
  const warehouseId = req.nextUrl.searchParams.get("warehouse_id");

  let results = demoReceipts.filter((r) => r.tenant_slug === tenantSlug);
  if (warehouseId) results = results.filter((r) => r.warehouse_id === warehouseId);

  return NextResponse.json({
    success:    true,
    data:       results,
    request_id: crypto.randomUUID(),
    timestamp:  new Date().toISOString(),
  });
}
