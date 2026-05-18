import { NextRequest, NextResponse } from "next/server";

interface ReceiptRecord {
  id: string;
  product_id: string;
  warehouse_id: string;
  quantity: number;
  lot_number?: string;
  expiry_date?: string;
  idempotency_key: string;
  created_at: string;
}

// In-memory store — reset on server restart (Phase 0 demo only)
const receipts: ReceiptRecord[] = [];
const processedKeys = new Set<string>();

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    product_id?: string;
    warehouse_id?: string;
    quantity?: string | number;
    lot_number?: string;
    expiry_date?: string;
    idempotency_key?: string;
  };

  if (!body.product_id || !body.warehouse_id) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "product_id and warehouse_id are required" } },
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

  const key = body.idempotency_key ?? `${body.product_id}:${body.warehouse_id}:${qty}`;
  if (processedKeys.has(key)) {
    return NextResponse.json(
      { success: false, error: { code: "DUPLICATE_TRANSACTION", message: "Idempotency key already processed" } },
      { status: 409 }
    );
  }

  processedKeys.add(key);
  const record: ReceiptRecord = {
    id: crypto.randomUUID(),
    product_id: body.product_id,
    warehouse_id: body.warehouse_id,
    quantity: qty,
    lot_number: body.lot_number,
    expiry_date: body.expiry_date,
    idempotency_key: key,
    created_at: new Date().toISOString(),
  };
  receipts.push(record);

  return NextResponse.json(
    { success: true, data: record, request_id: crypto.randomUUID(), timestamp: record.created_at },
    { status: 201 }
  );
}

export async function GET() {
  return NextResponse.json({
    success: true,
    data: receipts,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
