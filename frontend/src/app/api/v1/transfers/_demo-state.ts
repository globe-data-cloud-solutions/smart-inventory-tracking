export type TransferStatus =
  | "DRAFT" | "SUBMITTED" | "APPROVED" | "IN_TRANSIT" | "RECEIVED" | "CLOSED" | "REJECTED" | "CANCELLED";

export interface TransferRecord {
  id: string;
  ref: string;
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

// Counter for generating REF numbers
class RefCounter {
  private n = 0;
  next(): string {
    this.n += 1;
    const year = new Date().getFullYear();
    return `TRF-${year}-${String(this.n).padStart(3, "0")}`;
  }
}

export const refCounter = new RefCounter();
export const demoTransfers: TransferRecord[] = [];
