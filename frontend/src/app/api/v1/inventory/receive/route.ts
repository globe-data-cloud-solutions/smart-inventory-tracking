import { NextResponse } from "next/server";

// POST disabled — BUG_REPORT.md §5.
// Use the API gateway: POST /api/v1/inventory/receive/
// The gateway enforces JWT → RBAC (inventory:receive) → PostgreSQL RLS.
export async function POST() {
  return NextResponse.json(
    { success: false, error: { code: "BFF_DISABLED", message: "Route disabled. Use the API gateway: POST /api/v1/inventory/receive/" } },
    { status: 410 },
  );
}

export async function GET() {
  return NextResponse.json({ success: true, data: [], request_id: crypto.randomUUID(), timestamp: new Date().toISOString() });
}
