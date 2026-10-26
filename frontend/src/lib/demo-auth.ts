"use client";

import { type Role } from "@/lib/demo-data";
import { t, hasKey } from "@/lib/i18n";

/** One active position from the user's personnel_positions record. */
export interface ActivePosition {
  positionId:     string;
  roleCode:       string;
  nodeId:         string;
  nodeName:       string;
  levelNumber:    number;
  assignmentType: "PRIMARY" | "ACTING" | "DELEGATE";
}

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
  /** Session 2: position-derived claims from auth-service. */
  positionId?:    string;
  positionTitle?: string;
  levelNumber?:   number;
  /** All active positions (PRIMARY + ACTING + DELEGATE) for multi-facility ABAC. */
  positions?: ActivePosition[];
  /** SMART JWT — present in gateway mode.  api.ts reads this as Authorization: Bearer. */
  jwtToken?: string;
  /** When true the user must change their password before proceeding. */
  mustResetPassword?: boolean;
  /** When true the account owner must re-accept the current terms version
   * before proceeding (checked after mustResetPassword, never before). */
  termsAcceptanceRequired?: boolean;
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
 * Sign in via POST /api/v1/auth/token {email, password} — the only login
 * path (works in every environment; auth-service requires a password).
 *
 * Error mapping:
 *   429 (lockout)                          → throws Error (status=429), message is user-facing
 *   403 TENANT_SUSPENDED/DEACTIVATED/
 *       EMAIL_NOT_VERIFIED                 → throws Error (status=403, code=<code>)
 *   5xx AUTH_SERVICE_UNAVAILABLE           → throws Error (status=5xx, code=AUTH_SERVICE_UNAVAILABLE)
 *   401 INVALID_CREDENTIALS / 422 PASSWORD_REQUIRED / anything else → null (generic message on the form)
 *
 * Throws an Error with code=AUTH_NOT_CONFIGURED if no auth base URL is set —
 * there is no client-only fallback.
 */
