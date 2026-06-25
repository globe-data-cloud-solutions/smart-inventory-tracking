"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession } from "@/lib/demo-auth";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import {
  DEMO_TENANTS,
  getLowStockProducts,
  getTotalStock,
  type DemoProduct,
} from "@/lib/demo-data";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";

const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;

// ── API types ──────────────────────────────────────────────────────────────────

interface ApiStockRow {
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  warehouse_type: string | null;
  current_stock: number;
}

interface ApiAlertRow {
  product_id: string;
  warehouse_id: string;
  warehouse_name: string;
  current_stock: number;
  reorder_point: number;
}

interface ApiTransferLine {
  product_id: string;
  product_name: string;
  sku: string;
  quantity: string;
}

interface ApiTransferRow {
  transfer_id: string;
  transfer_type: string;
  status: string;
  from_warehouse_name: string;
  to_warehouse_name: string;
  created_at: string;
  lines: ApiTransferLine[];
}

// ── Summary card ────────────────────────────────────────────────────────────────
function SummaryCard({ title, subtitle, rows, accentColor }: {
  title: string;
  subtitle: string;
  rows: { label: string; value: string | number; warn?: boolean }[];
  accentColor: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded overflow-hidden mb-6">
      {/* brand accent strip — accentColor is tenant-specific, must be dynamic */}
      <div className="h-1" style={{ background: accentColor }} />
      <div className="px-6 py-4 bg-[#0f2d1f] flex items-center justify-between">
        <div>
          <p className="font-bold text-base text-white m-0">{title}</p>
          <p className="text-xs text-emerald-300 mt-0.5">{subtitle}</p>
        </div>
        <div
          className="h-1.5 w-[28%] rounded"
          style={{ background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)" }}
        />
      </div>
      {/* stat columns — count drives cols, must be dynamic */}
      <div
        className="grid"
        style={{ gridTemplateColumns: `repeat(${rows.length},1fr)` }}
      >
        {rows.map((r, i) => (
          <div
            key={i}
            className={[
              "px-6 py-5 text-center",
              i < rows.length - 1 ? "border-r border-gray-100" : "",
              r.warn ? "bg-red-50" : "bg-white",
            ].join(" ")}
          >
            <p className={`text-3xl font-extrabold m-0 ${r.warn ? "text-red-600" : "text-eth-forest"}`}>
              {typeof r.value === "number" ? r.value.toLocaleString() : r.value}
            </p>
            <p className="text-xs text-gray-500 mt-1 font-medium">{r.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Inventory table (demo mode only) ──────────────────────────────────────────
function InventoryTable({ products, getQty, accentColor, title, subtitle }: {
  products: DemoProduct[];
  getQty: (p: DemoProduct) => number;
  accentColor: string;
  title: string;
  subtitle: string;
}) {
  const categories = Array.from(new Set(products.map((p) => p.category)));
  return (
    <div className="flex flex-col gap-5">
      {categories.map((cat) => {
        const items = products.filter((p) => p.category === cat);
        const total = items.reduce((a, p) => a + getQty(p), 0);
        return (
          <div key={cat} className="bg-white border border-gray-200 rounded overflow-hidden">
            <div className="h-[3px]" style={{ background: accentColor }} />
            <div className="px-5 py-3 bg-gray-50 border-b-2 border-gray-200 flex items-center justify-between">
              <span className="text-sm font-bold text-gray-800">
                {title}{" "}
                <span className="text-gray-400 font-normal">· {subtitle} · {cat}</span>
              </span>
              <span className="text-xs font-bold text-gray-500 bg-gray-200 px-2 py-0.5 rounded">
                {items.length} {t("table.skus")}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    {[
                      { key: "table.sku",           align: "text-left"  },
                      { key: "table.product",        align: "text-left"  },
                      { key: "table.stock",          align: "text-right" },
                      { key: "table.reorder_point",  align: "text-right" },
                      { key: "table.status",         align: "text-left"  },
                    ].map((h) => (
                      <th
                        key={h.key}
                        className={`px-4 py-2.5 ${h.align} text-xs font-bold text-gray-500 uppercase tracking-wide`}
                      >
                        {t(h.key)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((p, idx) => {
                    const qty = getQty(p);
                    const isLow = qty < p.reorderPoint;
                    return (
                      <tr
                        key={p.id}
                        className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}
                      >
                        <td className="px-4 py-2.5 font-mono text-xs text-gray-400">{p.sku}</td>
                        <td className="px-4 py-2.5 font-semibold text-gray-800">{p.name}</td>
                        <td className="px-4 py-2.5 text-right font-bold text-gray-900">{formatQty(qty)}</td>
                        <td className="px-4 py-2.5 text-right text-gray-400">{formatQty(p.reorderPoint)}</td>
                        <td className="px-4 py-2.5">
                          <span
                            className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded border ${
                              isLow
                                ? "bg-red-50 text-red-600 border-red-200"
                                : "bg-green-50 text-emerald-600 border-emerald-200"
                            }`}
                          >
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${isLow ? "bg-red-600" : "bg-emerald-600"}`}
                            />
                            {isLow ? t("alerts.low_stock") : t("dashboard.in_stock")}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="bg-gray-100 border-t-2 border-gray-200">
                    <td colSpan={2} className="px-4 py-2.5 text-xs font-semibold text-gray-500">
                      {items.length} {t("table.products")}
                    </td>
                    <td className="px-4 py-2.5 text-right font-extrabold text-eth-forest text-sm">
                      {formatQty(total)}
                    </td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const TYPE_CLASS: Record<string, string> = {
  MWH:    "bg-amber-100 text-amber-800",
  RWH:    "bg-blue-100  text-blue-800",
  WH:     "bg-gray-100  text-gray-700",
  SUB_WH: "bg-violet-100 text-violet-800",
};

const STATUS_CLASS: Record<string, string> = {
  COMPLETED:        "bg-green-50 text-emerald-700 border-emerald-200",
  IN_TRANSIT:       "bg-blue-50 text-blue-700 border-blue-200",
  APPROVED:         "bg-indigo-50 text-indigo-700 border-indigo-200",
  PENDING_APPROVAL: "bg-amber-50 text-amber-700 border-amber-200",
  DRAFT:            "bg-gray-100 text-gray-600 border-gray-300",
  CANCELLED:        "bg-red-50 text-red-600 border-red-200",
  REJECTED:         "bg-red-50 text-red-600 border-red-200",
};

// ── Main page ──────────────────────────────────────────────────────────────────
export default function OrgDashboard() {
  const { org } = useParams() as { org: string };
  const user = getSession();

  // ── Hooks (called unconditionally, disabled for SA/demo modes) ─────────────
  const enabled = isGatewayMode && org !== SA_ORG_SLUG;

  const { data: stockData = [] } = useQuery<ApiStockRow[]>({
    queryKey: ["dashboard-stock", org],
    queryFn: () => api.get<ApiStockRow[]>("/api/v1/inventory/analytics/stock"),
    enabled,
    staleTime: 0,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });

  const { data: alertsData = [] } = useQuery<ApiAlertRow[]>({
    queryKey: ["dashboard-alerts", org],
    queryFn: () => api.get<ApiAlertRow[]>("/api/v1/inventory/analytics/alerts"),
    enabled,
    staleTime: 0,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });

  const { data: recentTransfers = [] } = useQuery<ApiTransferRow[]>({
    queryKey: ["dashboard-transfers", org],
    queryFn: () => api.get<ApiTransferRow[]>("/api/v1/inventory/transfers/"),
    enabled,
    staleTime: 0,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });

  const tenantId = user?.tenantId ?? "";
  const { data: apiTenantData } = useQuery<{ id: string; name: string; logo_url?: string | null; banner_url?: string | null }>({
    queryKey: ["tenant-branding", tenantId],
    queryFn: () => api.get(`/api/v1/tenants/${tenantId}`),
    enabled: isGatewayMode && !!tenantId && org !== SA_ORG_SLUG,
    staleTime: 120_000,
  });

  interface ApiTenantRow {
    id: string;
    name: string;
    slug: string | null;
    organisation_type: string | null;
    status: string;
    is_active: boolean;
  }
  const { data: apiTenantList } = useQuery<ApiTenantRow[]>({
    queryKey: ["tenants-list"],
    queryFn: () => api.get<ApiTenantRow[]>("/api/v1/tenants/"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 0,
    refetchOnMount: true,
  });

  // ── SA tenant management action state (hooks must run unconditionally) ────
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionError, setActionError]     = useState<string | null>(null);
  const [confirmModal, setConfirmModal]   = useState<{
    tenantId: string; tenantName: string; action: "suspend" | "reactivate" | "deactivate";
  } | null>(null);
  const qc = useQueryClient();

  async function handleTenantAction(tenantId: string, action: "suspend" | "reactivate" | "deactivate") {
    setActionLoading(tenantId + action);
    setActionError(null);
    try {
      await api.patch(`/api/v1/tenants/${tenantId}/${action}`, {});
      void qc.invalidateQueries({ queryKey: ["tenants-list"] });
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setActionLoading(null);
      setConfirmModal(null);
    }
  }

  if (!user) return null;

  // ── SA home (/admin/dashboard) ─────────────────────────────────────────────
  if (org === SA_ORG_SLUG) {
    // Gateway mode: show real API tenants
    if (isGatewayMode) {
      const tenantCount = apiTenantList?.length ?? 0;

      const STATUS_BADGE: Record<string, string> = {
        ACTIVE:      "bg-emerald-100 text-emerald-800",
        SUSPENDED:   "bg-amber-100 text-amber-800",
        DEACTIVATED: "bg-red-100 text-red-700",
      };
      const STATUS_LABEL_KEY: Record<string, string> = {
        ACTIVE:      "sa.tenant_status_active",
        SUSPENDED:   "sa.tenant_status_suspended",
        DEACTIVATED: "sa.tenant_status_deactivated",
      };
      const CONFIRM_BODY_KEY: Record<"suspend" | "reactivate" | "deactivate", string> = {
        suspend:    "sa.confirm_suspend",
        reactivate: "sa.confirm_reactivate",
        deactivate: "sa.confirm_deactivate",
      };

      return (
        <div className="p-8">
          <SummaryCard
            title={t("dashboard.platform_overview")}
            subtitle={t("dashboard.sa_subtitle")}
            accentColor="#FCDD09"
            rows={[
              { label: t("dashboard.stat_tenants"), value: tenantCount },
              { label: t("dashboard.stat_users"),   value: "—" },
              { label: t("table.skus"),             value: "—" },
              { label: t("dashboard.stat_units"),   value: "—" },
            ]}
          />
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-bold text-[#0f2d1f] m-0">{t("dashboard.tenants_heading")}</h3>
            <Link
              href="/onboard"
              className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded no-underline"
            >
              {t("wizard.onboard_btn")}
            </Link>
          </div>
          {(!apiTenantList || apiTenantList.length === 0) && (
            <p className="text-gray-400 text-sm">{t("common.no_data")}</p>
          )}
          {actionError && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-4 py-2 mb-4">
              {actionError}
            </p>
          )}
          <div className="bg-white border border-gray-200 rounded overflow-hidden">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {["dashboard.tenant_name", "dashboard.tenant_type", "table.status", "table.actions"].map((key) => (
                    <th
                      key={key}
                      className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide"
                    >
                      {t(key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(apiTenantList ?? []).map((ten, idx) => {
                  const slug   = ten.slug ?? ten.id;
                  const status = ten.status || "ACTIVE";
                  const badgeClass = STATUS_BADGE[status] ?? "bg-gray-100 text-gray-700";
                  const labelKey   = STATUS_LABEL_KEY[status];
                  return (
                    <tr key={ten.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                      <td className="px-4 py-2.5 font-semibold text-gray-800">
                        <Link href={`/${slug}/dashboard`} className="text-eth-forest hover:underline">
                          {ten.name}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">{ten.organisation_type ?? "—"}</td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs font-bold px-2.5 py-0.5 rounded ${badgeClass}`}>
                          {labelKey ? t(labelKey) : status}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-3">
                          {status === "ACTIVE" && (
                            <>
                              <button
                                type="button"
                                disabled={actionLoading === ten.id + "suspend"}
                                onClick={() => setConfirmModal({ tenantId: ten.id, tenantName: ten.name, action: "suspend" })}
                                className="text-xs font-bold text-amber-700 hover:underline disabled:opacity-50"
                              >
                                {actionLoading === ten.id + "suspend" ? "…" : t("sa.action_suspend")}
                              </button>
                              <button
                                type="button"
                                disabled={actionLoading === ten.id + "deactivate"}
                                onClick={() => setConfirmModal({ tenantId: ten.id, tenantName: ten.name, action: "deactivate" })}
                                className="text-xs font-bold text-red-600 hover:underline disabled:opacity-50"
                              >
                                {actionLoading === ten.id + "deactivate" ? "…" : t("sa.action_deactivate")}
                              </button>
                            </>
                          )}
                          {status === "SUSPENDED" && (
                            <>
                              <button
                                type="button"
                                disabled={actionLoading === ten.id + "reactivate"}
                                onClick={() => setConfirmModal({ tenantId: ten.id, tenantName: ten.name, action: "reactivate" })}
                                className="text-xs font-bold text-emerald-700 hover:underline disabled:opacity-50"
                              >
                                {actionLoading === ten.id + "reactivate" ? "…" : t("sa.action_reactivate")}
                              </button>
                              <button
                                type="button"
                                disabled={actionLoading === ten.id + "deactivate"}
                                onClick={() => setConfirmModal({ tenantId: ten.id, tenantName: ten.name, action: "deactivate" })}
                                className="text-xs font-bold text-red-600 hover:underline disabled:opacity-50"
                              >
                                {actionLoading === ten.id + "deactivate" ? "…" : t("sa.action_deactivate")}
                              </button>
                            </>
                          )}
                          {status === "DEACTIVATED" && (
                            <button
                              type="button"
                              disabled={actionLoading === ten.id + "reactivate"}
                              onClick={() => setConfirmModal({ tenantId: ten.id, tenantName: ten.name, action: "reactivate" })}
                              className="text-xs font-bold text-emerald-700 hover:underline disabled:opacity-50"
                            >
                              {actionLoading === ten.id + "reactivate" ? "…" : t("sa.action_reactivate")}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {confirmModal && (
            <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
              <div className="bg-white rounded-lg shadow-lg w-full max-w-sm p-6">
                <h4 className="text-base font-bold text-gray-900 m-0 mb-3">
                  {t("common.confirm")} {confirmModal.action.charAt(0).toUpperCase() + confirmModal.action.slice(1)}
                </h4>
                <p className="text-sm text-gray-600 mb-6">
                  {t(CONFIRM_BODY_KEY[confirmModal.action]).replace("{name}", confirmModal.tenantName)}
                </p>
                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => setConfirmModal(null)}
                    className="px-4 py-2 text-sm font-bold text-gray-600 rounded hover:bg-gray-100"
                  >
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleTenantAction(confirmModal.tenantId, confirmModal.action)}
                    className={`px-4 py-2 text-sm font-bold text-white rounded ${
                      confirmModal.action === "deactivate" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"
                    }`}
                  >
                    {actionLoading === confirmModal.tenantId + confirmModal.action ? "…" : t("common.confirm")}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      );
    }

    // Demo mode: hardcoded tenant data with branding
    const totalLoc   = DEMO_TENANTS.reduce((a, ten) => a + ten.warehouses.length, 0);
    const totalSKUs  = DEMO_TENANTS.reduce((a, ten) => a + ten.products.length, 0);
    const totalUnits = DEMO_TENANTS.reduce(
      (a, ten) => a + ten.products.reduce((b, p) => b + getTotalStock(p), 0), 0
    );
    return (
      <div className="p-8">
        <SummaryCard
          title={t("dashboard.platform_overview")}
          subtitle={t("dashboard.sa_subtitle")}
          accentColor="#FCDD09"
          rows={[
            { label: t("dashboard.stat_tenants"),    value: DEMO_TENANTS.length },
            { label: t("dashboard.stat_locations"),  value: totalLoc },
            { label: t("table.skus"),                value: totalSKUs },
            { label: t("dashboard.stat_units"),      value: totalUnits },
            { label: t("dashboard.stat_users"),      value: DEMO_TENANTS.reduce((a, ten) => a + ten.users.length, 0) + 1 },
          ]}
        />
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-[#0f2d1f] m-0">{t("dashboard.tenants_heading")}</h3>
          <Link
            href="/onboard"
            className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded no-underline"
          >
            {t("wizard.onboard_btn")}
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-6">
          {DEMO_TENANTS.map((ten) => {
            const low   = getLowStockProducts(ten);
            const units = ten.products.reduce((a, p) => a + getTotalStock(p), 0);
            return (
              <Link key={ten.id} href={`/${ten.slug}/dashboard`} className="no-underline">
                <div className="bg-white border border-gray-200 rounded overflow-hidden">
                  {/* tenant header — color is per-tenant, must be dynamic */}
                  <div
                    className="px-5 py-4 flex items-center gap-3"
                    style={{ background: ten.color }}
                  >
                    <span className="text-3xl">{ten.logo}</span>
                    <div>
                      <p className="font-bold text-base text-white m-0">{ten.name}</p>
                      <p className="text-xs text-white/75 m-0">{ten.industry}</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-4 p-3.5 gap-2 text-center">
                    {[
                      { l: t("dashboard.stat_locations"), v: ten.warehouses.length },
                      { l: t("table.skus"),               v: ten.products.length },
                      { l: t("dashboard.stat_units"),     v: formatQty(units) },
                      { l: t("alerts.low_stock"),         v: low.length, w: low.length > 0 },
                    ].map((s) => (
                      <div key={s.l}>
                        <p className={`text-xl font-extrabold m-0 ${s.w ? "text-red-600" : "text-gray-900"}`}>{s.v}</p>
                        <p className="text-xs text-gray-400 m-0">{s.l}</p>
                      </div>
                    ))}
                  </div>
                  <div className="px-5 py-2.5 border-t border-gray-100 bg-gray-50">
                    {/* tenant slug link — color is per-tenant */}
                    <span className="text-xs font-bold" style={{ color: ten.color }}>
                      /{ten.slug}/dashboard →
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Tenant lookup — demo branding only. Real tenants use fallback values. ─
  const tenant     = DEMO_TENANTS.find((ten) => ten.slug === org);
  const tenantName = apiTenantData?.name ?? tenant?.name ?? org;
  const tenantColor = tenant?.color   ?? "#1B4332";
  const tenantIndustry = tenant?.industry ?? "";

  // ── Gateway mode — real API data ───────────────────────────────────────────
  if (isGatewayMode) {
    const whStock  = user.warehouseId
      ? stockData.filter((r) => r.warehouse_id === user.warehouseId)
      : stockData;

    const whAlerts = user.warehouseId
      ? alertsData.filter((r) => r.warehouse_id === user.warehouseId)
      : alertsData;

    const totalUnits   = whStock.reduce((s, r) => s + Number(r.current_stock), 0);
    const skusWithStock = new Set(
      whStock.filter((r) => Number(r.current_stock) > 0).map((r) => r.product_id)
    ).size;
    const lowStockCount = new Set(whAlerts.map((r) => r.product_id)).size;
    const inStockCount  = Math.max(0, skusWithStock - lowStockCount);

    // Warehouse name for WM view
    const myWarehouseName = user.warehouseId
      ? (whStock[0]?.warehouse_name ?? t("dashboard.my_warehouse"))
      : null;

    // Per-warehouse breakdown for TA/NM view
    const warehouseMap = new Map<string, {
      id: string; name: string; type: string;
      totalUnits: number; skuCount: number; lowCount: number;
    }>();
    if (!user.warehouseId) {
      for (const row of stockData) {
        const entry = warehouseMap.get(row.warehouse_id) ?? {
          id: row.warehouse_id,
          name: row.warehouse_name,
          type: row.warehouse_type ?? "WH",
          totalUnits: 0,
          skuCount: 0,
          lowCount: 0,
        };
        entry.totalUnits += Number(row.current_stock);
        if (Number(row.current_stock) > 0) entry.skuCount++;
        warehouseMap.set(row.warehouse_id, entry);
      }
      for (const alert of alertsData) {
        const wh = warehouseMap.get(alert.warehouse_id);
        if (wh) wh.lowCount++;
      }
    }
    const warehouseRows = Array.from(warehouseMap.values());

    const cardTitle    = myWarehouseName ?? tenantName;
    const cardSubtitle = myWarehouseName
      ? `${user.role} access`
      : `${tenantIndustry ? tenantIndustry + " · " : ""}${user.role === "SA" ? t("dashboard.sa_viewing") : t("dashboard.tenant_admin")}`;

    const bannerUrl = apiTenantData?.banner_url ?? null;
    return (
      <div>
        {bannerUrl && (
          <img
            src={bannerUrl}
            alt=""
            className="w-full object-cover"
            style={{ maxHeight: "180px" }}
          />
        )}
      <div className="p-8">
        <SummaryCard
          title={cardTitle}
          subtitle={cardSubtitle}
          accentColor={tenantColor}
          rows={[
            { label: t("dashboard.stat_units"),           value: totalUnits },
            { label: t("dashboard.stat_skus_with_stock"), value: skusWithStock },
            { label: t("dashboard.in_stock"),             value: inStockCount },
            { label: t("alerts.low_stock"),               value: lowStockCount, warn: lowStockCount > 0 },
          ]}
        />

        {/* Warehouse breakdown — TA/NM only */}
        {warehouseRows.length > 0 && (
          <div className="bg-white border border-gray-200 rounded overflow-hidden mb-6">
            <div className="h-[3px]" style={{ background: tenantColor }} />
            <div className="px-5 py-3 bg-gray-50 border-b-2 border-gray-200">
              <span className="text-sm font-bold text-gray-800">{t("dashboard.inventory_by_location")}</span>
            </div>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  {["table.location","table.type","table.skus","table.total_units","alerts.low_stock"].map((key) => (
                    <th
                      key={key}
                      className="px-4 py-2.5 bg-gray-50 text-left text-xs font-bold text-gray-500 uppercase tracking-wide border-b border-gray-200"
                    >
                      {t(key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {warehouseRows.map((wh, idx) => {
                  const typeClass = TYPE_CLASS[wh.type] ?? "bg-gray-100 text-gray-500";
                  return (
                    <tr
                      key={wh.id}
                      className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}
                    >
                      <td className="px-4 py-2.5 font-semibold text-gray-800">{wh.name}</td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                          {wh.type}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-700">{wh.skuCount}</td>
                      <td className="px-4 py-2.5 font-bold text-gray-900">{formatQty(wh.totalUnits)}</td>
                      <td className="px-4 py-2.5">
                        {wh.lowCount > 0 ? (
                          <span className="text-xs font-bold bg-red-50 text-red-600 border border-red-200 px-2 py-0.5 rounded">
                            {wh.lowCount} {t("dashboard.low_badge")}
                          </span>
                        ) : (
                          <span className="text-xs font-bold bg-green-50 text-emerald-600 border border-emerald-200 px-2 py-0.5 rounded">
                            {t("dashboard.ok_badge")}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Recent transfers */}
        {recentTransfers.length > 0 && (
          <div className="bg-white border border-gray-200 rounded overflow-hidden">
            <div className="h-[3px]" style={{ background: tenantColor }} />
            <div className="px-5 py-3 bg-gray-50 border-b-2 border-gray-200">
              <span className="text-sm font-bold text-gray-800">{t("dashboard.recent_transfers")}</span>
            </div>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {["table.date","transfers.type","transfers.route","table.product","table.status"].map((key) => (
                    <th key={key} className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">
                      {t(key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recentTransfers.slice(0, 10).map((tr, idx) => {
                  const statusClass = STATUS_CLASS[tr.status] ?? "bg-gray-100 text-gray-600 border-gray-300";
                  const productSummary = tr.lines.length > 0
                    ? tr.lines[0]!.product_name + (tr.lines.length > 1 ? ` +${tr.lines.length - 1}` : "")
                    : "—";
                  return (
                    <tr key={tr.transfer_id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                      <td className="px-4 py-2.5 text-gray-500 text-xs">
                        {new Date(tr.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="text-xs font-bold bg-gray-100 text-gray-700 px-2 py-0.5 rounded">
                          {tr.transfer_type}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-700 text-xs">
                        {tr.from_warehouse_name} → {tr.to_warehouse_name}
                      </td>
                      <td className="px-4 py-2.5 text-gray-700">{productSummary}</td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded border ${statusClass}`}>
                          {tr.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      </div>
    );
  }

  // ── Demo mode ──────────────────────────────────────────────────────────────
  if (!tenant) {
    return (
      <p className="p-8 text-gray-500">
        {t("common.no_data")}: {tenantName}
      </p>
    );
  }

  const lowStock   = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);

  // WM/NM — single warehouse view
  if (user.warehouseId) {
    const wh         = tenant.warehouses.find((w) => w.id === user.warehouseId);
    const myProducts = tenant.products.filter((p) => (p.stock[user.warehouseId!] ?? 0) > 0);
    const myUnits    = myProducts.reduce((a, p) => a + (p.stock[user.warehouseId!] ?? 0), 0);
    const myLow      = myProducts.filter((p) => (p.stock[user.warehouseId!] ?? 0) < p.reorderPoint);
    return (
      <div className="p-8">
        <SummaryCard
          title={wh?.name ?? t("dashboard.my_warehouse")}
          subtitle={`${wh?.location ?? ""} · ${user.role} access`}
          accentColor={tenant.color ?? "#059669"}
          rows={[
            { label: t("dashboard.stat_units"),           value: myUnits },
            { label: t("dashboard.stat_skus_with_stock"), value: myProducts.length },
            { label: t("dashboard.in_stock"),             value: myProducts.length - myLow.length },
            { label: t("alerts.low_stock"),               value: myLow.length, warn: myLow.length > 0 },
          ]}
        />
        <InventoryTable
          products={myProducts}
          getQty={(p) => p.stock[user.warehouseId!] ?? 0}
          accentColor={tenant.color ?? "#059669"}
          title={wh?.name ?? t("dashboard.my_warehouse")}
          subtitle={user.role}
        />
      </div>
    );
  }

  // TA / SA viewing a tenant
  return (
    <div className="p-8">
      <SummaryCard
        title={tenant.name}
        subtitle={`${tenant.industry} · ${user.role === "SA" ? t("dashboard.sa_viewing") : t("dashboard.tenant_admin")}`}
        accentColor={tenant.color ?? "#059669"}
        rows={[
          { label: t("dashboard.stat_locations"), value: tenant.warehouses.length },
          { label: t("table.skus"),               value: tenant.products.length },
          { label: t("dashboard.stat_units"),     value: totalUnits },
          { label: t("alerts.low_stock"),         value: lowStock.length, warn: lowStock.length > 0 },
        ]}
      />

      {/* Warehouse summary */}
      <div className="bg-white border border-gray-200 rounded overflow-hidden mb-6">
        <div className="h-[3px]" style={{ background: tenant.color ?? "#059669" }} />
        <div className="px-5 py-3 bg-gray-50 border-b-2 border-gray-200">
          <span className="text-sm font-bold text-gray-800">{t("dashboard.inventory_by_location")}</span>
        </div>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              {[
                "table.location",
                "table.type",
                "table.skus",
                "table.total_units",
                "alerts.low_stock",
              ].map((key) => (
                <th
                  key={key}
                  className="px-4 py-2.5 bg-gray-50 text-left text-xs font-bold text-gray-500 uppercase tracking-wide border-b border-gray-200"
                >
                  {t(key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tenant.warehouses.map((w, idx) => {
              const whUnits = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
              const whSKUs  = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
              const whLow   = tenant.products.filter(
                (p) => (p.stock[w.id] ?? 0) > 0 && (p.stock[w.id] ?? 0) < p.reorderPoint
              ).length;
              const typeClasses: Record<string, string> = {
                MWH:    "bg-amber-100 text-amber-800",
                RWH:    "bg-blue-100 text-blue-800",
                WH:     "bg-gray-100 text-gray-700",
                SUB_WH: "bg-violet-100 text-violet-800",
              };
              const typeClass = typeClasses[w.type] ?? "bg-gray-100 text-gray-500";
              return (
                <tr
                  key={w.id}
                  className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}
                >
                  <td className="px-4 py-2.5 font-semibold text-gray-800">
                    {w.parentId && (
                      <span className="text-gray-300 mr-1">↳</span>
                    )}
                    {w.name}
                    <p className="m-0 text-xs text-gray-400 font-normal">{w.location}</p>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                      {t(`warehouse_type.${w.type}`)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">{whSKUs}</td>
                  <td className="px-4 py-2.5 font-bold text-gray-900">{formatQty(whUnits)}</td>
                  <td className="px-4 py-2.5">
                    {whLow > 0 ? (
                      <span className="text-xs font-bold bg-red-50 text-red-600 border border-red-200 px-2 py-0.5 rounded">
                        {whLow} {t("dashboard.low_badge")}
                      </span>
                    ) : (
                      <span className="text-xs font-bold bg-green-50 text-emerald-600 border border-emerald-200 px-2 py-0.5 rounded">
                        {t("dashboard.ok_badge")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <InventoryTable
        products={tenant.products}
        getQty={getTotalStock}
        accentColor={tenant.color ?? "#059669"}
        title={`${tenant.name} — ${t("dashboard.full_inventory")}`}
        subtitle={t("dashboard.all_locations")}
      />
    </div>
  );
}
