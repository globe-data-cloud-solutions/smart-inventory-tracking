import { NextRequest, NextResponse } from "next/server";
import { demoAdjustments, getRequiredRole, type AdjustRecord } from "./_demo-state";

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    product_id?: string; product_name?: string; product_sku?: string;
    warehouse_id?: string; warehouse_name?: string;
    quantity?: number | string; reason_code?: string; notes?: string;
    idempotency_key?: string;
  };

  if (!body.product_id || !body.warehouse_id) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "product_id and warehouse_id are required" } },
      { status: 422 }
    );
  }

  const qty = parseFloat(String(body.quantity ?? "0"));
  if (qty === 0 || isNaN(qty)) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "quantity must be non-zero" } },
      { status: 422 }
    );
  }

  if (!body.reason_code) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "reason_code is required" } },
      { status: 422 }
    );
  }

  const absQty     = Math.abs(qty);
  const reqRole    = getRequiredRole(absQty);
  const autoApply  = reqRole === "NONE";
  const now        = new Date().toISOString();

  const record: AdjustRecord = {
    id:                   crypto.randomUUID(),
    product_id:           body.product_id,
    product_name:         body.product_name ?? body.product_id,
    product_sku:          body.product_sku  ?? "",
    warehouse_id:         body.warehouse_id,
    warehouse_name:       body.warehouse_name ?? body.warehouse_id,
    quantity:             qty,
    reason_code:          body.reason_code,
    notes:                body.notes ?? "",
    status:               autoApply ? "APPLIED" : "SUBMITTED",
    approval_required_role: reqRole,
    idempotency_key:      body.idempotency_key ?? crypto.randomUUID(),
    created_at:           now,
  };

  demoAdjustments.unshift(record);

  return NextResponse.json(
    { success: true, data: record, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET() {
  return NextResponse.json({
    success: true,
    data: demoAdjustments,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
