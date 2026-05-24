export type AdjustStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "APPLIED" | "REJECTED" | "CANCELLED";

export interface AdjustRecord {
  id: string;
  tenant_slug: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  quantity: number;
  reason_code: string;
  notes: string;
  status: AdjustStatus;
  approval_required_role: "NONE" | "RM" | "NM" | "TA";
  idempotency_key: string;
  created_at: string;
}

export const THRESHOLDS = { low: 100, medium: 1000 };

export function getRequiredRole(absQty: number): "NONE" | "RM" | "NM" | "TA" {
  if (absQty < THRESHOLDS.low)    return "NONE";
  if (absQty < THRESHOLDS.medium) return "RM";
  return "TA";
}

declare global {
  // eslint-disable-next-line no-var
  var _smartDemoAdjustments: AdjustRecord[] | undefined;
}

if (!globalThis._smartDemoAdjustments) globalThis._smartDemoAdjustments = [];

export const demoAdjustments: AdjustRecord[] = globalThis._smartDemoAdjustments;
