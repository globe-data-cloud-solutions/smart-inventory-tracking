import { NextResponse } from "next/server";

// PATCH disabled — BUG_REPORT.md §5.
// Use the API gateway: PATCH /api/v1/inventory/adjust/{id}/
// The gateway enforces JWT → RBAC (adjustment:approve) → PostgreSQL RLS.
export async function PATCH() {
  return NextResponse.json(
    { success: false, error: { code: "BFF_DISABLED", message: "Route disabled. Use the API gateway: PATCH /api/v1/inventory/adjust/{id}/" } },
    { status: 410 },
  );
}
