import { NextRequest, NextResponse } from "next/server";
import { demoTransfers, refCounter, type TransferRecord } from "./_demo-state";

export async function POST(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const body = (await req.json()) as {
    product_id?: string; product_name?: string;
    from_warehouse_id?: string; from_warehouse_name?: string;
    to_warehouse_id?: string; to_warehouse_name?: string;
    quantity?: number | string; notes?: string; idempotency_key?: string;
  };

  if (!body.product_id || !body.from_warehouse_id || !body.to_warehouse_id) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "product_id, from_warehouse_id, and to_warehouse_id are required" } },
      { status: 422 }
    );
  }
  if (body.from_warehouse_id === body.to_warehouse_id) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "From and to warehouse must be different" } },
      { status: 422 }
    );
  }
  const qty = parseFloat(String(body.quantity ?? "0"));
  if (!qty || qty <= 0) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "quantity must be positive" } },
      { status: 422 }
    );
  }

  const now = new Date().toISOString();
  const record: TransferRecord = {
    id: crypto.randomUUID(),
    ref: refCounter.next(),
    tenant_slug: tenantSlug,
    product_id: body.product_id,
    product_name: body.product_name ?? body.product_id,
    from_warehouse_id: body.from_warehouse_id,
    from_warehouse_name: body.from_warehouse_name ?? body.from_warehouse_id,
    to_warehouse_id: body.to_warehouse_id,
    to_warehouse_name: body.to_warehouse_name ?? body.to_warehouse_id,
    quantity: qty,
    notes: body.notes ?? "",
    status: "DRAFT",
    idempotency_key: body.idempotency_key ?? crypto.randomUUID(),
    created_at: now,
  };

  demoTransfers.unshift(record);

  return NextResponse.json(
    { success: true, data: record, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const data = tenantSlug
    ? demoTransfers.filter((t) => t.tenant_slug === tenantSlug)
    : [];
  return NextResponse.json({
    success: true,
    data,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
