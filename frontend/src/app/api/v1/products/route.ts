import { NextRequest, NextResponse } from "next/server";
import { demoSkuCounter, demoProducts } from "./_demo-state";

const VALID_UNITS   = ["KG", "PACK", "QTL", "MT"] as const;
const VALID_PACKS   = [1, 4, 6, 12] as const;
const DEMO_TENANT   = "10000001-0000-0000-0000-000000000001";

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    name?: string; unit?: string; pack_size?: number;
  };

  // 422 validation
  if (!body.name || typeof body.name !== "string" || body.name.trim().length === 0) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "Name is required" } },
      { status: 422 }
    );
  }
  if (!VALID_UNITS.includes(body.unit as (typeof VALID_UNITS)[number])) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "Invalid unit" } },
      { status: 422 }
    );
  }
  if (!VALID_PACKS.includes(body.pack_size as (typeof VALID_PACKS)[number])) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "Invalid pack_size" } },
      { status: 422 }
    );
  }

  const name = body.name.trim();

  // 409 duplicate check (demo: case-insensitive name within demo state)
  const dup = demoProducts.find(
    (p) => p.name.toLowerCase() === name.toLowerCase()
  );
  if (dup) {
    return NextResponse.json(
      { success: false, error: { code: "duplicate_product_name", message: "Duplicate name" } },
      { status: 409 }
    );
  }

  const sku       = demoSkuCounter.increment();
  const id        = crypto.randomUUID();
  const now       = new Date().toISOString();
  const product   = { id, sku, name, unit: body.unit!, pack_size: body.pack_size!, tenant_id: DEMO_TENANT, created_at: now };
  demoProducts.push(product);

  return NextResponse.json(
    { success: true, data: product, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET() {
  return NextResponse.json(
    { success: true, data: demoProducts, request_id: crypto.randomUUID(), timestamp: new Date().toISOString() }
  );
}
