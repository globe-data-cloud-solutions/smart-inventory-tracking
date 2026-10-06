const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

/**
 * True when a real backend URL is configured (NEXT_PUBLIC_API_URL is set and non-empty).
 * Import this constant instead of re-computing !!process.env.NEXT_PUBLIC_API_URL everywhere,
 * and especially instead of using stockData.length > 0 as a proxy for gateway mode.
 *
 * Gateway mode:  API is the single source of truth — Zustand session state must NOT be
 *                added on top of API values or stock will be doubled.
 * Demo mode:     No backend; BFF routes (Next.js /api/v1/*) handle requests in-process
 *                and Zustand tracks session-time movements.
 */
export const IS_GATEWAY_MODE = !!BASE_URL;

type Method = "GET" | "POST" | "PATCH" | "DELETE" | "PUT";

interface _Session {
  orgSlug?: string;
  role?: string;
  warehouseId?: string;
  jwtToken?: string;
}

function _readSession(): _Session {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem("smart_demo_session");
    return raw ? (JSON.parse(raw) as _Session) : {};
  } catch { return {}; }
}

/** Decode JWT exp claim. Returns seconds-since-epoch or null if unreadable. */
function _jwtExp(token: string): number | null {
  try {
    const b64 = token.split(".")[1]?.replace(/-/g, "+").replace(/_/g, "/") ?? "";
    const payload = JSON.parse(atob(b64)) as { exp?: number };
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch { return null; }
}

/** True if the token has expired or will expire within windowSeconds (default 5 min). */
function _isJwtExpiringSoon(token: string, windowSeconds = 300): boolean {
  const exp = _jwtExp(token);
  if (exp === null) return false;
  return Date.now() / 1000 >= exp - windowSeconds;
}

/** Redirect to /login preserving the current path and signalling session expiry. */
function _redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const from = window.location.pathname + window.location.search;
  const params = new URLSearchParams({ reason: "session_expired", from });
  window.location.href = `/login?${params.toString()}`;
}

/** Read the tenant slug from the session so API routes can filter by tenant. */
function getTenantSlug(): string {
  const s = _readSession();
  return s.orgSlug && s.orgSlug !== "admin" ? s.orgSlug : "";
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  request_id: string;
  timestamp: string;
}

export interface ApiError {
  success: false;
  error: { code: string; message: string };
  request_id: string;
  timestamp: string;
}

async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
  token?: string
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  // JWT from session (stored after login's fire-and-forget _exchangeJWT call).
  // An explicit token argument always wins; falls back to the session JWT.
  const session = _readSession();
  const bearer = token ?? session.jwtToken;

  // Pre-flight: redirect before sending if the token is expired or about to expire.
  if (bearer && _isJwtExpiringSoon(bearer)) {
    _redirectToLogin();
    return new Promise<T>(() => { /* navigation pending */ });
  }

  if (bearer) headers["Authorization"] = `Bearer ${bearer}`;
  const tenantSlug = getTenantSlug();
  if (tenantSlug) headers["X-Tenant-Slug"] = tenantSlug;
  // Pass caller identity so server-side route handlers can enforce ABAC.
  if (session.role)        headers["X-User-Role"]         = session.role;
  if (session.warehouseId) headers["X-User-Warehouse-Id"] = session.warehouseId;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  // 401 when a JWT was sent means the token was rejected — clear session.
  // 401 with no JWT (SA with no token yet, or BFF mode) is surfaced as a normal
  // API error so the session is not destroyed for users who are still valid.
  if (res.status === 401) {
    if (bearer) {
      window.localStorage.removeItem("smart_demo_session");
      _redirectToLogin();
      return new Promise<T>(() => { /* navigation pending */ });
    }
    const authErr = new Error("Unauthorized") as Error & { status: number; code: string };
    authErr.status = 401;
    authErr.code   = "UNAUTHORIZED";
    throw authErr;
  }

  const json = (await res.json()) as ApiResponse<T> | ApiError;

  if (!res.ok || !json.success) {
    const err = json as ApiError;
    // FastAPI HTTPException returns {"detail": {...}} instead of {"error": {...}}.
    // Fall back to the detail field so the error code and message are not lost.
    type DetObj = { code?: string; message?: string; detail?: string; locations?: Array<{ warehouse: string; on_hand: number }> };
    const raw   = json as unknown as { detail?: DetObj | string };
    const det   = typeof raw.detail === "object" ? raw.detail : null;
    const detMsg = det?.message ?? det?.detail ?? (typeof raw.detail === "string" ? raw.detail : "");
    const detCode = det?.code ?? "";
    const apiErr = new Error(err.error?.message ?? (detMsg || `HTTP ${res.status}`)) as Error & { status: number; code: string; locations?: Array<{ warehouse: string; on_hand: number }> };
    apiErr.status    = res.status;
    apiErr.code      = err.error?.code ?? detCode;
    if (det?.locations) apiErr.locations = det.locations;
    throw apiErr;
  }

  return (json as ApiResponse<T>).data;
}

export const api = {
  get:    <T>(path: string, token?: string) => request<T>("GET",    path, undefined, token),
  post:   <T>(path: string, body: unknown, token?: string) => request<T>("POST",   path, body, token),
  put:    <T>(path: string, body: unknown, token?: string) => request<T>("PUT",    path, body, token),
  patch:  <T>(path: string, body: unknown, token?: string) => request<T>("PATCH",  path, body, token),
  delete: <T>(path: string, token?: string) => request<T>("DELETE", path, undefined, token),
};

/**
 * POST to an endpoint that returns a raw JSON body (not the {success, data, ...}
 * envelope) — e.g. auth-service's /verify-email and /resend-verification, which
 * predate the SuccessResponse convention and carry no SMART JWT. Never use `api.post`
 * for these: it throws on any response lacking `success: true`, which these never set.
 */
export async function rawPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = (await res.json().catch(() => null)) as
    | { detail?: { code?: string; message?: string } | string }
    | null;
  if (!res.ok) {
    const det = json?.detail;
    const detObj = typeof det === "object" ? det : null;
    const message = detObj?.message ?? (typeof det === "string" ? det : `HTTP ${res.status}`);
    const err = new Error(message) as Error & { status: number; code?: string };
    err.status = res.status;
    err.code = detObj?.code;
    throw err;
  }
  return json as T;
}
