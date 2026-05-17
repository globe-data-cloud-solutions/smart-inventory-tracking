import { NextResponse } from "next/server";
import { resetDemoTransfers } from "../_demo-state";

/**
 * DELETE /api/v1/transfers/_reset
 *
 * Development-only endpoint that resets globalThis._smartDemoTransfers back
 * to the seed data so Playwright E2E tests always start from a known state.
 *
 * Returns 403 in production. Never ship this without the NODE_ENV guard.
 */
export async function DELETE(): Promise<NextResponse> {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json(
      { success: false, error: { code: "FORBIDDEN", message: "Not available in production" } },
      { status: 403 },
    );
  }
  resetDemoTransfers();
  return NextResponse.json({
    success: true,
    data: { reset: true },
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
