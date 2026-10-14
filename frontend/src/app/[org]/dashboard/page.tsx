"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession } from "@/lib/demo-auth";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import {
  DEMO_TENANTS,
  getLowStockProducts,
  getTotalStock,
  type DemoProduct,
} from "@/lib/demo-data";
import { api } from "@/lib/api";
import { t, getCurrentLocale } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import { useContactInfo } from "@/hooks/useContactInfo";
import { pickLocalized } from "@/lib/billing-types";
import { ContactModal } from "@/components/features/contact/ContactModal";
import { useFeatures } from "@/hooks/useFeatures";
import { fetchExpiryAlerts, type ExpiryAlertsApi } from "@/components/features/lots/lotsApi";

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

// Need help? card — TA dashboard only, hidden until platform contact details
// are configured (useContactInfo: demo mode always resolves to not-configured).
function NeedHelpCard() {
  const { contact } = useContactInfo();
  const locale = getCurrentLocale();
  const [contactOpen, setContactOpen] = useState(false);

  if (!contact?.configured) return null;

  const hours = pickLocalized(contact.hours, locale);

  return (
    <div className="bg-white border border-gray-200 rounded p-4 mb-6 flex items-center justify-between gap-4 flex-wrap">
      <div>
        <p className="font-bold text-sm text-gray-800 m-0">{t("dashboard.need_help_title")}</p>
        <p className="text-xs text-gray-500 mt-0.5">
          {[contact.support_email, contact.phone, hours].filter(Boolean).join(" · ")}
        </p>
      </div>
      <button
        type="button"
        onClick={() => setContactOpen(true)}
        className="text-xs font-bold text-[#0f2d1f] underline shrink-0 whitespace-nowrap"
      >
        {t("dashboard.need_help_all_contact")}
      </button>
      <ContactModal open={contactOpen} onClose={() => setContactOpen(false)} />
    </div>
  );
}

