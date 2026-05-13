export type TransferStatus =
  | "DRAFT" | "SUBMITTED" | "APPROVED" | "IN_TRANSIT" | "RECEIVED" | "CLOSED" | "REJECTED" | "CANCELLED";

export interface TransferRecord {
  id: string;
  ref: string;
  tenant_slug: string;
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

// Pre-seeded demo transfers — scoped to "addis-water" so other tenants never see them
export const demoTransfers: TransferRecord[] = [
  { id: "d1", ref: "SHIP-2026-001", tenant_slug: "addis-water", product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-main",  from_warehouse_name: "Main Production Center", to_warehouse_id: "aw-north",  to_warehouse_name: "North WH",           quantity: 1200, notes: "Monthly replenishment",        status: "CLOSED",     idempotency_key: "demo-d1", created_at: "2026-05-01T08:00:00Z" },
  { id: "d2", ref: "SHIP-2026-002", tenant_slug: "addis-water", product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-north", from_warehouse_name: "North WH",               to_warehouse_id: "aw-north2", to_warehouse_name: "North-Subcenter WH", quantity: 480,  notes: "Sub-centre restock",           status: "IN_TRANSIT", idempotency_key: "demo-d2", created_at: "2026-05-05T09:30:00Z" },
  { id: "d3", ref: "SHIP-2026-003", tenant_slug: "addis-water", product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-main",  from_warehouse_name: "Main Production Center", to_warehouse_id: "aw-south",  to_warehouse_name: "South WH",           quantity: 860,  notes: "Approved — awaiting dispatch", status: "SUBMITTED",  idempotency_key: "demo-d3", created_at: "2026-05-07T14:00:00Z" },
  { id: "d4", ref: "SHIP-2026-004", tenant_slug: "addis-water", product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-main",  from_warehouse_name: "Main Production Center", to_warehouse_id: "aw-east",   to_warehouse_name: "East WH",            quantity: 540,  notes: "",                             status: "DRAFT",      idempotency_key: "demo-d4", created_at: "2026-05-09T11:00:00Z" },
  { id: "d5", ref: "SHIP-2026-005", tenant_slug: "addis-water", product_id: "", product_name: "Multiple SKUs", from_warehouse_id: "aw-south", from_warehouse_name: "South WH",               to_warehouse_id: "aw-west",   to_warehouse_name: "West WH",            quantity: 200,  notes: "Rejected — insufficient stock",status: "REJECTED",   idempotency_key: "demo-d5", created_at: "2026-05-09T16:00:00Z" },
];
