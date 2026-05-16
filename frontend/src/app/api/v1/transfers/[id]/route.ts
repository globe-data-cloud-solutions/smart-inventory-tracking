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

// Statuses that mean "stock is arriving at the destination" — only the destination
// warehouse manager may advance the transfer into or past these states.
const DESTINATION_ONLY = new Set<TransferStatus>([
  "PARTIALLY_RECEIVED",
  "RECEIVED",
  "COMPLETED",
]);

// Statuses that require the caller to be the source warehouse (dispatching stock).
// NM and LM may also dispatch without being assigned to the specific warehouse.
const SOURCE_ONLY = new Set<TransferStatus>(["IN_TRANSIT"]);

// Roles that bypass warehouse-scope checks (platform / tenant super-admins only).
const UNRESTRICTED_ROLES = new Set(["SA", "TA"]);

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const body = (await req.json()) as { next_status?: string };
  const next = body.next_status as TransferStatus | undefined;

  // Caller identity — injected by api.ts from the demo session stored in localStorage.
  const callerRole = req.headers.get("X-User-Role") ?? "";
  const callerWH   = req.headers.get("X-User-Warehouse-Id") ?? "";

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

  // ── Warehouse-scope ABAC ───────────────────────────────────────────────────
  // TA / SA can perform any transition (emergency override).
  if (!UNRESTRICTED_ROLES.has(callerRole)) {
    if (DESTINATION_ONLY.has(next)) {
      // Receiving and completing — destination warehouse only.
      // A missing or non-matching warehouse ID is always denied: middle-layer
      // managers (NM, RM, LM) have no warehouse assignment and must be rejected.
      if (!callerWH || callerWH !== transfer.to_warehouse_id) {
        return NextResponse.json(
          {
            success: false,
            error: {
              code: "ABAC_DENIED",
              message: "Only the destination warehouse can receive or complete this transfer",
            },
          },
          { status: 403 }
        );
      }
    }

    if (SOURCE_ONLY.has(next)) {
      // Dispatching — source warehouse or a manager-level role without a specific
      // warehouse assignment (NM, LM who coordinate logistics across facilities).
      const managerRoles = new Set(["NM", "LM", "RM"]);
      if (!managerRoles.has(callerRole) && (!callerWH || callerWH !== transfer.from_warehouse_id)) {
        return NextResponse.json(
          {
            success: false,
            error: {
              code: "ABAC_DENIED",
              message: "Only the source warehouse or a logistics manager can dispatch this transfer",
            },
          },
          { status: 403 }
        );
      }
    }
  }

  transfer.status = next;

  return NextResponse.json({
    success: true,
    data: transfer,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