// ── Summary card ────────────────────────────────────────────────────────────────
function SummaryCard({ title, subtitle, rows, accentColor }: {
  title: string;
  subtitle: string;
  rows: { label: string; value: string | number; warn?: boolean; href?: string }[];
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
        {rows.map((r, i) => {
          const cellClass = [
            "px-6 py-5 text-center",
            i < rows.length - 1 ? "border-r border-gray-100" : "",
            r.warn ? "bg-red-50" : "bg-white",
          ].join(" ");
          const cell = (
            <>
              <p className={`text-3xl font-extrabold m-0 ${r.warn ? "text-red-600" : "text-eth-forest"}`}>
                {typeof r.value === "number" ? r.value.toLocaleString() : r.value}
              </p>
              <p className="text-xs text-gray-500 mt-1 font-medium">{r.label}</p>
            </>
          );
          return r.href ? (
            <Link key={i} href={r.href} className={`${cellClass} no-underline`}>{cell}</Link>
          ) : (
            <div key={i} className={cellClass}>{cell}</div>
          );
        })}
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
  const router = useRouter();
  const searchParams = useSearchParams();
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

  // Expiry rows next to low-stock (gateway mode, lot tracking on). A 403 (e.g. LM)
  // or any other failure leaves data undefined, so no expiry rows are shown.
  const { lotTracking } = useFeatures();
  const expiryWarehouseId = user?.warehouseId ?? "";
  const { data: expiryAlerts } = useQuery<ExpiryAlertsApi>({
    queryKey: ["dashboard-expiry-alerts", org, expiryWarehouseId],
    queryFn: () => fetchExpiryAlerts(expiryWarehouseId),
    enabled: enabled && lotTracking,
    retry: false,
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
    plan_tier?: string | null;
  }

  interface ApiRegistryContact {
    id: string;
    is_primary: boolean;
    full_name: string;
    position_title: string | null;
    email: string | null;
    phone: string | null;
    mobile: string | null;
  }

  interface ApiRegistryRow {
    id: string;
    name: string;
    slug: string | null;
    organisation_type: string | null;
    status: string;
    plan_tier:      string | null;
    sku_cap:        number | null;
    default_locale: string;
    contact_name:   string | null;
    contact_email:  string | null;
    contact_phone:  string | null;
    contract_start: string | null;
    contract_end:   string | null;
    notes:          string | null;
    user_count: number;
    node_count: number;
    created_at: string;
    address_line1:  string | null;
    address_line2:  string | null;
    city:           string | null;
    state_province: string | null;
    postal_code:    string | null;
    country:        string | null;
    contacts:      ApiRegistryContact[];
    ta_name:    string | null;
    ta_email:   string | null;
    ta_user_id: string | null;
    industry:      string | null;
    feature_flags: Record<string, boolean>;
    signup_source: string;
    subscription_status: string | null;
    billing_period: string | null;
    current_period_end: string | null;
    last_payment_status: string | null;
  }

  interface ApiActivityRow {
    id: string;
    tenant_id: string;
    actor_id: string;
    actor_email: string | null;
    action: string;
    old_value: string | null;
    new_value: string | null;
    note: string | null;
    created_at: string;
  }

  interface ContractsOverviewRow {
    tenant_id: string;
    name: string;
    slug: string | null;
    plan_tier: string | null;
    contract_end: string | null;
    days_left: number | null;
    stage: "EXPIRING" | "GRACE" | "READ_ONLY";
    open_request_id: string | null;
  }

  interface ContractsOverviewOut {
    tenants: ContractsOverviewRow[];
    counts: { EXPIRING: number; GRACE: number; READ_ONLY: number };
  }

  interface SARenewalRequestRow {
    id: string;
    tenant_id: string;
    tenant_name: string;
    tenant_slug: string | null;
    plan_tier: string | null;
    contract_end: string | null;
    requested_by: string;
    requested_by_email: string | null;
    message: string | null;
    request_type: "RENEWAL" | "UPGRADE";
    requested_tier: string | null;
    status: "OPEN" | "HANDLED" | "CANCELLED";
    handled_by: string | null;
    handled_note: string | null;
    handled_at: string | null;
    created_at: string;
  }

  const { data: apiTenantList } = useQuery<ApiTenantRow[]>({
    queryKey: ["tenants-list"],
    queryFn: () => api.get<ApiTenantRow[]>("/api/v1/tenants/"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 0,
    refetchOnMount: true,
  });

  // ── SA tenant management action state ─────────────────────────────────────
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const qc = useQueryClient();

  // Deep-link support: /admin/dashboard?tab=renewals (used by the SA nav badge).
  const tabParam = searchParams.get("tab");
  const SA_TABS = ["tenants", "registry", "admin", "renewals"] as const;
  const initialSaTab = (SA_TABS as readonly string[]).includes(tabParam ?? "")
    ? (tabParam as typeof SA_TABS[number])
    : "tenants";
  const [saTab, setSaTab] = useState<typeof SA_TABS[number]>(initialSaTab);
  const [activityTenantId, setActivityTenantId] = useState<string | null>(null);
  const [personnelModalRow, setPersonnelModalRow] = useState<ApiRegistryRow | null>(null);


  const { data: apiRegistryList, isLoading: registryLoading, isError: registryError } = useQuery<ApiRegistryRow[]>({
    queryKey: ["sa-registry"],
    queryFn: () => api.get<ApiRegistryRow[]>("/api/v1/tenants/sa/registry"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 0,
    refetchOnMount: true,
  });

  const { data: contractsOverview, isLoading: contractsOverviewLoading } = useQuery<ContractsOverviewOut>({
    queryKey: ["sa-contracts-overview"],
    queryFn: () => api.get<ContractsOverviewOut>("/api/v1/tenants/sa/contracts/overview"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 0,
    refetchOnMount: true,
  });

  const { data: openRenewalRequests, isLoading: openRenewalRequestsLoading } = useQuery<SARenewalRequestRow[]>({
    queryKey: ["sa-renewal-requests", "OPEN"],
    queryFn: () => api.get<SARenewalRequestRow[]>("/api/v1/tenants/sa/renewal-requests?status=OPEN"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 0,
    refetchOnMount: true,
  });

  // ── SA renewals tab action state ────────────────────────────────────────────
  const [renewalActionRow, setRenewalActionRow] = useState<{ id: string; type: "handle" | "cancel" } | null>(null);
  const [renewalNote, setRenewalNote] = useState("");
  const [renewalActionError, setRenewalActionError] = useState<string | null>(null);

  const handleRenewalMutation = useMutation({
    mutationFn: (vars: { id: string; status: "HANDLED" | "CANCELLED"; note?: string }) =>
      api.patch(`/api/v1/tenants/sa/renewal-requests/${vars.id}`, {
        status: vars.status,
        note: vars.note?.trim() || undefined,
      }),
    onSuccess: () => {
      setRenewalActionRow(null);
      setRenewalNote("");
      setRenewalActionError(null);
      void qc.invalidateQueries({ queryKey: ["sa-renewal-requests"] });
      void qc.invalidateQueries({ queryKey: ["sa-contracts-overview"] });
    },
    onError: (e: unknown) => setRenewalActionError(e instanceof Error ? e.message : t("common.error")),
  });

  function toggleRenewalAction(id: string, type: "handle" | "cancel") {
    setRenewalActionRow((cur) => (cur?.id === id && cur.type === type ? null : { id, type }));
    setRenewalNote("");
    setRenewalActionError(null);
  }

  const { data: activityLog, isLoading: activityLoading } = useQuery<ApiActivityRow[]>({
    queryKey: ["sa-activity", activityTenantId],
    queryFn: () => api.get<ApiActivityRow[]>(`/api/v1/tenants/sa/${activityTenantId}/activity`),
    enabled: isGatewayMode && !!activityTenantId,
    staleTime: 0,
  });

  if (!user) return null;

  // ── SA home (/admin/dashboard) ─────────────────────────────────────────────
  if (org === SA_ORG_SLUG) {
    // Gateway mode: show real API tenants
    if (isGatewayMode) {
      const tenantCount = apiRegistryList?.length ?? 0;

      const STATUS_BADGE: Record<string, string> = {
        ACTIVE:      "bg-emerald-100 text-emerald-800",
        SUSPENDED:   "bg-amber-100 text-amber-800",
        DEACTIVATED: "bg-red-100 text-red-700",
      };
      const PLAN_TIER_BADGE: Record<string, string> = {
        STARTER:    "bg-gray-100 text-gray-600",
        GROWTH:     "bg-blue-100 text-blue-700",
        ENTERPRISE: "bg-amber-100 text-amber-700",
      };
      const STATUS_LABEL_KEY: Record<string, string> = {
        ACTIVE:      "sa.tenant_status_active",
        SUSPENDED:   "sa.tenant_status_suspended",
        DEACTIVATED: "sa.tenant_status_deactivated",
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
          <div className="flex gap-0 mb-6 border-b border-gray-200">
            {SA_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setSaTab(tab)}
                className={[
                  "px-5 py-2.5 text-sm font-semibold border-b-2 -mb-px transition-colors",
                  saTab === tab
                    ? "border-[#0f2d1f] text-[#0f2d1f]"
                    : "border-transparent text-gray-500 hover:text-gray-700",
                ].join(" ")}
              >
                {t(`sa.tab_${tab}`)}
              </button>
            ))}
          </div>

          {saTab === "tenants" && (
            <>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-base font-bold text-[#0f2d1f] m-0">{t("dashboard.tenants_heading")}</h3>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/${org}/settings/plans`}
                    className="px-3 py-2 text-xs font-bold rounded bg-gray-100 text-gray-700 border border-gray-200 hover:bg-gray-200 transition-colors flex items-center gap-1.5 no-underline"
                  >
                    ⚙ {t("sa.nav_plans_pricing")}
                  </Link>
                  <Link
                    href="/onboard"
                    className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded no-underline"
                  >
                    {t("wizard.onboard_btn")}
                  </Link>
                </div>
              </div>
              {registryLoading && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
              {!registryLoading && (!apiRegistryList || apiRegistryList.length === 0) && (
                <p className="text-gray-400 text-sm">{t("common.no_data")}</p>
              )}
              {!registryLoading && apiRegistryList && apiRegistryList.length > 0 && (
                <div className="bg-white border border-gray-200 rounded overflow-x-auto">
                  <table className="w-full border-collapse text-sm min-w-[900px]">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        {[
                          "dashboard.tenant_name",
                          "dashboard.tenant_type",
                          "table.status",
                          "table.plan",
                          "sa.col_sku_cap",
                          "sa.col_users",
                          "sa.col_nodes",
                          "sa.col_created",
                          "sa.col_end_date",
                        ].map((key) => (
                          <th
                            key={key}
                            className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap"
                          >
                            {t(key)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {apiRegistryList.map((ten, idx) => {
                        const slug   = ten.slug ?? ten.id;
                        const status = ten.status || "ACTIVE";
                        const badgeClass = STATUS_BADGE[status] ?? "bg-gray-100 text-gray-700";
                        const labelKey   = STATUS_LABEL_KEY[status];
                        const isEndedSoon = ten.contract_end
                          ? new Date(ten.contract_end) <= new Date(Date.now() + 30 * 24 * 60 * 60 * 1000)
                          : false;
                        return (
                          <tr key={ten.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                            <td className="px-4 py-2.5 font-semibold text-gray-800 whitespace-nowrap">
                              <Link href={`/${slug}/dashboard`} className="text-eth-forest hover:underline">
                                {ten.name}
                              </Link>
                            </td>
                            <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{ten.organisation_type ?? "—"}</td>
                            <td className="px-4 py-2.5">
                              <span className={`text-xs font-bold px-2.5 py-0.5 rounded ${badgeClass}`}>
                                {labelKey ? t(labelKey) : status}
                              </span>
                            </td>
                            <td className="px-4 py-2.5">
                              <span className={`text-xs font-bold px-2.5 py-0.5 rounded ${PLAN_TIER_BADGE[ten.plan_tier ?? ""] ?? "bg-gray-100 text-gray-600"}`}>
                                {ten.plan_tier ?? "—"}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-center text-xs text-gray-600">
                              {ten.sku_cap != null ? ten.sku_cap.toLocaleString() : <span className="text-gray-400">∞</span>}
                            </td>
                            <td className="px-4 py-2.5 text-center text-gray-700">{ten.user_count}</td>
                            <td className="px-4 py-2.5 text-center text-gray-700">{ten.node_count}</td>
                            <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                              {new Date(ten.created_at).toLocaleDateString()}
                            </td>
                            <td className="px-4 py-2.5 text-xs whitespace-nowrap">
                              {ten.contract_end ? (
                                <span className={isEndedSoon ? "text-amber-700 font-semibold" : "text-gray-500"}>
                                  {ten.contract_end}
                                </span>
                              ) : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {saTab === "registry" && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-bold text-[#0f2d1f] m-0">{t("sa.registry_heading")}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{t("sa.registry_subtitle")}</p>
                </div>
              </div>
              {registryLoading && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
              {!registryLoading && (
                <div className="bg-white border border-gray-200 rounded overflow-x-auto">
                  <table className="w-full border-collapse text-sm min-w-[900px]">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        {[
                          "dashboard.tenant_name",
                          "sa.col_source",
                          "sa.col_subscription",
                          "sa.col_contact_name",
                          "sa.col_contact_email",
                          "sa.col_contact_phone",
                          "sa.col_personnel",
                          "sa.col_contract_from",
                          "sa.col_contract_to",
                          "sa.col_notes",
                          "table.actions",
                        ].map((key) => (
                          <th
                            key={key}
                            className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap"
                          >
                            {t(key)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {registryError && (
                        <tr>
                          <td colSpan={11} className="px-4 py-8 text-center text-sm text-red-500">
                            {t("common.error")}
                          </td>
                        </tr>
                      )}
                      {!registryError && (!apiRegistryList || apiRegistryList.length === 0) && (
                        <tr>
                          <td colSpan={11} className="px-4 py-8 text-center text-sm text-gray-400">
                            {t("common.no_data")}
                          </td>
                        </tr>
                      )}
                      {(apiRegistryList ?? []).map((row, idx) => {
                        const primary = row.contacts?.find((c) => c.is_primary) ?? null;
                        const totalContacts = (row.contacts ?? []).length;
                        const primaryName  = primary?.full_name  ?? row.contact_name  ?? null;
                        const primaryEmail = primary?.email      ?? row.contact_email ?? null;
                        const primaryPhone = primary?.phone ?? primary?.mobile ?? row.contact_phone ?? null;
                        return (
                          <tr key={row.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                            {/* Tenant Name + location */}
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <p className="font-semibold text-gray-800 m-0">{row.name}</p>
                              {(row.city || row.country) && (
                                <p className="text-[11px] text-gray-400 m-0">{[row.city, row.country].filter(Boolean).join(", ")}</p>
                              )}
                            </td>
                            {/* Source */}
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                                row.signup_source === "SELF_SIGNUP" ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"
                              }`}>
                                {row.signup_source === "SELF_SIGNUP" ? t("sa.source_self_signup") : t("sa.source_sa")}
                              </span>
                            </td>
                            {/* Subscription */}
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              {row.subscription_status ? (
                                <div>
                                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                                    row.subscription_status === "ACTIVE"
                                      ? "bg-emerald-100 text-emerald-700"
                                      : row.subscription_status === "PAST_DUE"
                                        ? "bg-red-100 text-red-700"
                                        : "bg-amber-100 text-amber-700"
                                  }`}>
                                    {row.subscription_status}
                                  </span>
                                  {row.current_period_end && (
                                    <p className="text-[11px] text-gray-400 m-0 mt-0.5">{row.current_period_end}</p>
                                  )}
                                  {row.last_payment_status && (
                                    <span className={`inline-block mt-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                                      row.last_payment_status === "PAID"
                                        ? "bg-emerald-50 text-emerald-600"
                                        : "bg-gray-100 text-gray-500"
                                    }`}>
                                      {row.last_payment_status}
                                    </span>
                                  )}
                                </div>
                              ) : (
                                <span className="text-gray-300">—</span>
                              )}
                            </td>
                            {/* Contact Name */}
                            <td className="px-4 py-2.5 text-sm text-gray-700 whitespace-nowrap">
                              {primaryName ? (
                                <button
                                  type="button"
                                  onClick={() => router.push(`/${org}/settings/tenants/${row.id}`)}
                                  className="font-medium text-gray-800 hover:text-[#0f2d1f] hover:underline text-left"
                                >
                                  {primaryName}
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => router.push(`/${org}/settings/tenants/${row.id}`)}
                                  className="text-[11px] font-bold text-[#0f2d1f] hover:underline"
                                >
                                  {t("sa.contacts_add_btn")}
                                </button>
                              )}
                            </td>
                            {/* Contact Email */}
                            <td className="px-4 py-2.5 text-xs text-gray-500">
                              {primaryEmail ?? <span className="text-gray-300">—</span>}
                            </td>
                            {/* Contact Phone */}
                            <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                              {primaryPhone ?? <span className="text-gray-300">—</span>}
                            </td>
                            {/* Personnel icon */}
                            <td className="px-4 py-2.5 text-center">
                              <button
                                type="button"
                                onClick={() => setPersonnelModalRow(row)}
                                title={t("sa.col_personnel")}
                                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold text-gray-600 bg-gray-100 hover:bg-gray-200 transition-colors"
                              >
                                <span>👥</span>
                                {totalContacts > 0 && <span>{totalContacts}</span>}
                              </button>
                            </td>
                            {/* Contract From */}
                            <td className="px-4 py-2.5 text-xs text-gray-600 whitespace-nowrap">
                              {row.contract_start ?? <span className="text-gray-300">—</span>}
                            </td>
                            {/* Contract To */}
                            <td className="px-4 py-2.5 text-xs whitespace-nowrap">
                              {row.contract_end ? (
                                <span className={new Date(row.contract_end) < new Date() ? "text-red-600 font-semibold" : "text-gray-600"}>
                                  {row.contract_end}
                                </span>
                              ) : <span className="text-gray-300">—</span>}
                            </td>
                            {/* Notes */}
                            <td className="px-4 py-2.5 text-xs text-gray-500 max-w-[140px]">
                              {row.notes
                                ? (row.notes.length > 35 ? row.notes.slice(0, 35) + "…" : row.notes)
                                : "—"}
                            </td>
                            {/* Actions */}
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <div className="flex gap-3">
                                <Link
                                  href={`/admin/settings/tenants/${row.id}`}
                                  className="text-xs font-bold text-[#0f2d1f] hover:underline"
                                >
                                  {t("sa.open_tenant")}
                                </Link>
                                <button
                                  type="button"
                                  onClick={() => setActivityTenantId(row.id)}
                                  className="text-xs font-bold text-[#0f2d1f] hover:underline"
                                >
                                  {t("sa.view_activity")}
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* "Tenant Admin" is now a picker only — every edit action lives on
              /settings/tenants/[tenantId] (CLAUDE.md §15 S9). */}
          {saTab === "admin" && (
            <div>
              <p className="text-sm text-gray-500 mb-4">{t("sa.admin_picker_hint")}</p>
              <div className="max-w-xs">
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1.5">
                  {t("sa.admin_select_tenant")}
                </label>
                <select
                  defaultValue=""
                  onChange={(e) => { if (e.target.value) router.push(`/${org}/settings/tenants/${e.target.value}`); }}
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white outline-none focus:border-[#0f2d1f] focus:ring-1 focus:ring-[#0f2d1f]"
                >
                  <option value="">{t("sa.admin_select_placeholder")}</option>
                  {apiRegistryList?.map((ten) => (
                    <option key={ten.id} value={ten.id}>{ten.name}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {saTab === "renewals" && (
            <div>
              {/* Stage counts */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
                {([
                  ["EXPIRING", "sa.renewals_count_expiring", "bg-amber-50 text-amber-800 border-amber-200"],
                  ["GRACE", "sa.renewals_count_grace", "bg-orange-50 text-orange-800 border-orange-200"],
                  ["READ_ONLY", "sa.renewals_count_read_only", "bg-red-50 text-red-800 border-red-200"],
                ] as const).map(([stage, labelKey, cls]) => (
                  <div key={stage} className={`rounded-lg border p-4 ${cls}`}>
                    <p className="text-xs font-bold uppercase tracking-wide m-0">{t(labelKey)}</p>
                    <p className="text-2xl font-bold m-0 mt-1">
                      {contractsOverviewLoading ? "…" : contractsOverview?.counts[stage] ?? 0}
                    </p>
                  </div>
                ))}
              </div>

              {/* Tenants in EXPIRING/GRACE/READ_ONLY */}
              <h3 className="text-base font-bold text-[#0f2d1f] mb-3">{t("dashboard.tenants_heading")}</h3>
              {contractsOverviewLoading && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
              {!contractsOverviewLoading && (!contractsOverview || contractsOverview.tenants.length === 0) && (
                <p className="text-gray-400 text-sm mb-6">{t("sa.renewals_tenants_empty")}</p>
              )}
              {!contractsOverviewLoading && contractsOverview && contractsOverview.tenants.length > 0 && (
                <div className="bg-white border border-gray-200 rounded overflow-x-auto mb-6">
                  <table className="w-full border-collapse text-sm min-w-[700px]">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        {[
                          "dashboard.tenant_name", "table.plan", "sa.col_end_date",
                          "sa.col_days_left", "sa.col_stage", "sa.col_open_request", "table.actions",
                        ].map((key) => (
                          <th key={key} className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                            {t(key)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {contractsOverview.tenants.map((ten, idx) => (
                        <tr key={ten.tenant_id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                          <td className="px-4 py-2.5 font-semibold text-gray-800 whitespace-nowrap">{ten.name}</td>
                          <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{ten.plan_tier ?? "—"}</td>
                          <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{ten.contract_end ?? "—"}</td>
                          <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{ten.days_left ?? "—"}</td>
                          <td className="px-4 py-2.5 whitespace-nowrap">
                            <span className="text-xs font-bold px-2.5 py-0.5 rounded bg-gray-100 text-gray-700">
                              {t(`sa.renewal_stage_${ten.stage}`)}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-center whitespace-nowrap">{ten.open_request_id ? "✓" : "—"}</td>
                          <td className="px-4 py-2.5 whitespace-nowrap">
                            <Link
                              href={`/${org}/settings/tenants/${ten.tenant_id}`}
                              className="text-xs font-semibold text-eth-forest hover:underline"
                            >
                              {t("sa.open_tenant")}
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Open renewal requests */}
              <h3 className="text-base font-bold text-[#0f2d1f] mb-3">{t("sa.renewals_open_requests_heading")}</h3>
              {openRenewalRequestsLoading && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
              {!openRenewalRequestsLoading && (!openRenewalRequests || openRenewalRequests.length === 0) && (
                <p className="text-gray-400 text-sm">{t("sa.renewals_empty")}</p>
              )}
              {!openRenewalRequestsLoading && openRenewalRequests && openRenewalRequests.length > 0 && (
                <div className="space-y-3">
                  {openRenewalRequests.map((r) => (
                    <div key={r.id} className="bg-white border border-gray-200 rounded p-4">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="min-w-0">
                          <p className="m-0 font-semibold text-gray-800 flex items-center gap-2 flex-wrap">
                            <Link href={`/${org}/settings/tenants/${r.tenant_id}`} className="text-eth-forest hover:underline">
                              {r.tenant_name}
                            </Link>
                            {r.plan_tier && <span className="text-xs text-gray-500 font-normal"> · {r.plan_tier}</span>}
                            <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700">
                              {r.request_type === "UPGRADE"
                                ? t("sa.renewals_type_upgrade").replace("{tier}", r.requested_tier ?? "")
                                : t("sa.renewals_type_renewal")}
                            </span>
                          </p>
                          <p className="m-0 text-xs text-gray-400 mt-0.5">
                            {t("sa.renewals_requested_by")} {r.requested_by_email ?? r.requested_by} · {new Date(r.created_at).toLocaleDateString()}
                          </p>
                          {r.message && (
                            <p className="m-0 text-xs text-gray-600 mt-1.5">
                              <span className="font-semibold">{t("sa.renewals_message_label")}:</span> {r.message}
                            </p>
                          )}
                          {r.request_type === "UPGRADE" && (
                            <p className="m-0 text-xs text-amber-700 mt-1.5">{t("sa.renewals_upgrade_hint")}</p>
                          )}
                        </div>
                        <div className="flex gap-2 shrink-0">
                          <button
                            type="button"
                            onClick={() => toggleRenewalAction(r.id, "handle")}
                            className="text-xs font-semibold text-emerald-600 hover:text-emerald-700 underline"
                          >
                            {t("sa.renewals_mark_handled_btn")}
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleRenewalAction(r.id, "cancel")}
                            className="text-xs font-semibold text-red-600 hover:text-red-700 underline"
                          >
                            {t("sa.renewals_cancel_btn")}
                          </button>
                        </div>
                      </div>
                      {renewalActionRow?.id === r.id && (
                        <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-2 items-end">
                          <div className="flex-1 min-w-[200px]">
                            <label className="block text-[11px] font-semibold text-gray-600 mb-1">
                              {t("sa.renewals_note_label")}
                            </label>
                            <input
                              type="text"
                              value={renewalNote}
                              onChange={(e) => setRenewalNote(e.target.value)}
                              className="w-full px-2 py-1 text-xs border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f]"
                            />
                          </div>
                          <button
                            type="button"
                            disabled={handleRenewalMutation.isPending}
                            onClick={() => handleRenewalMutation.mutate({
                              id: r.id,
                              status: renewalActionRow.type === "handle" ? "HANDLED" : "CANCELLED",
                              note: renewalNote,
                            })}
                            className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50"
                          >
                            {handleRenewalMutation.isPending ? "…" : t("sa.renewals_confirm_btn")}
                          </button>
                          <button
                            type="button"
                            onClick={() => setRenewalActionRow(null)}
                            className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200"
                          >
                            {t("sa.renewals_dismiss_btn")}
                          </button>
                        </div>
                      )}
                      {renewalActionRow?.id === r.id && renewalActionError && (
                        <p className="text-xs text-red-600 mt-2">{renewalActionError}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activityTenantId && (
            <>
              <div
                className="fixed inset-0 z-40 bg-black/30"
                onClick={() => setActivityTenantId(null)}
              />
              <div className="fixed right-0 top-0 z-50 h-full w-[420px] bg-white shadow-xl flex flex-col">
                <div className="flex items-center justify-between px-6 py-4 bg-[#0f2d1f]">
                  <h4 className="m-0 text-base font-bold text-white">{t("sa.activity_heading")}</h4>
                  <button
                    type="button"
                    onClick={() => setActivityTenantId(null)}
                    className="text-white hover:text-gray-300 text-lg font-bold leading-none"
                    aria-label={t("sa.activity_drawer_close")}
                  >
                    ×
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto px-6 py-4">
                  {activityLoading && (
                    <p className="text-gray-400 text-sm">{t("common.loading")}</p>
                  )}
                  {!activityLoading && (!activityLog || activityLog.length === 0) && (
                    <p className="text-gray-400 text-sm">{t("sa.activity_empty")}</p>
                  )}
                  {!activityLoading && activityLog && activityLog.map((entry, idx) => (
                    <div key={entry.id}>
                      <div className="py-3">
                        <p className="m-0 font-semibold text-gray-800 text-sm">
                          {(() => {
                            const actionKey = `sa.activity_action_${entry.action}`;
                            const translated = t(actionKey);
                            return translated !== actionKey ? translated : entry.action;
                          })()}
                        </p>
                        {entry.old_value && entry.new_value && (
                          <p className="m-0 text-xs text-gray-500 mt-0.5">
                            {entry.old_value} → {entry.new_value}
                          </p>
                        )}
                        <p className="m-0 text-xs text-gray-400 mt-0.5">
                          {t("sa.activity_by")} {entry.actor_email ?? entry.actor_id}
                        </p>
                        <p className="m-0 text-xs text-gray-400">
                          {new Date(entry.created_at).toLocaleString()}
                        </p>
                        {entry.note && (
                          <p className="m-0 text-xs text-gray-500 italic mt-1">{entry.note}</p>
                        )}
                      </div>
                      {idx < activityLog.length - 1 && (
                        <hr className="border-gray-100 m-0" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* ── Personnel modal ─────────────────────────────────────────────── */}
          {personnelModalRow && (
            <>
              <div
                className="fixed inset-0 z-40 bg-black/30"
                onClick={() => setPersonnelModalRow(null)}
              />
              <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
                <div className="pointer-events-auto bg-white rounded-lg shadow-xl w-full max-w-md overflow-hidden">
                  <div className="flex items-center justify-between px-5 py-4 bg-[#0f2d1f]">
                    <div>
                      <h4 className="m-0 text-sm font-bold text-white">{personnelModalRow.name}</h4>
                      <p className="m-0 text-xs text-emerald-300 mt-0.5">{t("sa.col_personnel")}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setPersonnelModalRow(null)}
                      className="text-white hover:text-gray-300 text-xl font-bold leading-none"
                      aria-label={t("sa.personnel_modal_close")}
                    >
                      ×
                    </button>
                  </div>
                  <div className="px-5 py-4 max-h-[60vh] overflow-y-auto space-y-3">
                    {/* TA admin — always shown first, gray tint */}
                    {(personnelModalRow.ta_name ?? personnelModalRow.ta_email) && (
                      <div className="flex items-start gap-3 p-3 border border-gray-200 rounded-lg bg-gray-100">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="m-0 font-semibold text-gray-500 text-sm">
                              {personnelModalRow.ta_name ?? "—"}
                            </p>
                            <span className="text-[10px] font-bold bg-gray-200 text-gray-500 px-1.5 py-0.5 rounded uppercase">
                              TA
                            </span>
                          </div>
                          {personnelModalRow.ta_email && (
                            <p className="m-0 text-xs text-gray-400 mt-1">
                              <span>✉ </span>{personnelModalRow.ta_email}
                            </p>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Structured contacts */}
                    {(personnelModalRow.contacts && personnelModalRow.contacts.length > 0
                      ? personnelModalRow.contacts
                      : (personnelModalRow.contact_name ?? personnelModalRow.contact_email)
                        ? [{
                            id: "legacy",
                            is_primary: true,
                            full_name: personnelModalRow.contact_name ?? "",
                            position_title: null,
                            email: personnelModalRow.contact_email,
                            phone: personnelModalRow.contact_phone,
                            mobile: null,
                          }]
                        : []
                    ).map((c, i) => (
                      <div key={c.id || i} className="flex items-start gap-3 p-3 border border-gray-100 rounded-lg bg-gray-50">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="m-0 font-semibold text-gray-800 text-sm">{c.full_name || "—"}</p>
                            {c.is_primary && (
                              <span className="text-[10px] font-bold bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded uppercase">
                                {t("sa.contacts_primary")}
                              </span>
                            )}
                          </div>
                          {c.position_title && <p className="m-0 text-xs text-gray-500 mt-0.5">{c.position_title}</p>}
                          {c.email && (
                            <p className="m-0 text-xs text-gray-600 mt-1">
                              <span className="text-gray-400">✉ </span>{c.email}
                            </p>
                          )}
                          {(c.phone ?? c.mobile) && (
                            <p className="m-0 text-xs text-gray-600 mt-0.5">
                              <span className="text-gray-400">☎ </span>{c.phone ?? c.mobile}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}

                    {/* Empty state — only when no TA and no contacts */}
                    {!personnelModalRow.ta_name && !personnelModalRow.ta_email &&
                     (!personnelModalRow.contacts || personnelModalRow.contacts.length === 0) &&
                     !personnelModalRow.contact_name && !personnelModalRow.contact_email && (
                      <p className="text-sm text-gray-400">{t("sa.personnel_no_contacts")}</p>
                    )}
                  </div>
                  <div className="px-5 py-3 border-t border-gray-100 flex justify-between items-center">
                    <button
                      type="button"
                      onClick={() => { setPersonnelModalRow(null); router.push(`/${org}/settings/tenants/${personnelModalRow.id}`); }}
                      className="text-xs font-bold text-[#0f2d1f] hover:underline"
                    >
                      {t("sa.contacts_edit_link")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPersonnelModalRow(null)}
                      className="px-3 py-1.5 text-xs font-semibold text-gray-600 rounded bg-gray-100 hover:bg-gray-200"
                    >
                      {t("sa.personnel_modal_close")}
                    </button>
                  </div>
                </div>
              </div>
            </>
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

    const expiryHref = `/${org}/lots?view=expiry`;
    const expiryRows = expiryAlerts ? [
      { label: t("dashboard.expired_lots"),    value: expiryAlerts.counts.expired,   warn: expiryAlerts.counts.expired > 0,   href: expiryHref },
      { label: t("dashboard.expiring_lots").replace("{days}", String(expiryAlerts.window_days)),
                                               value: expiryAlerts.counts.expiring,  warn: expiryAlerts.counts.expiring > 0,  href: expiryHref },
      { label: t("dashboard.no_expiry_lots"),  value: expiryAlerts.counts.no_expiry, warn: expiryAlerts.counts.no_expiry > 0, href: expiryHref },
    ] : [];

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
            ...expiryRows,
          ]}
        />

        {user.role === "TA" && <NeedHelpCard />}

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
