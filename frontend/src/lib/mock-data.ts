/**
 * Mock data for frontend-only development (no backend required).
 * Set NEXT_PUBLIC_USE_MOCK_DATA=true in .env.local to enable.
 */

import { ApiResponse } from "./api";

export interface MockContext {
  tenantId?: string;
  userId?: string;
  userRole?: string;
}

// Tenant data by ID - used when TA logs in
const TENANT_DATA: Record<string, unknown> = {
  "t01-uuid-0000-0000-000000000001": {
    id: "t01-uuid-0000-0000-000000000001",
    name: "Addis Water Supply",
    organisation_type: "PRODUCER",
    onboarding_complete: true,
    default_locale: "en",
    is_active: true,
    contract_start: "2026-01-01",
    contract_end: "2027-01-01",
    plan_tier: "GROWTH",
    max_warehouses: 10,
    max_users: 50,
  },
  "t02-uuid-0000-0000-000000000002": {
    id: "t02-uuid-0000-0000-000000000002",
    name: "East Africa Retail",
    organisation_type: "RETAILER",
    onboarding_complete: true,
    default_locale: "en",
    is_active: true,
    contract_start: "2026-02-01",
    contract_end: "2027-02-01",
    plan_tier: "ENTERPRISE",
    max_warehouses: 50,
    max_users: 200,
  },
};

// Mock contacts (mutable for demo)
let mockContacts = [
  {
    id: "contact-1",
    is_primary: true,
    full_name: "John Doe",
    email: "john@example.com",
    phone: "+1-555-0100",
    position_title: "Operations Manager",
  },
  {
    id: "contact-2",
    is_primary: false,
    full_name: "Jane Smith",
    email: "jane@example.com",
    phone: "+1-555-0101",
    position_title: "Finance Lead",
  },
];

export function getMockResponse<T>(
  path: string,
  method: string,
  body?: unknown,
  context?: MockContext
): T | null {
  // Get the user's tenant ID from session if available
  function getTenantDataForUser(): unknown {
    // For TA users, derive tenant from email or use context
    if (typeof window !== "undefined") {
      try {
        const session = JSON.parse(window.localStorage.getItem("smart_demo_session") || "{}") as Record<string, unknown>;
        const tenantId = session.tenantId || context?.tenantId;
        if (tenantId && TENANT_DATA[tenantId as string]) {
          return TENANT_DATA[tenantId as string];
        }
      } catch {
        // Fall through to default
      }
    }
    // Default to Addis Water Supply (t01) for SA or when no tenant context
    return TENANT_DATA["t01-uuid-0000-0000-000000000001"];
  }

  // Tenant Profile
  if (path === "/api/v1/tenants/me/profile" && method === "GET") {
    return getTenantDataForUser() as T;
  }

  // Update Profile (Tenant Admin can only edit locale)
  if (path === "/api/v1/tenants/me/profile" && method === "PATCH") {
    const updateData = body as Record<string, unknown>;
    const tenantData = getTenantDataForUser() as Record<string, unknown>;
    return {
      ...tenantData,
      default_locale: updateData.default_locale ?? tenantData.default_locale,
    } as T;
  }

  // Tenant Plan
  if (path === "/api/v1/tenants/me/plan" && method === "GET") {
    const tenantData = getTenantDataForUser() as Record<string, unknown>;
    const planTier = (tenantData.plan_tier as string) || "GROWTH";
    const features: Record<string, boolean> = {
      CORE_INVENTORY: true,
      TRANSFERS_PULL_PUSH: true,
      TRANSFERS_SISTER: planTier !== "STARTER",
      LOT_TRACEABILITY: true,
      LOGISTICS: planTier !== "STARTER",
      AUDIT_EXPORT: planTier !== "STARTER",
      CUSTOM_BRANDING: planTier === "ENTERPRISE",
      AI_ANALYTICS: planTier !== "STARTER",
      API_ACCESS: planTier === "ENTERPRISE",
    };
    return {
      plan_tier: planTier,
      max_warehouses: tenantData.max_warehouses,
      max_users: tenantData.max_users,
      sku_cap: planTier === "ENTERPRISE" ? null : 5000,
      feature_flags: features,
    } as T;
  }

  // Contract Update (renewal)
  if (path === "/api/v1/tenants/me/contract" && method === "PATCH") {
    const updateData = body as Record<string, unknown>;
    const tenantData = getTenantDataForUser() as Record<string, unknown>;
    const newEndDate = updateData.contract_end ?? "2027-12-31";
    return {
      ...tenantData,
      contract_end: newEndDate,
    } as T;
  }

  // Get Contacts
  if (path === "/api/v1/tenants/me/contacts" && method === "GET") {
    return mockContacts as T;
  }

  // Create Contact
  if (path === "/api/v1/tenants/me/contacts" && method === "POST") {
    const newContact = body as Record<string, unknown>;
    const contact: Record<string, unknown> = {
      id: `contact-${Date.now()}`,
      is_primary: (newContact.is_primary as boolean | undefined) ?? false,
      full_name: (newContact.full_name as string | undefined) ?? "",
      email: (newContact.email as string | undefined) ?? "",
      phone: (newContact.phone as string | undefined) ?? "",
      position_title: (newContact.position_title as string | undefined) ?? "",
    };
    mockContacts.push(contact as any);
    return contact as T;
  }

  // Update Contact
  const updateContactMatch = path.match(/^\/api\/v1\/tenants\/me\/contacts\/(.+)$/);
  if (updateContactMatch && method === "PATCH") {
    const contactId = updateContactMatch[1];
    const updateData = body as Record<string, unknown>;
    const index = mockContacts.findIndex((c) => c.id === contactId);
    if (index >= 0) {
      const original = mockContacts[index]!;
      const updated = {
        id: original.id,
        is_primary: (updateData.is_primary as boolean | undefined) ?? original.is_primary,
        full_name: (updateData.full_name as string | undefined) ?? original.full_name,
        email: (updateData.email as string | undefined) ?? original.email,
        phone: (updateData.phone as string | undefined) ?? original.phone,
        position_title:
          (updateData.position_title as string | undefined) ?? original.position_title,
      };
      mockContacts[index] = updated;
      return updated as T;
    }
  }

  // Delete Contact
  if (updateContactMatch && method === "DELETE") {
    const contactId = updateContactMatch[1];
    mockContacts = mockContacts.filter((c) => c.id !== contactId);
    return { success: true } as T;
  }

  // No mock for this path
  return null;
}

export function createMockApiResponse<T>(data: T): ApiResponse<T> {
  return {
    success: true,
    data,
    request_id: `mock-${Date.now()}`,
    timestamp: new Date().toISOString(),
  };
}
