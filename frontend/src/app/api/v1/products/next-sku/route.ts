import { NextResponse } from "next/server";
import { demoSkuCounter } from "../_demo-state";

export async function GET() {
  return NextResponse.json({
    success: true,
    data: { counter: demoSkuCounter.peekNumber() },
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
