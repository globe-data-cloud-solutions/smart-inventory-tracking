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
  /** SMART JWT — present when NEXT_PUBLIC_API_URL points to the Python gateway.
   *  Exchanged asynchronously after login; absent during the first render.
   *  api.ts reads this and sends it as Authorization: Bearer. */
  jwtToken?: string;
  /** When true, the user must change their password before proceeding. */
  mustResetPassword?: boolean;
}

/** SA org slug — used as the first path segment for system administrators. */
export const SA_ORG_SLUG = "admin";

const SESSION_KEY = "smart_demo_session";

function store(): Storage | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage; } catch { return null; }
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const b64 = parts[1]!.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Exchange a SMART JWT for a demo session.
 * Called fire-and-forget after login() so the token is ready before the first
 * authenticated API call.
 *
 * Routing:
 *   NEXT_PUBLIC_AUTH_URL set  → call real auth-service with dev_email (Phase 4B Step 1+)
 *   NEXT_PUBLIC_API_URL set   → fallback for gateway mode without dedicated auth URL
 *   Both empty                → BFF-only mode, no JWT needed
 *
 * The dev_email path returns a JWT with exact seed UUIDs matching the database.
 */
async function _exchangeJWT(session: SessionUser): Promise<void> {
  const authBase =
    process.env.NEXT_PUBLIC_AUTH_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "";
  if (!authBase) return; // BFF mode — no gateway, no JWT needed

  try {
    const res = await fetch(`${authBase}/api/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dev_email: session.email }),
    });
    if (!res.ok) return;
    const data = (await res.json()) as { access_token?: string };
    if (!data.access_token) return;

    // Patch the stored session with the JWT and real warehouse/tenant IDs from claims
    const raw = store()?.getItem(SESSION_KEY);
    if (!raw) return;
    const stored = JSON.parse(raw) as SessionUser;
    stored.jwtToken = data.access_token;
    const claims = decodeJwtPayload(data.access_token);
    if (claims) {
      if (claims.warehouse_id) stored.warehouseId = String(claims.warehouse_id);
      if (claims.tenant_id)    stored.tenantId    = String(claims.tenant_id);
    }
    store()?.setItem(SESSION_KEY, JSON.stringify(stored));
  } catch {
    // Auth service unreachable — continue without JWT (BFF routes handle it)
  }
}

/**
 * Login path for backend-created users not present in ALL_DEMO_USERS.
 * Calls dev_email endpoint; uses tenant_id UUID as the orgSlug so the
 * URL becomes /{tenant_id}/dashboard.
 * Only works when ENVIRONMENT=local on the auth-service side.
 */
export async function loginWithDevEmail(email: string, password?: string): Promise<SessionUser | null> {
  const authBase =
    process.env.NEXT_PUBLIC_AUTH_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "";
  if (!authBase) return null;

  try {
    const body: Record<string, string> = { dev_email: email };
    if (password) body.dev_password = password;
    const res = await fetch(`${authBase}/api/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as {
      access_token?: string;
      tenant_slug?: string | null;
      must_reset_password?: boolean;
    };
    if (!data.access_token) return null;

    const claims = decodeJwtPayload(data.access_token);
    if (!claims) return null;

    const tenantId    = claims.tenant_id    ? String(claims.tenant_id)    : undefined;
    const warehouseId = claims.warehouse_id ? String(claims.warehouse_id) : undefined;
    const role        = claims.role         ? String(claims.role)         : "AU";
    const sub         = claims.sub          ? String(claims.sub)          : email;
    // Prefer the friendly slug returned by auth-service; fall back to tenant_id UUID
    const orgSlug = (role === "SA") ? SA_ORG_SLUG : (data.tenant_slug ?? tenantId ?? SA_ORG_SLUG);

    const session: SessionUser = {
      id:                 sub,
      email,
      name:               email.split("@")[0] ?? email,
      role:               role as Role,
      orgSlug,
      tenantId,
      tenantName:         tenantId,   // layout.tsx will overwrite this async with the real name
      tenantSlug:         data.tenant_slug ?? orgSlug,
      warehouseId,
      jwtToken:           data.access_token,
      mustResetPassword:  data.must_reset_password ?? false,
    };
    store()?.setItem(SESSION_KEY, JSON.stringify(session));
    return session;
  } catch {
    return null;
  }
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

  // Fire-and-forget JWT exchange — token will be in localStorage before the
  // first dashboard API call (login triggers a router.push and a brief re-render)
  void _exchangeJWT(session);

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
