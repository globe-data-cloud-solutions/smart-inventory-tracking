export interface OnboardedTenant {
  id: string;
  name: string;
  slug: string;
  industry: string;
  org_type: "PRODUCER" | "RETAILER" | "HYBRID";
  default_locale: "en" | "am" | "or";
  sku_limit: number | null;
  feature_flags: Record<string, boolean>;
  approval_thresholds: Record<string, unknown>;
  onboarding_complete: boolean;
  created_at: string;
}

declare global {
  // eslint-disable-next-line no-var
  var _smartOnboardedTenants: OnboardedTenant[] | undefined;
}

if (!globalThis._smartOnboardedTenants) {
  globalThis._smartOnboardedTenants = [];
}

export const onboardedTenants: OnboardedTenant[] = globalThis._smartOnboardedTenants;
