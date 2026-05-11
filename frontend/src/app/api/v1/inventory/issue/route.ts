import { NextRequest, NextResponse } from "next/server";

interface IssueRecord {
  id: string;
  product_id: string;
  warehouse_id: string;
  quantity: number;
  reason_code: string;
  issued_to: string;
  notes: string;
  idempotency_key: string;
  created_at: string;
}

const issues: IssueRecord[] = [];
const processedKeys = new Set<string>();

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    product_id?: string;
    warehouse_id?: string;
    quantity?: string | number;
    reason_code?: string;
    issued_to?: string;
    notes?: string;
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

  if (!body.reason_code) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "reason_code is required" } },
      { status: 422 }
    );
  }

  const key = body.idempotency_key ?? `${body.product_id}:issue:${Date.now()}`;
  if (processedKeys.has(key)) {
    return NextResponse.json(
      { success: false, error: { code: "DUPLICATE_TRANSACTION", message: "Already processed" } },
      { status: 409 }
    );
  }

  processedKeys.add(key);
  const now = new Date().toISOString();
  const record: IssueRecord = {
    id: crypto.randomUUID(),
    product_id: body.product_id,
    warehouse_id: body.warehouse_id,
    quantity: qty,
    reason_code: body.reason_code,
    issued_to: body.issued_to ?? "",
    notes: body.notes ?? "",
    idempotency_key: key,
    created_at: now,
  };
  issues.push(record);

  return NextResponse.json(
    { success: true, data: record, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET() {
  return NextResponse.json({
    success: true,
    data: issues,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
