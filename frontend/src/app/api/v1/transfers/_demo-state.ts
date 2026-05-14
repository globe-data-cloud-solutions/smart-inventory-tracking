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

// Seed records — survive hot-reloads because they live in globalThis
const SEED: TransferRecord[] = [
  // ── Addis Water ────────────────────────────────────────────────────────────
  { id: "d1", ref: "SHIP-2026-001", tenant_slug: "addis-water", transfer_type: "PUSH",   product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-main",    from_warehouse_name: "Main Production Center", to_warehouse_id: "aw-north",    to_warehouse_name: "North WH",           quantity: 1200, notes: "Monthly replenishment",         status: "COMPLETED",        idempotency_key: "demo-d1", created_at: "2026-05-01T08:00:00Z" },
  { id: "d2", ref: "SHIP-2026-002", tenant_slug: "addis-water", transfer_type: "PUSH",   product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-north",   from_warehouse_name: "North WH",               to_warehouse_id: "aw-north-sub",to_warehouse_name: "North-Subcenter WH", quantity: 480,  notes: "Sub-centre restock",            status: "IN_TRANSIT",       idempotency_key: "demo-d2", created_at: "2026-05-05T09:30:00Z" },
  { id: "d3", ref: "SHIP-2026-003", tenant_slug: "addis-water", transfer_type: "PULL",   product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-main",    from_warehouse_name: "Main Production Center", to_warehouse_id: "aw-south",    to_warehouse_name: "South WH",           quantity: 860,  notes: "South WH pull request",         status: "PENDING_APPROVAL", idempotency_key: "demo-d3", created_at: "2026-05-07T14:00:00Z" },
  { id: "d4", ref: "SHIP-2026-004", tenant_slug: "addis-water", transfer_type: "PULL",   product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-main",    from_warehouse_name: "Main Production Center", to_warehouse_id: "aw-east",     to_warehouse_name: "East WH",            quantity: 540,  notes: "East WH stock request",         status: "PENDING_REVIEW",   idempotency_key: "demo-d4", created_at: "2026-05-09T11:00:00Z" },
  { id: "d5", ref: "SHIP-2026-005", tenant_slug: "addis-water", transfer_type: "SISTER", product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-south",   from_warehouse_name: "South WH",               to_warehouse_id: "aw-west",     to_warehouse_name: "West WH",            quantity: 200,  notes: "Sister transfer rejected",      status: "REJECTED",         idempotency_key: "demo-d5", created_at: "2026-05-09T16:00:00Z" },

  // ── Muger Cement ───────────────────────────────────────────────────────────
  { id: "mc-t1", ref: "MC-2026-001", tenant_slug: "muger-cement", transfer_type: "PUSH",   product_id: "mc-p01", product_name: "OPC Grade 42.5N - 25kg Bag",  from_warehouse_id: "mc-harar",  from_warehouse_name: "Harar Production Center", to_warehouse_id: "mc-kombolcha", to_warehouse_name: "Kombolcha WH", quantity: 2400, notes: "Monthly push from Harar",      status: "COMPLETED",        idempotency_key: "demo-mc-t1", created_at: "2026-05-01T07:00:00Z" },
  { id: "mc-t2", ref: "MC-2026-002", tenant_slug: "muger-cement", transfer_type: "PUSH",   product_id: "mc-p01", product_name: "OPC Grade 42.5N - 25kg Bag",  from_warehouse_id: "mc-ambo",   from_warehouse_name: "Ambo Production Center",  to_warehouse_id: "mc-hawassa",   to_warehouse_name: "Hawassa WH",   quantity: 1800, notes: "Ambo push to Hawassa",         status: "IN_TRANSIT",       idempotency_key: "demo-mc-t2", created_at: "2026-05-06T09:00:00Z" },
  { id: "mc-t3", ref: "MC-2026-003", tenant_slug: "muger-cement", transfer_type: "PULL",   product_id: "mc-p02", product_name: "OPC Grade 42.5N - 50kg Bag",  from_warehouse_id: "mc-harar",  from_warehouse_name: "Harar Production Center", to_warehouse_id: "mc-mekele",    to_warehouse_name: "Mekele WH",    quantity: 960,  notes: "Mekele pull request",          status: "PENDING_APPROVAL", idempotency_key: "demo-mc-t3", created_at: "2026-05-08T11:00:00Z" },
  { id: "mc-t4", ref: "MC-2026-004", tenant_slug: "muger-cement", transfer_type: "PULL",   product_id: "mc-p01", product_name: "OPC Grade 42.5N - 25kg Bag",  from_warehouse_id: "mc-harar",  from_warehouse_name: "Harar Production Center", to_warehouse_id: "mc-kombolcha", to_warehouse_name: "Kombolcha WH", quantity: 1455, notes: "Kombolcha restock request",    status: "PENDING_REVIEW",   idempotency_key: "demo-mc-t4", created_at: "2026-05-10T10:00:00Z" },
  { id: "mc-t5", ref: "MC-2026-005", tenant_slug: "muger-cement", transfer_type: "SISTER", product_id: "mc-p03", product_name: "OPC Grade 32.5R - 25kg Bag",  from_warehouse_id: "mc-kombolcha",from_warehouse_name: "Kombolcha WH",           to_warehouse_id: "mc-diredawa",  to_warehouse_name: "Dire Dawa WH", quantity: 500,  notes: "Surplus rebalance",            status: "DRAFT",            idempotency_key: "demo-mc-t5", created_at: "2026-05-11T14:00:00Z" },
];

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
