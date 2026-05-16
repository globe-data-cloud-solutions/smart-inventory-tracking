import { NextRequest, NextResponse } from "next/server";
import { demoSkuCounter, demoProducts, buildSku } from "./_demo-state";

const VALID_UNITS = ["KG", "PACK", "QTL", "MT"] as const;
const VALID_PACKS = [1, 4, 6, 12] as const;

export async function POST(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "unknown";
  const body = (await req.json()) as {
    name?: string; type_code?: string; unit?: string;
    pack_size?: number; org_slug?: string;
    category?: string; on_hand?: number; reorder_point?: number;
    warehouse_id?: string;
  };

  const name     = typeof body.name === "string" ? body.name.trim() : "";
  const typeCode = typeof body.type_code === "string" ? body.type_code.trim().toUpperCase() : "";
  const orgSlug  = typeof body.org_slug === "string" ? body.org_slug : tenantSlug;

  if (!name) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "Name is required" } },
      { status: 422 }
    );
  }
  if (typeCode.length < 2 || typeCode.length > 5 || !/^[A-Z]+$/.test(typeCode)) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "type_code must be 2–5 letters" } },
      { status: 422 }
    );
  }
  if (!VALID_UNITS.includes(body.unit as (typeof VALID_UNITS)[number])) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "Invalid unit" } },
      { status: 422 }
    );
  }
  const packSize = Number(body.pack_size);
  if (!VALID_PACKS.includes(packSize as (typeof VALID_PACKS)[number])) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "Invalid pack_size" } },
      { status: 422 }
    );
  }

  // 409 duplicate within the same tenant only
  if (demoProducts.some((p) => p.tenant_slug === tenantSlug && p.name.toLowerCase() === name.toLowerCase())) {
    return NextResponse.json(
      { success: false, error: { code: "duplicate_product_name", message: "Duplicate product name" } },
      { status: 409 }
    );
  }

  const n   = demoSkuCounter.increment();
  const sku = buildSku(orgSlug, typeCode, body.unit!, packSize, n);
  const id  = crypto.randomUUID();
  const now = new Date().toISOString();

  const product = {
    id, sku, name, type_code: typeCode, unit: body.unit!, pack_size: packSize,
    tenant_slug: tenantSlug, created_at: now,
    category:      body.category     ?? typeCode,
    on_hand:       body.on_hand      ?? 0,
    reorder_point: body.reorder_point ?? 0,
    warehouse_id:  body.warehouse_id ?? undefined,
  };
  demoProducts.push(product);

  return NextResponse.json(
    { success: true, data: product, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET(req: NextRequest) {
  const tenantSlug = req.headers.get("X-Tenant-Slug") ?? "";
  const data = tenantSlug
    ? demoProducts.filter((p) => p.tenant_slug === tenantSlug)
    : [];
  return NextResponse.json({
    success: true,
    data,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
