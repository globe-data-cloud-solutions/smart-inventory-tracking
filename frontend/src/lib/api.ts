const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

type Method = "GET" | "POST" | "PATCH" | "DELETE" | "PUT";

/** Read the tenant slug from the session so API routes can filter by tenant. */
function getTenantSlug(): string {
  if (typeof window === "undefined") return "";
  try {
    const raw = window.localStorage.getItem("smart_demo_session");
    if (!raw) return "";
    const s = JSON.parse(raw) as { orgSlug?: string };
    return s.orgSlug && s.orgSlug !== "admin" ? s.orgSlug : "";
  } catch { return ""; }
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
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const tenantSlug = getTenantSlug();
  if (tenantSlug) headers["X-Tenant-Slug"] = tenantSlug;

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
