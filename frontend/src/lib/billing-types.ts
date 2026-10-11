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

// Mirrors backend/services/tenant-service/routers/platform_contact.py's ContactOut.
export interface LocalizedText {
  en: string | null;
  am: string | null;
}

export interface ContactInfo {
  configured: boolean;
  support_email: string | null;
  phone: string | null;
  whatsapp: string | null;
  address: LocalizedText;
  hours: LocalizedText;
  note: LocalizedText;
  updated_at: string;
}

/** am -> am value falling back to en; en/or -> en, per the i18n loader's locale fallback order. */
export function pickLocalized(text: LocalizedText, locale: string): string | null {
  if (locale === "am") return text.am ?? text.en ?? null;
  return text.en ?? null;
}
