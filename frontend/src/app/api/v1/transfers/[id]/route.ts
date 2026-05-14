import { NextRequest, NextResponse } from "next/server";
import { demoTransfers, type TransferStatus } from "../_demo-state";

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const transfer = demoTransfers.find((t) => t.id === id);
  if (!transfer) {
    return NextResponse.json(
      { success: false, error: { code: "NOT_FOUND", message: "Transfer not found" } },
      { status: 404 }
    );
  }
  return NextResponse.json({
    success: true,
    data: transfer,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}

const PULL_TRANSITIONS: Record<string, TransferStatus[]> = {
  DRAFT:              ["PENDING_REVIEW", "CANCELLED"],
  PENDING_REVIEW:     ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
  PENDING_APPROVAL:   ["APPROVED", "REJECTED", "CANCELLED"],
  APPROVED:           ["ISSUED", "CANCELLED"],
  ISSUED:             ["IN_TRANSIT"],
  IN_TRANSIT:         ["PARTIALLY_RECEIVED", "RECEIVED"],
  PARTIALLY_RECEIVED: ["RECEIVED"],
  RECEIVED:           ["COMPLETED"],
  COMPLETED: [], REJECTED: [], CANCELLED: [],
};

const PUSH_TRANSITIONS: Record<string, TransferStatus[]> = {
  DRAFT:              ["PENDING_APPROVAL", "CANCELLED"],
  PENDING_APPROVAL:   ["APPROVED", "REJECTED", "CANCELLED"],
  APPROVED:           ["ADVISED", "ISSUED", "CANCELLED"],
  ADVISED:            ["ISSUED", "CANCELLED"],
  ISSUED:             ["IN_TRANSIT"],
  IN_TRANSIT:         ["PARTIALLY_RECEIVED", "RECEIVED"],
  PARTIALLY_RECEIVED: ["RECEIVED"],
  RECEIVED:           ["COMPLETED"],
  COMPLETED: [], REJECTED: [], CANCELLED: [],
};

const SISTER_TRANSITIONS: Record<string, TransferStatus[]> = {
  DRAFT:                  ["PENDING_SOURCE_CONFIRM", "CANCELLED"],
  PENDING_SOURCE_CONFIRM: ["PENDING_DEST_CONFIRM", "CANCELLED"],
  PENDING_DEST_CONFIRM:   ["PENDING_APPROVAL", "REJECTED", "CANCELLED"],
  PENDING_APPROVAL:       ["APPROVED", "REJECTED", "CANCELLED"],
  APPROVED:               ["ISSUED", "CANCELLED"],
  ISSUED:                 ["IN_TRANSIT"],
  IN_TRANSIT:             ["PARTIALLY_RECEIVED", "RECEIVED"],
  PARTIALLY_RECEIVED:     ["RECEIVED"],
  RECEIVED:               ["COMPLETED"],
  COMPLETED: [], REJECTED: [], CANCELLED: [],
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

  const machine =
    transfer.transfer_type === "PULL"   ? PULL_TRANSITIONS :
    transfer.transfer_type === "SISTER" ? SISTER_TRANSITIONS :
    PUSH_TRANSITIONS;

  const allowed = machine[transfer.status] ?? [];
  if (!allowed.includes(next)) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "INVALID_STATE_TRANSITION",
          message: `Cannot transition ${transfer.transfer_type} from ${transfer.status} to ${next}`,
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
