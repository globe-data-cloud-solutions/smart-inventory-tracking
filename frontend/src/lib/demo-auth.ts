"use client";

import { ALL_DEMO_USERS, DEMO_TENANTS, type Role } from "@/lib/demo-data";

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  tenantId?: string;
  tenantName?: string;
  warehouseId?: string;
  warehouseName?: string;
}

// localStorage persists across tab close / browser suspend / back-forward cache.
// sessionStorage was the bug: it cleared on tab close, causing 404 after idle.
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

  if (found.role !== "SA") {
    const tenant = DEMO_TENANTS.find((t) => t.users.some((u) => u.id === found.id));
    tenantId  = tenant?.id;
    tenantName = tenant?.name;
  }

  const session: SessionUser = {
    id:           found.id,
    email:        found.email,
    name:         found.name,
    role:         found.role as Role,
    tenantId,
    tenantName,
    warehouseId:   "warehouseId"   in found ? found.warehouseId   : undefined,
    warehouseName: "warehouseName" in found ? found.warehouseName : undefined,
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

export function requireSession(): SessionUser | null {
  return getSession();
}