export async function loginWithPassword(email: string, password: string): Promise<SessionUser | null> {
  const authBase =
    process.env.NEXT_PUBLIC_AUTH_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "";
  if (!authBase) {
    const err = new Error("Auth service is not configured") as Error & { code?: string };
    err.code = "AUTH_NOT_CONFIGURED";
    throw err;
  }

  try {
    const res = await fetch(`${authBase}/api/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      // 429 (login lockout) carries a specific message the login form must
      // show verbatim — every other failure (401, 422, etc.) stays a generic
      // null so as not to leak whether the email exists.
      if (res.status === 429) {
        const errBody = (await res.json().catch(() => null)) as
          | { detail?: { code?: string; message?: string } }
          | null;
        const code = errBody?.detail?.code;
        const message = code && hasKey(`errors.${code}`)
          ? t(`errors.${code}`)
          : (errBody?.detail?.message ??
            "Too many failed login attempts. Please wait 15 minutes before trying again, or contact your administrator.");
        const err = new Error(message) as Error & { status?: number; code?: string };
        err.status = 429;
        err.code = code;
        throw err;
      }
      if (res.status === 403) {
        const errBody = (await res.json().catch(() => null)) as
          | { detail?: { code?: string; message?: string } }
          | null;
        const code = errBody?.detail?.code;
        if (code === "TENANT_SUSPENDED" || code === "TENANT_DEACTIVATED" || code === "EMAIL_NOT_VERIFIED") {
          const message = hasKey(`errors.${code}`)
            ? t(`errors.${code}`)
            : (errBody?.detail?.message ?? "Your account access has been restricted. Please contact your administrator.");
          const err = new Error(message) as Error & { status?: number; code?: string };
          err.status = 403;
          err.code = code;
          throw err;
        }
      }
      // 5xx (AUTH_SERVICE_UNAVAILABLE): the service failed, not the credentials.
      if (res.status >= 500) {
        const err = new Error(t("login.auth_unavailable")) as Error & { status?: number; code?: string };
        err.status = res.status;
        err.code = "AUTH_SERVICE_UNAVAILABLE";
        throw err;
      }
      return null;
    }
    const data = (await res.json()) as {
      access_token?: string;
      tenant_slug?: string | null;
      must_reset_password?: boolean;
      terms_acceptance_required?: boolean;
    };
    if (!data.access_token) return null;

    const claims = decodeJwtPayload(data.access_token);
    if (!claims) return null;

    const tenantId      = claims.tenant_id      ? String(claims.tenant_id)      : undefined;
    const warehouseId   = claims.warehouse_id   ? String(claims.warehouse_id)   : undefined;
    const warehouseName = claims.warehouse_name ? String(claims.warehouse_name) : undefined;
    const role          = claims.role           ? String(claims.role)           : "AU";
    const sub           = claims.sub            ? String(claims.sub)            : email;
    const positionId    = claims.position_id    ? String(claims.position_id)    : undefined;
    const positionTitle = claims.position_title ? String(claims.position_title) : undefined;
    const levelNumber   = typeof claims.level_number === "number" ? claims.level_number : undefined;
    const positions: ActivePosition[] = Array.isArray(claims.positions)
      ? (claims.positions as Record<string, unknown>[]).map((p) => ({
          positionId:     String(p["position_id"]     ?? ""),
          roleCode:       String(p["role_code"]       ?? ""),
          nodeId:         String(p["node_id"]         ?? ""),
          nodeName:       String(p["node_name"]       ?? ""),
          levelNumber:    typeof p["level_number"] === "number" ? p["level_number"] : 0,
          assignmentType: String(p["assignment_type"] ?? "PRIMARY") as ActivePosition["assignmentType"],
        }))
      : [];

    const orgSlug = (role === "SA") ? SA_ORG_SLUG : (data.tenant_slug ?? tenantId ?? SA_ORG_SLUG);

    const session: SessionUser = {
      id:                sub,
      email,
      name:              claims.name ? String(claims.name) : (email.split("@")[0] ?? email),
      role:              role as Role,
      orgSlug,
      tenantId,
      tenantName:        tenantId,
      tenantSlug:        data.tenant_slug ?? orgSlug,
      warehouseId,
      warehouseName,
      positionId,
      positionTitle,
      levelNumber,
      positions,
      jwtToken:          data.access_token,
      mustResetPassword: data.must_reset_password ?? false,
      termsAcceptanceRequired: data.terms_acceptance_required ?? false,
    };
    store()?.setItem(SESSION_KEY, JSON.stringify(session));
    return session;
  } catch (err) {
    // Lockout and restricted-account errors carry status=429/403 and must
    // propagate to the caller (the login form needs the specific message) —
    // every other failure (network error, bad JSON, etc.) stays a generic
    // null as before.
    if (err instanceof Error) {
      const status = (err as Error & { status?: number }).status;
      if (status === 429 || status === 403 || (status !== undefined && status >= 500)) {
        throw err;
      }
    }
    return null;
  }
}

export function getSession(): SessionUser | null {
  const raw = store()?.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    const session = JSON.parse(raw) as SessionUser;
    // If the JWT is present and has expired, strip the token but preserve the
    // demo session. SA has tenant_id=null which is valid; api.ts handles 401s.
    if (session.jwtToken) {
      const payload = decodeJwtPayload(session.jwtToken);
      const exp = typeof payload?.exp === "number" ? payload.exp : null;
      if (exp !== null && Date.now() / 1000 >= exp) {
        const { jwtToken: _expired, ...rest } = session;
        store()?.setItem(SESSION_KEY, JSON.stringify(rest));
        return rest as SessionUser;
      }
    }
    return session;
  } catch { return null; }
}

export function logout(): void {
  store()?.removeItem(SESSION_KEY);
}

/** Build an org-scoped URL: /{orgSlug}/{page} */
export function orgUrl(orgSlug: string, page: string): string {
  return `/${orgSlug}/${page}`;
}
