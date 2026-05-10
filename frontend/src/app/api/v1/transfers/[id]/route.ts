import { NextRequest, NextResponse } from "next/server";
import { demoTransfers, type TransferStatus } from "../_demo-state";

// Valid state-machine transitions (mirrors state_machine.py)
const TRANSITIONS: Record<TransferStatus, TransferStatus[]> = {
  DRAFT:      ["SUBMITTED", "CANCELLED"],
  SUBMITTED:  ["APPROVED", "REJECTED", "CANCELLED"],
  APPROVED:   ["IN_TRANSIT", "CANCELLED"],
  IN_TRANSIT: ["RECEIVED", "CANCELLED"],
  RECEIVED:   ["CLOSED"],
  CLOSED:     [],
  REJECTED:   [],
  CANCELLED:  [],
};

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const body = (await req.json()) as { next_status?: string };
  const next = body.next_status as TransferStatus | undefined;

  const transfer = demoTransfers.find((t) => t.id === id);
  if (!transfer) {
    return NextResponse.json(
      { success: false, error: { code: "NOT_FOUND", message: "Transfer not found" } },
      { status: 404 }
    );
  }

  if (!next) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "next_status is required" } },
      { status: 422 }
    );
  }

  const allowed = TRANSITIONS[transfer.status] ?? [];
  if (!allowed.includes(next)) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "INVALID_STATE_TRANSITION",
          message: `Cannot transition from ${transfer.status} to ${next}`,
        },
      },
      { status: 422 }
    );
  }

  transfer.status = next;

  return NextResponse.json({
    success: true,
    data: transfer,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
