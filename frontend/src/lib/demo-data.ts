// demo-data.ts — Session 1 clean slate
// DEMO_TENANTS is intentionally empty.
// All tenant data is now stored in the database; the BFF demo layer is retired.
// Kept: type definitions and helper stubs required by existing imports.

export type OrgType = "PRODUCER" | "RETAILER" | "HYBRID";
export type WarehouseType = "MWH" | "RWH" | "WH" | "SUB_WH";
export type Role = "SA" | "TA" | "NM" | "RM" | "WM" | "LM" | "AU" | "PENDING_SETUP";

export interface DemoWarehouse {
  id: string;
  name: string;
  type: WarehouseType;
  parentId: string | null;
  location?: string;
  manager?: string;
  managerEmail?: string;
  level_number?: number;
}

// Design-B per-product approval override summary — see
// backend/services/product-service/schemas/product.py ProductApprovalOverride.
export interface ProductApprovalOverride {
  mode: "ALWAYS" | "QUANTITY" | "VALUE";
  threshold?: number | string | null;
  approver_label?: string | null;
  note?: string | null;
}

export interface DemoProduct {
  id: string;
  name: string;
  sku: string;
  category: string;
  unit: string;
  batchTracking: boolean;
  expiryTracking?: boolean;
  reorderPoint: number;
  stock: Record<string, number>;
  shortName?: string;
  description?: string;
  image_url?: string | null;
  is_discontinued?: boolean;
  approval_overrides?: Record<string, ProductApprovalOverride>;
}

export interface DemoUser {
  id: string;
  email: string;
  password: string;
  name: string;
  role: Role;
  warehouseId?: string;
  warehouseName?: string;
}

export interface DemoTenant {
  id: string;
  name: string;
  slug: string;
  logo: string;
  orgType: OrgType;
  warehouses: DemoWarehouse[];
  products: DemoProduct[];
  users: DemoUser[];
  // Legacy display fields referenced by dashboard/audit-log/analytics pages.
  // Kept as optional so existing pages compile; values come from the API in gateway mode.
  color?:       string;
  bgClass?:     string;
  industry?:    string;
  description?: string;
}

// ── Empty exports — all real data lives in the database ───────────────────────

export const DEMO_TENANTS: DemoTenant[] = [];

// ── Helper stubs — return empty/zero for gateway mode ────────────────────────

export function getTenantBySlug(_slug: string): DemoTenant | undefined {
  return undefined;
}

export function getTotalStock(_product: DemoProduct): number {
  return 0;
}

export function getLowStockProducts(_tenant: DemoTenant): DemoProduct[] {
  return [];
}

export function getWarehouseTree(warehouses: DemoWarehouse[]): DemoWarehouse[] {
  return warehouses.filter((w) => w.parentId === null);
}

export function getChildren(warehouses: DemoWarehouse[], parentId: string): DemoWarehouse[] {
  return warehouses.filter((w) => w.parentId === parentId);
}
