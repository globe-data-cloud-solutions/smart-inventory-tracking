export type TransferType = "PULL" | "PUSH" | "SISTER";

export type TransferStatus =
  | "DRAFT"
  | "PENDING_REVIEW"
  | "PENDING_APPROVAL"
  | "PENDING_SOURCE_CONFIRM"
  | "PENDING_DEST_CONFIRM"
  | "APPROVED"
  | "ADVISED"
  | "ISSUED"
  | "IN_TRANSIT"
  | "PARTIALLY_RECEIVED"
  | "RECEIVED"
  | "COMPLETED"
  | "REJECTED"
  | "CANCELLED";

export interface TransferRecord {
  id: string;
  ref: string;
  tenant_slug: string;
  transfer_type: TransferType;
  product_id: string;
  product_name: string;
  from_warehouse_id: string;
  from_warehouse_name: string;
  to_warehouse_id: string;
  to_warehouse_name: string;
  quantity: number;
  notes: string;
  status: TransferStatus;
  idempotency_key: string;
  created_at: string;
}

class RefCounter {
  private n = 0;
  next(): string {
    this.n += 1;
    return `TRF-${new Date().getFullYear()}-${String(this.n).padStart(3, "0")}`;
  }
}

export const refCounter = new RefCounter();

// Seed records — empty; real data comes from the backend API in gateway mode
const SEED: TransferRecord[] = [];

/**
 * Persist demoTransfers on globalThis so hot-reloads in development do NOT
 * reset user-created transfers. Without this, any transfer created during a
 * session is lost the moment Next.js recompiles a file.
 */
declare global {
  // eslint-disable-next-line no-var
  var _smartDemoTransfers: TransferRecord[] | undefined;
}

if (!globalThis._smartDemoTransfers) {
  globalThis._smartDemoTransfers = [...SEED];
}

export const demoTransfers: TransferRecord[] = globalThis._smartDemoTransfers;

/** Reset back to seed data — used by the Playwright E2E reset endpoint. */
export function resetDemoTransfers(): void {
  globalThis._smartDemoTransfers = [...SEED];
  // Splice-in-place so the exported const still points to the same array ref
  demoTransfers.splice(0, demoTransfers.length, ...globalThis._smartDemoTransfers);
}
