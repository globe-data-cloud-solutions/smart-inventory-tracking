const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

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

  const json = (await res.json()) as ApiResponse<T> | ApiError;

  if (!res.ok || !json.success) {
    const err = json as ApiError;
    const apiErr = new Error(err.error?.message ?? `HTTP ${res.status}`) as Error & { status: number; code: string };
    apiErr.status = res.status;
    apiErr.code   = err.error?.code ?? "";
    throw apiErr;
  }

  return (json as ApiResponse<T>).data;
}

export const api = {
  get:    <T>(path: string, token?: string) => request<T>("GET",    path, undefined, token),
  post:   <T>(path: string, body: unknown, token?: string) => request<T>("POST",   path, body, token),
  patch:  <T>(path: string, body: unknown, token?: string) => request<T>("PATCH",  path, body, token),
  delete: <T>(path: string, token?: string) => request<T>("DELETE", path, undefined, token),
};
