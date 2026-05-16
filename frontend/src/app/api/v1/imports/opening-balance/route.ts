import { NextRequest, NextResponse } from "next/server";
import { demoImports, refCounter, type ImportRow, type ImportBatch } from "../_demo-state";

export async function POST(req: NextRequest) {
  const tenantSlug  = req.headers.get("X-Tenant-Slug") ?? "";
  const submittedBy = req.headers.get("X-User-Role")   ?? "";

  const body = (await req.json()) as { rows?: ImportRow[] };

  if (!body.rows || body.rows.length === 0) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "rows array is required and must not be empty" } },
      { status: 422 }
    );
  }

  const rows = body.rows;
  const validRows   = rows.filter((r) => r.status === "VALID" || r.status === "WARNING");
  const errorRows   = rows.filter((r) => r.status === "ERROR");
  const warningRows = rows.filter((r) => r.status === "WARNING");

  if (errorRows.length > 0) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: `${errorRows.length} row(s) have errors and must be corrected before submission` } },
      { status: 422 }
    );
  }

  const now = new Date().toISOString();
  const batch: ImportBatch = {
    id:           crypto.randomUUID(),
    reference:    refCounter.next(),
    tenant_slug:  tenantSlug,
    submitted_by: submittedBy,
    status:       "PENDING_APPROVAL",
    total_rows:   rows.length,
    valid_rows:   validRows.length,
    error_rows:   errorRows.length,
    warning_rows: warningRows.length,
    posted_rows:  0,
    rows:         rows.map((r) => ({ ...r, status: r.status === "ERROR" ? "ERROR" : "VALID" as const })),
    created_at:   now,
    posted_at:    null,
  };

  demoImports.unshift(batch);

  return NextResponse.json(
    { success: true, data: batch, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const data = demoImports.filter((b) => b.tenant_slug === tenantSlug);
  return NextResponse.json({
    success:    true,
    data,
    request_id: crypto.randomUUID(),
    timestamp:  new Date().toISOString(),
  });
}
