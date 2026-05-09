const TOKEN_KEY = "smart_jwt";

export interface JWTPayload {
  sub: string;
  role: string;
  tenant_id: string;
  region_id: string | null;
  warehouse_id: string | null;
  iat: number;
  exp: number;
}

export function storeToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function decodePayload(token: string): JWTPayload {
  const base64 = token.split(".")[1];
  if (!base64) throw new Error("Invalid JWT");
  const json = atob(base64.replace(/-/g, "+").replace(/_/g, "/"));
  return JSON.parse(json) as JWTPayload;
}

export function isTokenExpired(token: string): boolean {
  try {
    const { exp } = decodePayload(token);
    return Date.now() / 1000 > exp;
  } catch {
    return true;
  }
}

export function getCurrentUser(): JWTPayload | null {
  const token = getToken();
  if (!token || isTokenExpired(token)) return null;
  try {
    return decodePayload(token);
  } catch {
    return null;
  }
}
