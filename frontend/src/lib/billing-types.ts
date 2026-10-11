// Shared with app/(auth)/signup/page.tsx and components/features/billing/PlanComparisonModal.tsx —
// mirrors backend/services/tenant-service/routers/public_signup.py's package catalog response.

export type BillingPeriod = "MONTHLY" | "ANNUAL";

export interface PriceOut {
  subtotal: string;
  vat_rate: string;
  vat_amount: string;
  total: string;
  currency: string;
}

export interface PackageOut {
  tier: string;
  display_name: string | null;
  max_warehouses: number | null;
  max_users: number | null;
  sku_cap: number | null;
  feature_flags: Record<string, boolean>;
  prices: Partial<Record<BillingPeriod, PriceOut>>;
}

export interface PackagesListOut {
  packages: PackageOut[];
  terms_version: string;
}
