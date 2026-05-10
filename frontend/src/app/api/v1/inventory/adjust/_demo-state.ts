export type AdjustStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "APPLIED" | "REJECTED" | "CANCELLED";

export interface AdjustRecord {
  id: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  quantity: number;       // positive = add, negative = remove
  reason_code: string;
  notes: string;
  status: AdjustStatus;
  approval_required_role: "NONE" | "RM" | "NM";
  idempotency_key: string;
  created_at: string;
}

// PRODUCER defaults from APPROVAL_DEFAULTS in wizard_service.py
export const THRESHOLDS = { low: 100, medium: 500 };

export function getRequiredRole(absQty: number): "NONE" | "RM" | "NM" {
  if (absQty < THRESHOLDS.low)    return "NONE";
  if (absQty < THRESHOLDS.medium) return "RM";
  return "NM";
}

export const demoAdjustments: AdjustRecord[] = [];
