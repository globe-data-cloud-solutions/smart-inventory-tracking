import { ReactNode } from "react";

export interface TenantAdminData {
  id: string;
  name: string;
  slug: string | null;
  organisation_type: string | null;
  default_locale: string;
  is_active: boolean;
  status: string | null;
  onboarding_complete: boolean;
  logo_url: string | null;
  banner_url: string | null;
  plan_tier: string | null;
  max_warehouses: number | null;
  max_users: number | null;
  contract_start: string | null;
  contract_end: string | null;
  admin_user_id: string | null;
  admin_email: string | null;
}

export interface PlanData {
  plan_tier: string;
  feature_flags: Record<string, boolean>;
  max_warehouses: number | null;
  max_users: number | null;
  sku_cap: number | null;
  contract_start: string | null;
  contract_end: string | null;
  /** Codes currently granted via an ACTIVE tenant_addons row (S10) —
   * get_tenant_entitlements() OR's these into feature_flags, so a code here
   * means the flag is true because of an add-on, not necessarily the package. */
  addons: string[];
}

/** One grant from GET /{tenant_id}/addons or /me/addons (S10). */
export interface TenantAddonOut {
  id: string;
  addon_code: string;
  display_name: string;
  source: "OVERRIDE" | "PURCHASED";
  status: "ACTIVE" | "CANCELLED";
  amount: string;
  currency: string;
  starts_on: string;
  ends_on: string | null;
  note: string | null;
  created_at: string;
  cancelled_at: string | null;
}

export interface TenantContact {
  id: string;
  tenant_id: string;
  is_primary: boolean;
  full_name: string;
  email: string;
  phone?: string | null;
  position_title?: string | null;
  mobile?: string | null;
  created_at: string;
}

export interface TabProps {
  /**
   * Real tenant UUID — present only when an SA is viewing another tenant's
   * settings (frontend/src/app/[org]/settings/tenants/[tenantId]/page.tsx).
   * When set, every tab calls the SA by-tenant endpoint (/api/v1/tenants/{tenantId}/...)
   * instead of the TA self-service one (/api/v1/tenants/me/...) and enables
   * SA-only controls. The TA's own page (tenant-admin/page.tsx) never passes this.
   */
  tenantId?: string;
  isLoading?: boolean;
  readonly?: boolean;
}

export interface Tab {
  id: string;
  label: string;
  icon: string;
  component: (props: TabProps) => ReactNode;
}
