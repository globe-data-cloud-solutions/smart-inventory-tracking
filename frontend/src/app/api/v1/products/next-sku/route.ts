import { NextResponse } from "next/server";
import { demoSkuCounter } from "../_demo-state";

export async function GET() {
  const next = demoSkuCounter.peek();
  return NextResponse.json({
    success: true,
    data: { sku: next },
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
