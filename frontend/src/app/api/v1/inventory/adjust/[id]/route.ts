import { NextRequest, NextResponse } from "next/server";
import { demoAdjustments, type AdjustStatus } from "../_demo-state";

const TRANSITIONS: Record<AdjustStatus, AdjustStatus[]> = {
  DRAFT:     ["SUBMITTED", "CANCELLED"],
  SUBMITTED: ["APPROVED", "REJECTED"],
  APPROVED:  ["APPLIED"],
  APPLIED:   [],
  REJECTED:  [],
  CANCELLED: [],
};

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const body = (await req.json()) as { next_status?: string };
  const next = body.next_status as AdjustStatus | undefined;

  const adj = demoAdjustments.find((a) => a.id === id);
  if (!adj) {
    return NextResponse.json(
      { success: false, error: { code: "NOT_FOUND", message: "Adjustment not found" } },
      { status: 404 }
    );
  }

  if (!next || !TRANSITIONS[adj.status]?.includes(next)) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "INVALID_STATE_TRANSITION",
          message: `Cannot transition from ${adj.status} to ${next ?? "undefined"}`,
        },
      },
      { status: 422 }
    );
  }

  adj.status = next;
  if (next === "APPROVED") adj.status = "APPLIED"; // auto-apply on approval

  return NextResponse.json({
    success: true,
    data: adj,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
