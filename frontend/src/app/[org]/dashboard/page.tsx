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
    plan_tier?: string | null;
  }

  interface TierConfigEntry {
    tier: string;
    max_warehouses: number | null;
    max_users: number | null;
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
    address_line1: string | null;
    city:          string | null;
    country:       string | null;
    contacts:      ApiRegistryContact[];
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

  const [saTab, setSaTab] = useState<"tenants" | "registry" | "admin">("tenants");
  const [activityTenantId, setActivityTenantId] = useState<string | null>(null);

  const [tierConfigOpen, setTierConfigOpen]   = useState(false);
  const [tierConfigForm, setTierConfigForm]   = useState<TierConfigEntry[]>([]);
  const [tierConfigSaving, setTierConfigSaving] = useState(false);
  const [tierConfigError, setTierConfigError]   = useState<string | null>(null);
  const [tierConfigSaved, setTierConfigSaved]   = useState(false);

  // ── Tenant Admin tab state ─────────────────────────────────────────────────
  const [adminTenantId, setAdminTenantId]       = useState<string>("");
  const [adminSubTab, setAdminSubTab]           = useState<"profile" | "plan" | "contract" | "status" | "levels" | "contacts">("profile");
  const [adminSaving, setAdminSaving]           = useState(false);
  const [adminError, setAdminError]             = useState<string | null>(null);
  const [adminSuccess, setAdminSuccess]         = useState<string | null>(null);
  const [adminConfirm, setAdminConfirm]         = useState<string | null>(null);
  const [adminProfile, setAdminProfile]         = useState({ name: "", organisation_type: "", default_locale: "", plan_tier: "" });
  const [adminInitProfile, setAdminInitProfile] = useState({ name: "", organisation_type: "", default_locale: "", plan_tier: "" });
  const [adminPlanTier, setAdminPlanTier]       = useState<string>("");
  const [adminContract, setAdminContract]       = useState({ start: "", end: "", note: "" });
  const [adminContacts, setAdminContacts]       = useState<ApiRegistryContact[]>([]);
  const [adminContactFormOpen, setAdminContactFormOpen] = useState(false);
  const [adminContactEditIdx, setAdminContactEditIdx]   = useState<number | null>(null);
  const [adminContactForm, setAdminContactForm]         = useState({ is_primary: false, full_name: "", position_title: "", email: "", phone: "", mobile: "" });

  const { data: platformTierConfig, refetch: refetchTierConfig } = useQuery<TierConfigEntry[]>({
    queryKey: ["platform-tier-config"],
    queryFn: () => api.get<TierConfigEntry[]>("/api/v1/tenants/platform/tier-config"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 60_000,
  });

  const { data: apiRegistryList, isLoading: registryLoading, isError: registryError } = useQuery<ApiRegistryRow[]>({
    queryKey: ["sa-registry"],
    queryFn: () => api.get<ApiRegistryRow[]>("/api/v1/tenants/sa/registry"),
    enabled: isGatewayMode && org === SA_ORG_SLUG,
    staleTime: 0,
    refetchOnMount: true,
  });

  const { data: activityLog, isLoading: activityLoading } = useQuery<ApiActivityRow[]>({
    queryKey: ["sa-activity", activityTenantId],
    queryFn: () => api.get<ApiActivityRow[]>(`/api/v1/tenants/sa/${activityTenantId}/activity`),
    enabled: isGatewayMode && !!activityTenantId,
    staleTime: 0,
  });

  // Tier defaults used for the "Reset to Defaults" button only.
  const TIER_DEFAULTS: Record<string, TierConfigEntry> = {
    STARTER:    { tier: "STARTER",    max_warehouses: 3,    max_users: 5    },
    GROWTH:     { tier: "GROWTH",     max_warehouses: 10,   max_users: 25   },
    ENTERPRISE: { tier: "ENTERPRISE", max_warehouses: null, max_users: null },
  };

  async function handleTierConfigSave() {
    setTierConfigSaving(true);
    setTierConfigError(null);
    setTierConfigSaved(false);
    try {
      await api.patch("/api/v1/tenants/platform/tier-config", { tiers: tierConfigForm });
      await refetchTierConfig();
      setTierConfigSaved(true);
    } catch (e: unknown) {
      setTierConfigError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setTierConfigSaving(false);
    }
  }

  // ── Tenant Admin tab helpers ───────────────────────────────────────────────
  function selectAdminTenant(id: string, subTab?: "profile" | "plan" | "contract" | "status" | "levels" | "contacts") {
    const ten = apiRegistryList?.find((r) => r.id === id);
    if (ten) {
      const prof = {
        name:              ten.name,
        organisation_type: ten.organisation_type ?? "",
        default_locale:    ten.default_locale    ?? "en",
        plan_tier:         ten.plan_tier          ?? "",
      };
      setAdminProfile(prof);
      setAdminInitProfile(prof);
      setAdminPlanTier(ten.plan_tier ?? "");
      setAdminContract({ start: ten.contract_start ?? "", end: ten.contract_end ?? "", note: "" });
      setAdminContacts(ten.contacts ?? []);
    }
    setAdminTenantId(id);
    setAdminSubTab(subTab ?? "profile");
    setAdminConfirm(null);
    setAdminError(null);
    setAdminSuccess(null);
    setAdminContactFormOpen(false);
    setAdminContactEditIdx(null);
    setAdminContactForm({ is_primary: false, full_name: "", position_title: "", email: "", phone: "", mobile: "" });
  }

  async function doAdminSave(apiFn: () => Promise<unknown>) {
    setAdminSaving(true);
    setAdminError(null);
    setAdminSuccess(null);
    try {
      await apiFn();
      setAdminSuccess(t("sa.admin_saved"));
      setAdminConfirm(null);
      void qc.invalidateQueries({ queryKey: ["sa-registry"] });
      void qc.invalidateQueries({ queryKey: ["tenants-list"] });
    } catch (e: unknown) {
      setAdminError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setAdminSaving(false);
    }
  }

  async function handleAdminProfileSave() {
    const body: Record<string, string> = {};
    if (adminProfile.name.trim() !== adminInitProfile.name && adminProfile.name.trim())
      body.name = adminProfile.name.trim();
    if (adminProfile.organisation_type !== adminInitProfile.organisation_type && adminProfile.organisation_type)
      body.organisation_type = adminProfile.organisation_type;
    if (adminProfile.default_locale !== adminInitProfile.default_locale)
      body.default_locale = adminProfile.default_locale;
    if (adminProfile.plan_tier !== adminInitProfile.plan_tier && adminProfile.plan_tier)
      body.plan_tier = adminProfile.plan_tier;
    if (Object.keys(body).length === 0) {
      setAdminConfirm(null);
      setAdminSuccess(t("sa.admin_no_changes"));
      return;
    }
    await doAdminSave(async () => {
      await api.patch(`/api/v1/tenants/${adminTenantId}/profile`, body);
      setAdminInitProfile({ ...adminProfile, name: adminProfile.name.trim() });
    });
  }

  async function handleAdminPlanSave() {
    const currentTier = apiRegistryList?.find((r) => r.id === adminTenantId)?.plan_tier ?? "";
    if (adminPlanTier === currentTier || !adminPlanTier) {
      setAdminConfirm(null);
      setAdminSuccess(t("sa.admin_no_changes"));
      return;
    }
    await doAdminSave(() => api.patch(`/api/v1/tenants/${adminTenantId}/plan`, { plan_tier: adminPlanTier }));
  }

  async function handleAdminContractSave() {
    const note = adminContract.note.trim();
    if (!note) {
      setAdminError(t("sa.edit_contract_note_required"));
      setAdminConfirm(null);
      return;
    }
    await doAdminSave(() =>
      api.patch(`/api/v1/tenants/${adminTenantId}/contract`, {
        contract_start: adminContract.start || null,
        contract_end:   adminContract.end   || null,
        note,
      })
    );
  }

  async function handleAdminStatusAction(action: "suspend" | "reactivate" | "deactivate") {
    setActionLoading(adminTenantId + action);
    await doAdminSave(async () => {
      await api.patch(`/api/v1/tenants/${adminTenantId}/${action}`, {});
    });
    setActionLoading(null);
  }

  async function handleAdminContactsSave() {
    const primaryCount = adminContacts.filter((c) => c.is_primary).length;
    if (adminContacts.length > 0 && primaryCount !== 1) {
      setAdminError(t("sa.contacts_need_primary"));
      setAdminConfirm(null);
      return;
    }
    await doAdminSave(() =>
      api.post(`/api/v1/tenants/${adminTenantId}/contacts/bulk`, {
        contacts: adminContacts.map((c) => ({
          is_primary:     c.is_primary,
          full_name:      c.full_name,
          position_title: c.position_title ?? null,
          email:          c.email ?? null,
          phone:          c.phone ?? null,
          mobile:         c.mobile ?? null,
        })),
      })
    );
  }

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
          <div className="flex gap-0 mb-6 border-b border-gray-200">
            {(["tenants", "registry", "admin"] as const).map((tab) => (
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
                  <button
                    type="button"
                    onClick={() => {
                      const current = platformTierConfig ?? Object.values(TIER_DEFAULTS);
                      setTierConfigForm(
                        ["STARTER", "GROWTH", "ENTERPRISE"].map((tier) =>
                          current.find((c) => c.tier === tier) ?? TIER_DEFAULTS[tier] ?? { tier, max_warehouses: null, max_users: null }
                        )
                      );
                      setTierConfigError(null);
                      setTierConfigSaved(false);
                      setTierConfigOpen(true);
                    }}
                    className="px-3 py-2 text-xs font-bold rounded bg-gray-100 text-gray-700 border border-gray-200 hover:bg-gray-200 transition-colors flex items-center gap-1.5"
                  >
                    ⚙ {t("sa.tier_config_btn")}
                  </button>
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
                  <table className="w-full border-collapse text-sm min-w-[700px]">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-200">
                        {[
                          "dashboard.tenant_name",
                          "sa.col_contact",
                          "sa.col_contract",
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
                          <td colSpan={5} className="px-4 py-8 text-center text-sm text-red-500">
                            {t("common.error")}
                          </td>
                        </tr>
                      )}
                      {!registryError && (!apiRegistryList || apiRegistryList.length === 0) && (
                        <tr>
                          <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">
                            {t("common.no_data")}
                          </td>
                        </tr>
                      )}
                      {(apiRegistryList ?? []).map((row, idx) => {
                        return (
                          <tr key={row.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                            <td className="px-4 py-2.5 font-semibold text-gray-800 whitespace-nowrap">
                              {row.name}
                            </td>
                            <td className="px-4 py-2.5">
                              {(() => {
                                const primary = row.contacts?.find((c) => c.is_primary) ?? null;
                                const extra   = (row.contacts ?? []).filter((c) => !c.is_primary).length;
                                if (primary) {
                                  return (
                                    <div>
                                      <p className="m-0 font-medium text-gray-800 text-[13px]">{primary.full_name}</p>
                                      {primary.position_title && <p className="m-0 text-[11px] text-gray-400">{primary.position_title}</p>}
                                      {primary.email && <p className="m-0 text-xs text-gray-500">{primary.email}</p>}
                                      {(primary.phone ?? primary.mobile) && (
                                        <p className="m-0 text-xs text-gray-400">{primary.phone ?? primary.mobile}</p>
                                      )}
                                      {extra > 0 && (
                                        <p className="m-0 text-[11px] text-gray-400">+{extra} {t("sa.contacts_more")}</p>
                                      )}
                                      <button type="button"
                                        onClick={() => { selectAdminTenant(row.id, "contacts"); setSaTab("admin"); }}
                                        className="mt-1 text-[11px] font-bold text-[#0f2d1f] hover:underline"
                                      >
                                        {t("sa.contacts_edit_link")}
                                      </button>
                                    </div>
                                  );
                                }
                                if (row.contact_name ?? row.contact_email) {
                                  return (
                                    <div>
                                      {row.contact_name  && <p className="m-0 font-medium text-gray-800">{row.contact_name}</p>}
                                      {row.contact_email && <p className="m-0 text-xs text-gray-500">{row.contact_email}</p>}
                                      {row.contact_phone && <p className="m-0 text-xs text-gray-400">{row.contact_phone}</p>}
                                      <button type="button"
                                        onClick={() => { selectAdminTenant(row.id, "contacts"); setSaTab("admin"); }}
                                        className="mt-1 text-[11px] font-bold text-[#0f2d1f] hover:underline"
                                      >
                                        {t("sa.contacts_edit_link")}
                                      </button>
                                    </div>
                                  );
                                }
                                return (
                                  <button type="button"
                                    onClick={() => { selectAdminTenant(row.id, "contacts"); setSaTab("admin"); }}
                                    className="text-[11px] font-bold text-[#0f2d1f] hover:underline"
                                  >
                                    {t("sa.contacts_add_btn")}
                                  </button>
                                );
                              })()}
                            </td>
                            <td className="px-4 py-2.5 text-xs text-gray-600">
                              {row.contract_start ?? row.contract_end ? (
                                <div>
                                  {row.contract_start && <p className="m-0"><span className="text-gray-400">{t("sa.contract_from")}</span> {row.contract_start}</p>}
                                  {row.contract_end   && <p className="m-0"><span className="text-gray-400">{t("sa.contract_to")}</span> {row.contract_end}</p>}
                                </div>
                              ) : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-xs text-gray-500 max-w-[160px]">
                              {row.notes
                                ? (row.notes.length > 40 ? row.notes.slice(0, 40) + "…" : row.notes)
                                : "—"}
                            </td>
                            <td className="px-4 py-2.5 whitespace-nowrap">
                              <button
                                type="button"
                                onClick={() => setActivityTenantId(row.id)}
                                className="text-xs font-bold text-[#0f2d1f] hover:underline"
                              >
                                {t("sa.view_activity")}
                              </button>
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

          {saTab === "admin" && (
            <div>
              {/* Tenant selector */}
              <div className="mb-6 max-w-xs">
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wide mb-1.5">
                  {t("sa.admin_select_tenant")}
                </label>
                <select
                  value={adminTenantId}
                  onChange={(e) => selectAdminTenant(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white outline-none focus:border-[#0f2d1f] focus:ring-1 focus:ring-[#0f2d1f]"
                >
                  <option value="">{t("sa.admin_select_placeholder")}</option>
                  {apiRegistryList?.map((ten) => (
                    <option key={ten.id} value={ten.id}>{ten.name}</option>
                  ))}
                </select>
              </div>

              {adminTenantId && (() => {
                const selTen = apiRegistryList?.find((r) => r.id === adminTenantId);
                if (!selTen) return null;
                const selStatus = selTen.status || "ACTIVE";
                const selSlug   = selTen.slug ?? selTen.id;
                const ADMIN_SUBTABS = ["profile", "plan", "contract", "status", "levels", "contacts"] as const;
                return (
                  <div>
                    <p className="text-sm font-semibold text-[#0f2d1f] mb-3">{selTen.name}</p>

                    {/* Sub-tab bar */}
                    <div className="flex gap-0 border-b border-gray-200 mb-6">
                      {ADMIN_SUBTABS.map((sub) => (
                        <button
                          key={sub}
                          type="button"
                          onClick={() => {
                            setAdminSubTab(sub);
                            setAdminConfirm(null);
                            setAdminError(null);
                            setAdminSuccess(null);
                          }}
                          className={[
                            "px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors",
                            adminSubTab === sub
                              ? "border-[#0f2d1f] text-[#0f2d1f]"
                              : "border-transparent text-gray-500 hover:text-gray-700",
                          ].join(" ")}
                        >
                          {t(`sa.admin_sub_${sub}`)}
                        </button>
                      ))}
                    </div>

                    {/* Feedback */}
                    {adminError && (
                      <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-4 py-2 mb-4">{adminError}</p>
                    )}
                    {adminSuccess && (
                      <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-4 py-2 mb-4">{adminSuccess}</p>
                    )}

                    {/* ── Profile ─────────────────────────────────────────── */}
                    {adminSubTab === "profile" && (
                      <div className="max-w-md">
                        <div className="flex flex-col gap-4 mb-5">
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("sa.edit_profile_field_name")}</label>
                            <input
                              type="text"
                              value={adminProfile.name}
                              onChange={(e) => { setAdminProfile((p) => ({ ...p, name: e.target.value })); setAdminSuccess(null); }}
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f] focus:ring-1 focus:ring-[#0f2d1f]"
                            />
                          </div>
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("sa.edit_profile_field_org_type")}</label>
                            <select
                              value={adminProfile.organisation_type}
                              onChange={(e) => { setAdminProfile((p) => ({ ...p, organisation_type: e.target.value })); setAdminSuccess(null); }}
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f] bg-white"
                            >
                              <option value="PRODUCER">PRODUCER</option>
                              <option value="RETAILER">RETAILER</option>
                              <option value="HYBRID">HYBRID</option>
                            </select>
                            {adminProfile.organisation_type !== adminInitProfile.organisation_type && adminProfile.organisation_type && (
                              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mt-2">
                                {t("sa.edit_profile_org_type_warning")}
                              </p>
                            )}
                          </div>
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("sa.edit_profile_field_locale")}</label>
                            <select
                              value={adminProfile.default_locale}
                              onChange={(e) => { setAdminProfile((p) => ({ ...p, default_locale: e.target.value })); setAdminSuccess(null); }}
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f] bg-white"
                            >
                              <option value="en">English (en)</option>
                              <option value="am">Amharic / አማርኛ (am)</option>
                              <option value="or">Oromifa / Afaan Oromoo (or)</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-2">{t("sa.edit_profile_field_plan_tier")}</label>
                            <div className="flex gap-2">
                              {(["STARTER", "GROWTH", "ENTERPRISE"] as const).map((tier) => (
                                <button
                                  key={tier}
                                  type="button"
                                  onClick={() => { setAdminProfile((p) => ({ ...p, plan_tier: tier })); setAdminSuccess(null); }}
                                  className={[
                                    "flex-1 py-2 rounded border-2 text-xs font-bold transition-colors",
                                    adminProfile.plan_tier === tier
                                      ? "border-[#0f2d1f] bg-[#0f2d1f] text-white"
                                      : "border-gray-200 text-gray-600 hover:border-gray-400",
                                  ].join(" ")}
                                >
                                  {tier}
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                        {adminConfirm === "save" ? (
                          <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
                            <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
                            <button type="button" disabled={adminSaving} onClick={() => void handleAdminProfileSave()}
                              className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
                              {adminSaving ? "…" : t("sa.admin_confirm_yes")}
                            </button>
                            <button type="button" disabled={adminSaving} onClick={() => setAdminConfirm(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
                              {t("sa.admin_confirm_no")}
                            </button>
                          </div>
                        ) : (
                          <button type="button" onClick={() => { setAdminConfirm("save"); setAdminSuccess(null); setAdminError(null); }}
                            className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35]">
                            {t("sa.admin_save_btn")}
                          </button>
                        )}
                      </div>
                    )}

                    {/* ── Plan ────────────────────────────────────────────── */}
                    {adminSubTab === "plan" && (
                      <div className="max-w-md">
                        <p className="text-xs text-gray-500 mb-4">
                          {t("sa.plan_modal_current")}:{" "}
                          <span className={`font-bold px-1.5 py-0.5 rounded text-xs ${PLAN_TIER_BADGE[selTen.plan_tier ?? ""] ?? "bg-gray-100 text-gray-600"}`}>
                            {selTen.plan_tier ?? "—"}
                          </span>
                        </p>
                        <p className="text-xs font-bold text-gray-700 uppercase tracking-wide mb-2">{t("sa.plan_modal_new")}</p>
                        <div className="flex gap-3 mb-3">
                          {(["STARTER", "GROWTH", "ENTERPRISE"] as const).map((tier) => (
                            <button key={tier} type="button"
                              onClick={() => { setAdminPlanTier(tier); setAdminSuccess(null); }}
                              className={[
                                "flex-1 py-3 rounded border-2 text-sm font-bold transition-colors",
                                adminPlanTier === tier
                                  ? "border-[#0f2d1f] bg-[#0f2d1f] text-white"
                                  : "border-gray-200 text-gray-700 hover:border-gray-400",
                              ].join(" ")}
                            >
                              {tier}
                              {tier === (selTen.plan_tier ?? "") && (
                                <span className="block text-xs font-normal opacity-70 mt-0.5">{t("sa.plan_modal_current").toLowerCase()}</span>
                              )}
                            </button>
                          ))}
                        </div>
                        <p className="text-xs text-gray-400 mb-3">{t("sa.plan_modal_caps")}</p>
                        {adminPlanTier !== (selTen.plan_tier ?? "") && adminPlanTier && (
                          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-3">
                            {t("sa.plan_modal_downgrade_note")}
                          </p>
                        )}
                        {adminConfirm === "save" ? (
                          <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
                            <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
                            <button type="button" disabled={adminSaving} onClick={() => void handleAdminPlanSave()}
                              className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
                              {adminSaving ? "…" : t("sa.admin_confirm_yes")}
                            </button>
                            <button type="button" disabled={adminSaving} onClick={() => setAdminConfirm(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
                              {t("sa.admin_confirm_no")}
                            </button>
                          </div>
                        ) : (
                          <button type="button"
                            disabled={!adminPlanTier || adminPlanTier === (selTen.plan_tier ?? "")}
                            onClick={() => { setAdminConfirm("save"); setAdminSuccess(null); setAdminError(null); }}
                            className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
                            {t("sa.admin_save_btn")}
                          </button>
                        )}
                      </div>
                    )}

                    {/* ── Contract ─────────────────────────────────────────── */}
                    {adminSubTab === "contract" && (
                      <div className="max-w-md">
                        <div className="flex flex-col gap-4 mb-5">
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("wizard.contract_start")}</label>
                              <input type="date" value={adminContract.start}
                                onChange={(e) => { setAdminContract((c) => ({ ...c, start: e.target.value })); setAdminSuccess(null); }}
                                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                              />
                            </div>
                            <div>
                              <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("wizard.contract_end")}</label>
                              <input type="date" value={adminContract.end}
                                onChange={(e) => { setAdminContract((c) => ({ ...c, end: e.target.value })); setAdminSuccess(null); }}
                                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                              />
                            </div>
                          </div>
                          {adminContract.end && adminContract.end < new Date().toISOString().slice(0, 10) && (
                            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                              {t("sa.edit_contract_warning_past")}
                            </p>
                          )}
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                              {t("sa.edit_contract_note_label")} <span className="text-red-500">*</span>
                            </label>
                            <textarea rows={3} value={adminContract.note}
                              placeholder={t("sa.edit_contract_note_placeholder")}
                              onChange={(e) => { setAdminContract((c) => ({ ...c, note: e.target.value })); setAdminSuccess(null); }}
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 resize-none"
                            />
                          </div>
                        </div>
                        {adminConfirm === "save" ? (
                          <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
                            <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
                            <button type="button" disabled={adminSaving} onClick={() => void handleAdminContractSave()}
                              className="px-3 py-1.5 text-xs font-bold text-white bg-sky-600 rounded hover:bg-sky-700 disabled:opacity-50">
                              {adminSaving ? "…" : t("sa.admin_confirm_yes")}
                            </button>
                            <button type="button" disabled={adminSaving} onClick={() => setAdminConfirm(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
                              {t("sa.admin_confirm_no")}
                            </button>
                          </div>
                        ) : (
                          <button type="button"
                            onClick={() => { setAdminConfirm("save"); setAdminSuccess(null); setAdminError(null); }}
                            className="px-4 py-2 text-sm font-bold text-white bg-sky-600 rounded hover:bg-sky-700">
                            {t("sa.admin_save_btn")}
                          </button>
                        )}
                      </div>
                    )}

                    {/* ── Status ───────────────────────────────────────────── */}
                    {adminSubTab === "status" && (
                      <div className="max-w-md">
                        <div className="mb-5">
                          <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">{t("sa.admin_status_heading")}</p>
                          <span className={`text-xs font-bold px-2.5 py-0.5 rounded ${STATUS_BADGE[selStatus] ?? "bg-gray-100 text-gray-700"}`}>
                            {STATUS_LABEL_KEY[selStatus] ? t(STATUS_LABEL_KEY[selStatus] as string) : selStatus}
                          </span>
                        </div>
                        <div className="flex gap-3 mb-5">
                          {selStatus === "ACTIVE" && (
                            <button type="button"
                              onClick={() => { setAdminConfirm("suspend"); setAdminSuccess(null); setAdminError(null); }}
                              className="px-4 py-2 text-sm font-bold text-white bg-amber-500 rounded hover:bg-amber-600">
                              {t("sa.action_suspend")}
                            </button>
                          )}
                          {selStatus !== "ACTIVE" && (
                            <button type="button"
                              onClick={() => { setAdminConfirm("reactivate"); setAdminSuccess(null); setAdminError(null); }}
                              className="px-4 py-2 text-sm font-bold text-white bg-emerald-600 rounded hover:bg-emerald-700">
                              {t("sa.action_reactivate")}
                            </button>
                          )}
                          {selStatus !== "DEACTIVATED" && (
                            <button type="button"
                              onClick={() => { setAdminConfirm("deactivate"); setAdminSuccess(null); setAdminError(null); }}
                              className="px-4 py-2 text-sm font-bold text-white bg-red-600 rounded hover:bg-red-700">
                              {t("sa.action_deactivate")}
                            </button>
                          )}
                        </div>
                        {(adminConfirm === "suspend" || adminConfirm === "reactivate" || adminConfirm === "deactivate") && (
                          <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
                            <span className="text-sm text-gray-700 flex-1">
                              {t(CONFIRM_BODY_KEY[adminConfirm as "suspend" | "reactivate" | "deactivate"]).replace("{name}", selTen.name)}
                            </span>
                            <button type="button" disabled={adminSaving}
                              onClick={() => void handleAdminStatusAction(adminConfirm as "suspend" | "reactivate" | "deactivate")}
                              className={`px-3 py-1.5 text-xs font-bold text-white rounded disabled:opacity-50 ${
                                adminConfirm === "deactivate" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"
                              }`}>
                              {adminSaving ? "…" : t("sa.admin_confirm_yes")}
                            </button>
                            <button type="button" disabled={adminSaving} onClick={() => setAdminConfirm(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
                              {t("sa.admin_confirm_no")}
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                    {/* ── Levels ───────────────────────────────────────────── */}
                    {adminSubTab === "levels" && (
                      <div className="max-w-md">
                        <p className="text-sm text-gray-600 mb-4">{t("sa.admin_levels_description")}</p>
                        <Link
                          href={`/${selSlug}/settings/org-setup`}
                          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-bold rounded bg-indigo-600 text-white hover:bg-indigo-700 no-underline"
                        >
                          {t("sa.admin_levels_open_btn")}
                        </Link>
                      </div>
                    )}

                    {/* ── Contacts ─────────────────────────────────────────── */}
                    {adminSubTab === "contacts" && (
                      <div className="max-w-lg">
                        {/* Contacts list */}
                        {adminContacts.length === 0 ? (
                          <p className="text-sm text-gray-400 mb-4">{t("sa.contacts_empty")}</p>
                        ) : (
                          <div className="space-y-2 mb-4">
                            {adminContacts.map((c, idx) => (
                              <div key={idx} className="flex items-start gap-3 p-3 border border-gray-200 rounded bg-white">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <p className="m-0 font-semibold text-gray-800 text-sm">{c.full_name}</p>
                                    {c.is_primary && (
                                      <span className="text-[10px] font-bold bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded uppercase">
                                        {t("sa.contacts_primary")}
                                      </span>
                                    )}
                                  </div>
                                  {c.position_title && <p className="m-0 text-xs text-gray-500">{c.position_title}</p>}
                                  {c.email && <p className="m-0 text-xs text-gray-500">{c.email}</p>}
                                  {(c.phone ?? c.mobile) && <p className="m-0 text-xs text-gray-400">{c.phone ?? c.mobile}</p>}
                                </div>
                                <div className="flex gap-2 shrink-0">
                                  <button type="button"
                                    onClick={() => {
                                      setAdminContactEditIdx(idx);
                                      setAdminContactForm({
                                        is_primary:     c.is_primary,
                                        full_name:      c.full_name,
                                        position_title: c.position_title ?? "",
                                        email:          c.email ?? "",
                                        phone:          c.phone ?? "",
                                        mobile:         c.mobile ?? "",
                                      });
                                      setAdminContactFormOpen(true);
                                      setAdminSuccess(null);
                                    }}
                                    className="text-xs font-bold text-blue-600 hover:underline"
                                  >
                                    {t("common.edit")}
                                  </button>
                                  <button type="button"
                                    onClick={() => {
                                      setAdminContacts((prev) => prev.filter((_, i) => i !== idx));
                                      setAdminSuccess(null);
                                    }}
                                    className="text-xs font-bold text-red-500 hover:underline"
                                  >
                                    {t("common.remove")}
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Add / Edit form */}
                        {adminContactFormOpen ? (
                          <div className="border border-gray-200 rounded p-4 mb-4 bg-gray-50">
                            <p className="text-xs font-bold text-gray-600 uppercase tracking-wide mb-3">
                              {adminContactEditIdx === null ? t("sa.contacts_add_title") : t("sa.contacts_edit_title")}
                            </p>
                            <div className="flex flex-col gap-3">
                              <div className="flex items-center gap-2">
                                <input type="checkbox" id="contact-primary"
                                  checked={adminContactForm.is_primary}
                                  onChange={(e) => setAdminContactForm((f) => ({ ...f, is_primary: e.target.checked }))}
                                  className="h-4 w-4"
                                />
                                <label htmlFor="contact-primary" className="text-sm text-gray-700">{t("sa.contacts_is_primary")}</label>
                              </div>
                              <input type="text" placeholder={t("sa.contacts_field_name")}
                                value={adminContactForm.full_name}
                                onChange={(e) => setAdminContactForm((f) => ({ ...f, full_name: e.target.value }))}
                                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f]"
                              />
                              <input type="text" placeholder={t("sa.contacts_field_title")}
                                value={adminContactForm.position_title}
                                onChange={(e) => setAdminContactForm((f) => ({ ...f, position_title: e.target.value }))}
                                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f]"
                              />
                              <input type="email" placeholder={t("sa.contacts_field_email")}
                                value={adminContactForm.email}
                                onChange={(e) => setAdminContactForm((f) => ({ ...f, email: e.target.value }))}
                                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f]"
                              />
                              <div className="grid grid-cols-2 gap-2">
                                <input type="tel" placeholder={t("sa.contacts_field_phone")}
                                  value={adminContactForm.phone}
                                  onChange={(e) => setAdminContactForm((f) => ({ ...f, phone: e.target.value }))}
                                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f]"
                                />
                                <input type="tel" placeholder={t("sa.contacts_field_mobile")}
                                  value={adminContactForm.mobile}
                                  onChange={(e) => setAdminContactForm((f) => ({ ...f, mobile: e.target.value }))}
                                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f]"
                                />
                              </div>
                              <div className="flex gap-2">
                                <button type="button"
                                  disabled={!adminContactForm.full_name.trim()}
                                  onClick={() => {
                                    const contact: ApiRegistryContact = {
                                      id:             adminContactEditIdx !== null ? (adminContacts[adminContactEditIdx]?.id ?? "") : "",
                                      is_primary:     adminContactForm.is_primary,
                                      full_name:      adminContactForm.full_name.trim(),
                                      position_title: adminContactForm.position_title.trim() || null,
                                      email:          adminContactForm.email.trim() || null,
                                      phone:          adminContactForm.phone.trim() || null,
                                      mobile:         adminContactForm.mobile.trim() || null,
                                    };
                                    if (adminContactEditIdx !== null) {
                                      setAdminContacts((prev) => prev.map((c, i) => i === adminContactEditIdx ? contact : c));
                                    } else {
                                      setAdminContacts((prev) => [...prev, contact]);
                                    }
                                    setAdminContactFormOpen(false);
                                    setAdminContactEditIdx(null);
                                    setAdminContactForm({ is_primary: false, full_name: "", position_title: "", email: "", phone: "", mobile: "" });
                                    setAdminSuccess(null);
                                  }}
                                  className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50"
                                >
                                  {adminContactEditIdx !== null ? t("sa.contacts_update_btn") : t("sa.contacts_add_btn")}
                                </button>
                                <button type="button"
                                  onClick={() => {
                                    setAdminContactFormOpen(false);
                                    setAdminContactEditIdx(null);
                                    setAdminContactForm({ is_primary: false, full_name: "", position_title: "", email: "", phone: "", mobile: "" });
                                  }}
                                  className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200"
                                >
                                  {t("common.cancel")}
                                </button>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <button type="button"
                            onClick={() => {
                              setAdminContactForm({ is_primary: adminContacts.length === 0, full_name: "", position_title: "", email: "", phone: "", mobile: "" });
                              setAdminContactEditIdx(null);
                              setAdminContactFormOpen(true);
                              setAdminSuccess(null);
                            }}
                            className="mb-4 px-3 py-1.5 text-xs font-bold text-[#0f2d1f] border border-[#0f2d1f] rounded hover:bg-[#0f2d1f] hover:text-white transition-colors"
                          >
                            + {t("sa.contacts_add_btn")}
                          </button>
                        )}

                        {/* Save */}
                        {adminConfirm === "save" ? (
                          <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
                            <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
                            <button type="button" disabled={adminSaving} onClick={() => void handleAdminContactsSave()}
                              className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
                              {adminSaving ? "…" : t("sa.admin_confirm_yes")}
                            </button>
                            <button type="button" disabled={adminSaving} onClick={() => setAdminConfirm(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
                              {t("sa.admin_confirm_no")}
                            </button>
                          </div>
                        ) : (
                          <button type="button"
                            onClick={() => { setAdminConfirm("save"); setAdminSuccess(null); setAdminError(null); }}
                            className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35]"
                          >
                            {t("sa.admin_save_btn")}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })()}
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

          {tierConfigOpen && (
            <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
              <div className="bg-white rounded-lg shadow-lg w-full max-w-lg p-6">
                <h4 className="text-base font-bold text-gray-900 m-0 mb-0.5">{t("sa.tier_config_title")}</h4>
                <p className="text-xs text-gray-500 mb-5">{t("sa.tier_config_subtitle")}</p>

                <table className="w-full text-sm border-collapse mb-2">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wide w-28">{t("sa.tier_config_tier")}</th>
                      <th className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">{t("sa.tier_config_max_wh")}</th>
                      <th className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">{t("sa.tier_config_max_users")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tierConfigForm.map((entry, idx) => {
                      const TIER_BADGE: Record<string, string> = {
                        STARTER:    "bg-gray-100 text-gray-600",
                        GROWTH:     "bg-blue-100 text-blue-700",
                        ENTERPRISE: "bg-amber-100 text-amber-700",
                      };
                      return (
                        <tr key={entry.tier} className="border-b border-gray-100">
                          <td className="px-3 py-3">
                            <span className={`text-xs font-extrabold px-2 py-0.5 rounded ${TIER_BADGE[entry.tier] ?? "bg-gray-100 text-gray-600"}`}>
                              {entry.tier}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex items-center gap-2">
                              <input
                                type="number"
                                min={1}
                                value={entry.max_warehouses ?? ""}
                                placeholder={t("sa.tier_config_unlimited")}
                                onChange={(e) => {
                                  const v = e.target.value === "" ? null : parseInt(e.target.value, 10);
                                  setTierConfigForm((f) => f.map((r, i) => i === idx ? { ...r, max_warehouses: v } : r));
                                }}
                                className="w-24 px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                              />
                              {entry.max_warehouses === null && (
                                <span className="text-xs text-gray-400">{t("sa.tier_config_unlimited")}</span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex items-center gap-2">
                              <input
                                type="number"
                                min={1}
                                value={entry.max_users ?? ""}
                                placeholder={t("sa.tier_config_unlimited")}
                                onChange={(e) => {
                                  const v = e.target.value === "" ? null : parseInt(e.target.value, 10);
                                  setTierConfigForm((f) => f.map((r, i) => i === idx ? { ...r, max_users: v } : r));
                                }}
                                className="w-24 px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                              />
                              {entry.max_users === null && (
                                <span className="text-xs text-gray-400">{t("sa.tier_config_unlimited")}</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <p className="text-[11px] text-gray-400 mb-3">{t("sa.tier_config_note")}</p>

                {tierConfigError && (
                  <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-3">{tierConfigError}</p>
                )}
                {tierConfigSaved && (
                  <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-3 py-2 mb-3">{t("sa.tier_config_saved")}</p>
                )}

                <div className="flex items-center justify-between mt-2">
                  <button
                    type="button"
                    onClick={() => setTierConfigForm(
                      ["STARTER", "GROWTH", "ENTERPRISE"].map((tier) => TIER_DEFAULTS[tier] ?? { tier, max_warehouses: null, max_users: null })
                    )}
                    className="text-xs font-semibold text-gray-500 hover:text-gray-700 underline"
                  >
                    {t("sa.tier_config_reset")}
                  </button>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => { setTierConfigOpen(false); setTierConfigSaved(false); }}
                      className="px-4 py-2 text-sm font-bold text-gray-600 rounded hover:bg-gray-100"
                    >
                      {t("common.cancel")}
                    </button>
                    <button
                      type="button"
                      disabled={tierConfigSaving}
                      onClick={() => void handleTierConfigSave()}
                      className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50"
                    >
                      {tierConfigSaving ? t("sa.tier_config_saving") : t("sa.tier_config_save")}
                    </button>
                  </div>
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
