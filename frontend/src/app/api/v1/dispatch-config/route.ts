import { NextRequest, NextResponse } from "next/server";

type Strategy = "FEFO" | "FIFO" | "LIFO";
type Scope    = "PRODUCT" | "CATEGORY";

interface DispatchConfig {
  id: string;
  tenant_slug: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  scope: Scope;
  strategy: Strategy;
  effective_from: string;
  configured_by: string;
  created_at: string;
}

const dispatchConfigs: DispatchConfig[] = [];

export async function GET(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const data = tenantSlug
    ? dispatchConfigs.filter((c) => c.tenant_slug === tenantSlug)
    : [];
  return NextResponse.json({
    success: true,
    data,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}

export async function POST(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const body = (await req.json()) as {
    product_id?: string; product_name?: string; product_sku?: string;
    scope?: Scope; strategy?: Strategy;
  };

  if (!body.product_id || !body.strategy) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "product_id and strategy are required" } },
      { status: 422 }
    );
  }
  if (!["FEFO", "FIFO", "LIFO"].includes(body.strategy)) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "strategy must be FEFO, FIFO, or LIFO" } },
      { status: 422 }
    );
  }

  const now = new Date().toISOString();
  const record: DispatchConfig = {
    id:            crypto.randomUUID(),
    tenant_slug:   tenantSlug,
    product_id:    body.product_id,
    product_name:  body.product_name ?? body.product_id,
    product_sku:   body.product_sku  ?? "",
    scope:         body.scope ?? "PRODUCT",
    strategy:      body.strategy,
    effective_from: now.slice(0, 10),
    configured_by: "demo-user",
    created_at:    now,
  };

  // Upsert — replace existing config for same tenant + product
  const existing = dispatchConfigs.findIndex(
    (c) => c.tenant_slug === tenantSlug && c.product_id === body.product_id && c.scope === record.scope
  );
  if (existing >= 0) dispatchConfigs[existing] = record;
  else dispatchConfigs.push(record);

  return NextResponse.json(
    { success: true, data: record, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}
