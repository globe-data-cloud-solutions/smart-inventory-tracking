export type ImportStatus =
  | "SUBMITTED"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "POSTED"
  | "FAILED"
  | "PARTIAL";

export interface ImportRow {
  row_number:        number;
  warehouse_code:    string;
  warehouse_id:      string | null;
  sku_code:          string;
  product_id:        string | null;
  opening_quantity:  number;
  uom:               string;
  batch_number:      string | null;
  manufacture_date:  string | null;
  expiry_date:       string | null;
  notes:             string | null;
  reference_document: string | null;
  idempotency_key:   string;
  status:            "VALID" | "ERROR" | "WARNING" | "POSTED";
  errors:            string[];
  warnings:          string[];
}

export interface ImportBatch {
  id:           string;
  reference:    string;
  tenant_slug:  string;
  submitted_by: string;
  status:       ImportStatus;
  total_rows:   number;
  valid_rows:   number;
  error_rows:   number;
  warning_rows: number;
  posted_rows:  number;
  rows:         ImportRow[];
  created_at:   string;
  posted_at:    string | null;
}

class RefCounter {
  private n = 0;
  next(): string {
    this.n += 1;
    return `IMP-${new Date().getFullYear()}-${String(this.n).padStart(3, "0")}`;
  }
}

declare global {
  // eslint-disable-next-line no-var
  var _smartDemoImports: ImportBatch[] | undefined;
  // eslint-disable-next-line no-var
  var _smartImportRefCounter: RefCounter | undefined;
}

if (!globalThis._smartDemoImports)      globalThis._smartDemoImports      = [];
if (!globalThis._smartImportRefCounter) globalThis._smartImportRefCounter = new RefCounter();

export const demoImports: ImportBatch[] = globalThis._smartDemoImports;
export const refCounter: RefCounter = globalThis._smartImportRefCounter;
