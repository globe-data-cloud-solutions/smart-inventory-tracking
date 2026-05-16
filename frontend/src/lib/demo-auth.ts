"use client";

import { ALL_DEMO_USERS, DEMO_TENANTS, type Role } from "@/lib/demo-data";

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  /** URL-safe org identifier used as the first path segment: /addis-water/dashboard */
  orgSlug: string;
  tenantId?: string;
  tenantName?: string;
  tenantSlug?: string;
  warehouseId?: string;
  warehouseName?: string;
}

/** SA org slug — used as the first path segment for system administrators. */
export const SA_ORG_SLUG = "admin";

const SESSION_KEY = "smart_demo_session";

function store(): Storage | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage; } catch { return null; }
}

export function login(email: string, password: string): SessionUser | null {
  const found = ALL_DEMO_USERS.find(
    (u) => u.email.toLowerCase() === email.toLowerCase() && u.password === password
  );
  if (!found) return null;

  let tenantId: string | undefined;
  let tenantName: string | undefined;
  let tenantSlug: string | undefined;
  let orgSlug = SA_ORG_SLUG;

  if (found.role !== "SA") {
    const tenant = DEMO_TENANTS.find((t) => t.users.some((u) => u.id === found.id));
    tenantId   = tenant?.id;
    tenantName = tenant?.name;
    tenantSlug = tenant?.slug;
    orgSlug    = tenant?.slug ?? SA_ORG_SLUG;
  }

  const session: SessionUser = {
    id:    found.id,
    email: found.email,
    name:  found.name,
    role:  found.role as Role,
    orgSlug,
    tenantId,
    tenantName,
    tenantSlug,
    warehouseId:   "warehouseId"   in found
      ? (found as { warehouseId: string }).warehouseId
      : undefined,
    warehouseName: "warehouseName" in found
      ? (found as { warehouseName: string }).warehouseName
      : undefined,
  };

  store()?.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export function getSession(): SessionUser | null {
  const raw = store()?.getItem(SESSION_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw) as SessionUser; } catch { return null; }
}

export function logout(): void {
  store()?.removeItem(SESSION_KEY);
}

/** Build an org-scoped URL: /{orgSlug}/{page} */
export function orgUrl(orgSlug: string, page: string): string {
  return `/${orgSlug}/${page}`;
}

