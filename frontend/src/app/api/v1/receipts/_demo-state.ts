export type ReceiptStatus =
  | "DRAFT"
  | "PENDING_REVIEW"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "POSTED"
  | "REJECTED";

export interface OpeningBalanceReceipt {
  id: string;
  tenant_slug: string;
  ref: string;
  warehouse_id: string;
  warehouse_name: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  quantity: number;
  uom: string;
  batch_number: string | null;
  manufacture_date: string | null;
  expiry_date: string | null;
  reason_code: "OPENING_BALANCE";
  notes: string;
  reference_document: string | null;
  idempotency_key: string;
  created_by: string;
  status: ReceiptStatus;
  created_at: string;
  posted_at: string | null;
}

class RefCounter {
  private n = 0;
  next(): string {
    this.n += 1;
    return `OBR-${new Date().getFullYear()}-${String(this.n).padStart(3, "0")}`;
  }
}

declare global {
  // eslint-disable-next-line no-var
  var _smartDemoReceipts: OpeningBalanceReceipt[] | undefined;
  // eslint-disable-next-line no-var
  var _smartReceiptRefCounter: RefCounter | undefined;
}

if (!globalThis._smartDemoReceipts)      globalThis._smartDemoReceipts      = [];
if (!globalThis._smartReceiptRefCounter) globalThis._smartReceiptRefCounter = new RefCounter();

export const demoReceipts: OpeningBalanceReceipt[] = globalThis._smartDemoReceipts;
export const refCounter: RefCounter = globalThis._smartReceiptRefCounter;
