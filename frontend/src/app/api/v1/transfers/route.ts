import { NextRequest, NextResponse } from "next/server";
import { demoTransfers } from "./_demo-state";

// POST disabled — BUG_REPORT.md §5. Use API gateway: POST /api/v1/inventory/transfers/
export async function POST() {
  return NextResponse.json(
    { success: false, error: { code: "BFF_DISABLED", message: "Route disabled. Use the API gateway: POST /api/v1/inventory/transfers/" } },
    { status: 410 },
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
