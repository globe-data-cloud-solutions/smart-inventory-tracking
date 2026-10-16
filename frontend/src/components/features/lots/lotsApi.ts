import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

/* ── GET /api/v1/inventory/lots ─────────────────────────────────────────── */
export type LotStatus = "ACTIVE" | "DEPLETED" | "EXPIRED";

export interface LotApi {
  lot_id: string;
  lot_number: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  quantity: string | number;
  expiry_date: string | null;
  first_received_at: string;
  is_opening: boolean;
  status: LotStatus;
  days_to_expiry: number | null;
  expiring_soon: boolean;
}

/* ── GET /api/v1/inventory/lots/expiry-alerts ───────────────────────────── */
export type ExpiryAlertType = "EXPIRED" | "EXPIRING" | "NO_EXPIRY";

export interface ExpiryAlertItem {
  lot_id: string;
  lot_number: string;
  product_id: string;
  warehouse_id: string;
  alert_type: ExpiryAlertType;
  days_to_expiry: number | null;
}

export interface ExpiryAlertsApi {
  window_days: number;
  counts: { expired: number; expiring: number; no_expiry: number };
  items: ExpiryAlertItem[];
}

/** SA has no tenant of its own: it names the viewed tenant with ?tenant_id (ignored for other roles). */
export function fetchLots(warehouseId: string, includeDepleted: boolean, tenantId?: string): Promise<LotApi[]> {
  const q = new URLSearchParams({ limit: "1000" });
  if (tenantId) q.set("tenant_id", tenantId);
  if (includeDepleted) q.set("include_depleted", "true");
  if (warehouseId) q.set("warehouse_id", warehouseId);
  return api.get<LotApi[]>(`/api/v1/inventory/lots?${q.toString()}`);
}

export function fetchExpiryAlerts(warehouseId: string, tenantId?: string): Promise<ExpiryAlertsApi> {
  const q = new URLSearchParams();
  if (tenantId) q.set("tenant_id", tenantId);
  if (warehouseId) q.set("warehouse_id", warehouseId);
  const qs = q.toString();
  return api.get<ExpiryAlertsApi>(`/api/v1/inventory/lots/expiry-alerts${qs ? `?${qs}` : ""}`);
}

/* ── GET / PUT /api/v1/inventory/lots/expiry-settings ───────────────────── */
export interface ExpirySettingsApi {
  near_expiry_days: number;
}

export const NEAR_EXPIRY_MIN_DAYS = 1;
export const NEAR_EXPIRY_MAX_DAYS = 365;

function tenantQuery(tenantId?: string): string {
  return tenantId ? `?${new URLSearchParams({ tenant_id: tenantId }).toString()}` : "";
}

export function fetchExpirySettings(tenantId?: string): Promise<ExpirySettingsApi> {
  return api.get<ExpirySettingsApi>(`/api/v1/inventory/lots/expiry-settings${tenantQuery(tenantId)}`);
}

export function updateExpirySettings(days: number, tenantId?: string): Promise<ExpirySettingsApi> {
  return api.put<ExpirySettingsApi>(
    `/api/v1/inventory/lots/expiry-settings${tenantQuery(tenantId)}`,
    { near_expiry_days: days },
  );
}

/* ── GET /api/v1/inventory/lots/overrides[/summary] ──────────────────────── */
export type OverrideStrategy = "FEFO" | "FIFO" | "LIFO";

export interface OverrideLotApi {
  lot_id: string;
  lot_number: string | null;
  quantity: string | number;
}

export interface OverrideRowApi {
  id: string;
  created_at: string;
  overridden_by: string | null;
  product: { id: string; name: string; sku: string };
  warehouse: { id: string; name: string | null };
  strategy: string;
  movement_type: string;
  reference_id: string | null;
  requested_qty: string | number;
  suggested: OverrideLotApi[];
  chosen: OverrideLotApi[];
  reason: string | null;
}

export interface OverrideLogApi {
  total: number;
  rows: OverrideRowApi[];
}

export interface ComplianceCountsApi {
  decisions: number;
  overridden: number;
  compliance_rate: number | null;
}

export interface OverrideSummaryApi {
  date_from: string;
  date_to: string;
  overall: ComplianceCountsApi;
  fefo: ComplianceCountsApi;
  by_movement: Record<string, ComplianceCountsApi>;
}

export interface OverrideParams {
  dateFrom: string;
  dateTo: string;
  warehouseId: string;
  productId?: string;
  strategy?: OverrideStrategy | "";
  limit?: number;
  offset?: number;
}

function overrideQuery(p: OverrideParams, withListFilters: boolean, tenantId?: string): string {
  const q = new URLSearchParams();
  if (tenantId) q.set("tenant_id", tenantId);
  if (p.dateFrom) q.set("date_from", p.dateFrom);
  if (p.dateTo) q.set("date_to", p.dateTo);
  if (p.warehouseId) q.set("warehouse_id", p.warehouseId);
  if (withListFilters) {
    if (p.productId) q.set("product_id", p.productId);
    if (p.strategy) q.set("strategy", p.strategy);
    q.set("limit", String(p.limit ?? 50));
    q.set("offset", String(p.offset ?? 0));
  }
  const qs = q.toString();
  return qs ? `?${qs}` : "";
}

export function fetchOverrides(p: OverrideParams, tenantId?: string): Promise<OverrideLogApi> {
  return api.get<OverrideLogApi>(`/api/v1/inventory/lots/overrides${overrideQuery(p, true, tenantId)}`);
}

export function fetchOverrideSummary(p: OverrideParams, tenantId?: string): Promise<OverrideSummaryApi> {
  return api.get<OverrideSummaryApi>(`/api/v1/inventory/lots/overrides/summary${overrideQuery(p, false, tenantId)}`);
}

/** HTTP status carried by an ApiError-shaped throw, if any. */
export function errStatus(err: unknown): number | undefined {
  return (err as { status?: number } | null | undefined)?.status;
}

/** "YYYY-MM-DD" → local calendar date (no UTC shift); ISO datetimes → local date. */
export function formatLotDate(iso: string | null): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
  return d.toLocaleDateString();
}

/** "in N days" / "expires today" / "expired N days ago" / "No expiry set". */
export function expiryRelative(days: number | null): string {
  if (days === null) return t("lots.no_expiry");
  if (days < 0) {
    return days === -1
      ? t("lots.expiry_ago_one_day")
      : t("lots.expiry_ago_days").replace("{n}", String(-days));
  }
  if (days === 0) return t("lots.expiry_today");
  return days === 1 ? t("lots.expiry_in_one_day") : t("lots.expiry_in_days").replace("{n}", String(days));
}

const EXPIRY_ERROR_CODES = new Set([
  "LOT_NOT_FOUND", "LOT_EXPIRY_ALREADY_SET", "EXPIRY_TRACKING_OFF",
  "EXPIRY_IN_PAST", "FEATURE_NOT_ENABLED",
]);

/** Translated message for a failed set-expiry call; never a raw code or backend English. */
export function expiryErrorMessage(err: unknown): string {
  const code = (err as { code?: string } | null | undefined)?.code ?? "";
  if (EXPIRY_ERROR_CODES.has(code)) return t(`errors.${code}`);
  if (errStatus(err) === 403) return t("errors.RBAC_DENIED");
  return t("errors.INTERNAL_ERROR");
}
