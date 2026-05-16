import { NextRequest, NextResponse } from "next/server";
import { demoImports } from "../../_demo-state";

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ reference: string }> }
) {
  const { reference } = await context.params;
  const batch = demoImports.find((b) => b.reference === reference);
  if (!batch) {
    return NextResponse.json(
      { success: false, error: { code: "NOT_FOUND", message: `Import ${reference} not found` } },
      { status: 404 }
    );
  }
  return NextResponse.json({
    success:    true,
    data:       batch,
    request_id: crypto.randomUUID(),
    timestamp:  new Date().toISOString(),
  });
}
