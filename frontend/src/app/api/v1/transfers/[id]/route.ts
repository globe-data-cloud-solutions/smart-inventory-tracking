import { NextRequest, NextResponse } from "next/server";
import { demoTransfers } from "../_demo-state";

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const transfer = demoTransfers.find((t) => t.id === id);
  if (!transfer) {
    return NextResponse.json(
      { success: false, error: { code: "NOT_FOUND", message: "Transfer not found" } },
      { status: 404 }
    );
  }
  return NextResponse.json({
    success: true,
    data: transfer,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}

// PATCH disabled — BUG_REPORT.md §5 fix.
// The previous BFF implementation only enforced warehouse-scope ABAC, allowing
// a WM to call APPROVED without NM sign-off. All transfer state transitions must
// go through the API gateway (NEXT_PUBLIC_API_URL) which enforces:
//   Layer 1: JWT validation (api-gateway)
//   Layer 2: RBAC via role_permissions DB + ABAC (inventory-service @require_permission)
//   Layer 3: PostgreSQL RLS tenant isolation
export async function PATCH() {
  return NextResponse.json(
    {
      success: false,
      error: {
        code: "BFF_DISABLED",
        message: "Route disabled. Use the API gateway: POST /api/v1/inventory/transfers/{id}/approve|submit|receive|dispatch",
      },
    },
    { status: 410 },
  );
}
