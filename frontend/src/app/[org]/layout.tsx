"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { getSession, logout, SA_ORG_SLUG, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS, getLowStockProducts } from "@/lib/demo-data";
import { api } from "@/lib/api";
import { getCurrentLocale, setLocale, loadLocale, t } from "@/lib/i18n";
import { formatNumber } from "@/lib/format";
import { ENABLED_LOCALES } from "@/lib/locales-config";
import { useInventoryStore } from "@/lib/inventory-state";
import { useTenantName } from "@/hooks/useTenantName";
import { useContractStatus } from "@/hooks/useContractStatus";
import { PublicContactLink } from "@/components/features/auth/PublicContactLink";
import { ContactModal } from "@/components/features/contact/ContactModal";
import { GlobalToast } from "@/components/ui/GlobalToast";

type Locale = "en" | "am" | "or";

const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;

/* ── Role badge Tailwind classes ──────────────────────────────────────────── */
const ROLE_BADGE: Record<string, string> = {
  SA:  "bg-red-600",
  TA:  "bg-violet-600",
  NM:  "bg-blue-600",
  RM:  "bg-teal-600",
  WM:  "bg-emerald-600",
  LM:  "bg-cyan-600",
  AU:  "bg-gray-500",
  SYS: "bg-amber-600",
};

/* ── Notification bell ────────────────────────────────────────────────────── */

interface AutoApprovalAlert {
  id: string;
  alert_type: "AUTO_APPROVAL_NOTICE";
  transfer_id: string;
  transfer_ref: string;
  transfer_type: string;
  quantity: number;
  product_name: string;
  warehouse_name: string;
  reason: string;
  created_at: string;
}

function NotificationBell({ org }: { org: string }) {
  const [open, setOpen] = useState(false);

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  const lowStock     = tenant ? getLowStockProducts(tenant) : [];
  const expiryAlerts = tenant ? tenant.products.filter((p) => p.batchTracking).slice(0, 2) : [];

  const demoAlerts = [
    ...lowStock.map((p)     => ({ type: "low_stock" as const, product: p.name, sku: p.sku })),
    ...expiryAlerts.map((p) => ({ type: "expiry"    as const, product: p.name, sku: p.sku })),
  ];

  const { data: autoApprovalAlerts = [] } = useQuery<AutoApprovalAlert[]>({
    queryKey: ["auto-approval-alerts", org],
    queryFn:  async () => {
      try {
        const r = await api.get<AutoApprovalAlert[]>(
          "/api/v1/inventory/alerts/?alert_type=AUTO_APPROVAL_NOTICE"
        );
        return r ?? [];
      } catch {
        return [];
      }
    },
    enabled:         isGatewayMode,
    staleTime:       30_000,
    refetchInterval: 60_000,
  });

  const count = isGatewayMode
    ? autoApprovalAlerts.length
    : demoAlerts.length;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative bg-white/10 border-0 rounded cursor-pointer w-[34px] h-[34px] flex items-center justify-center text-base"
        title={t("notifications.title")}
      >
        🔔
        {count > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 bg-red-600 text-white text-[10px] font-extrabold rounded-full flex items-center justify-center px-0.5">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)} className="fixed inset-0 z-[90]" />
          <div className="absolute top-full right-0 mt-2 w-80 bg-white rounded-lg shadow-2xl border border-gray-200 z-[100] overflow-hidden">
            <div className="px-3.5 py-2.5 border-b border-gray-100 flex items-center justify-between">
              <span className="font-bold text-sm text-gray-800">
                {t("notifications.title")} {count > 0 && `(${count})`}
              </span>
              <button
                onClick={() => setOpen(false)}
                className="bg-transparent border-0 cursor-pointer text-sm text-gray-400"
              >
                ✕
              </button>
            </div>

            {/* Gateway mode: show real auto-approval notices */}
            {isGatewayMode && (
              autoApprovalAlerts.length === 0 ? (
                <p className="p-6 text-center text-gray-400 text-sm">{t("notifications.no_alerts")}</p>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  {autoApprovalAlerts.map((a) => (
                    <Link
                      key={a.id}
                      href={`/${org}/transfers/${a.transfer_id}`}
                      onClick={() => setOpen(false)}
                      className="flex items-start gap-2.5 px-3.5 py-2.5 border-b border-gray-50 no-underline"
                    >
                      <span className="text-base shrink-0 mt-0.5">🔔</span>
                      <div>
                        <p className="font-semibold text-sm text-gray-800 m-0">
                          {t("common.auto_approved_transfer")
                            .replace("{type}", a.transfer_type)
                            .replace("{ref}", a.transfer_ref)}
                        </p>
                        <p className="text-xs text-gray-500 m-0 mt-0.5">
                          {t("common.units_summary")
                            .replace("{qty}", formatNumber(a.quantity))
                            .replace("{product}", a.product_name)
                            .replace("{warehouse}", a.warehouse_name)}
                        </p>
                        <p className="text-xs text-blue-600 m-0 mt-0.5 font-medium">{a.reason}</p>
                      </div>
                    </Link>
                  ))}
                </div>
              )
            )}

            {/* Demo mode: show static low-stock / expiry alerts */}
            {!isGatewayMode && (
              demoAlerts.length === 0 ? (
                <p className="p-6 text-center text-gray-400 text-sm">{t("notifications.no_alerts")}</p>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  {demoAlerts.map((a, i) => (
                    <Link
                      key={i}
                      href={`/${org}/inventory`}
                      onClick={() => setOpen(false)}
                      className="flex items-start gap-2.5 px-3.5 py-2.5 border-b border-gray-50 no-underline"
                    >
                      <span className="text-base shrink-0 mt-0.5">{a.type === "low_stock" ? "📉" : "⚠️"}</span>
                      <div>
                        <p className="font-semibold text-sm text-gray-800 m-0">{a.product}</p>
                        <p className={`text-xs m-0 mt-0.5 font-semibold ${a.type === "low_stock" ? "text-red-600" : "text-amber-800"}`}>
                          {a.type === "low_stock" ? t("notifications.low_stock") : t("notifications.expiry_soon")} · {a.sku}
                        </p>
                      </div>
                    </Link>
                  ))}
                </div>
              )
            )}

            <div className="px-3.5 py-2 border-t border-gray-100">
              <Link href={`/${org}/analytics`} onClick={() => setOpen(false)} className="text-xs font-bold text-eth-forest no-underline">
                {t("notifications.mark_all_read")} →
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function LangSwitcher() {
  const [current, setCurrent] = useState<Locale>("en");

  useEffect(() => { setCurrent(getCurrentLocale()); }, []);

  async function switchLocale(loc: Locale) {
    if (loc === current) return;
    setLocale(loc);
    try { await loadLocale(loc); } catch { /* fallback to key */ }
    setCurrent(loc);
    window.location.reload();
  }

  return (
    <div className="flex gap-0.5 bg-white/10 rounded p-0.5">
      {ENABLED_LOCALES.map((loc) => (
        <button
          key={loc}
          onClick={() => void switchLocale(loc)}
          className={`text-[11px] font-bold px-2 py-0.5 rounded border-0 cursor-pointer transition-all ${
            current === loc
              ? "bg-eth-gold text-[#0f2d1f]"
              : "bg-transparent text-white/50 hover:text-white/80"
          }`}
        >
          {t(`lang.${loc}`)}
        </button>
      ))}
    </div>
  );
}

/* ── Brand logo mark ──────────────────────────────────────────────────────── */
function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <rect width="40" height="40" rx="7" fill="#FCDD09" />
      <polygon points="20,4 36,12 36,24 20,32 4,24 4,12" fill="#0f2d1f" />
      <polygon points="20,10 30,16 30,23 20,29 10,23 10,16" fill="#FCDD09" />
      <polygon points="20,16 25,19 25,23 20,26 15,23 15,19" fill="#0f2d1f" />
    </svg>
  );
}

interface ApiTenantRow { id: string; name: string; slug: string | null; organisation_type: string | null }

interface PlanData {
  plan_tier: string;
  feature_flags: Record<string, boolean>;
  max_warehouses: number | null;
  max_users: number | null;
  sku_cap: number | null;
  contract_start: string | null;
  contract_end: string | null;
}

/* ── Sidebar nav ──────────────────────────────────────────────────────────── */
function Sidebar({ user, org, tenantName, plan, onClose, isOpen }: {
  user: SessionUser;
  org: string;
  tenantName?: string;
  plan?: PlanData | null;
  onClose?: () => void;       // called when a nav link is tapped (mobile)
  isOpen?: boolean;           // mobile slide-in state, owned by OrgLayout
}) {
  const router   = useRouter();
  const pathname = usePathname();
  const { contractStatus } = useContractStatus();

  const navItems = org === SA_ORG_SLUG ? SA_NAV : TENANT_NAV;

  // In gateway mode, SA sidebar shows real API tenants instead of hardcoded demo list
  const { data: apiTenants } = useQuery<ApiTenantRow[]>({
    queryKey: ["tenants-list"],
    queryFn: () => api.get<ApiTenantRow[]>("/api/v1/tenants/"),
    enabled: isGatewayMode && org === SA_ORG_SLUG && user.role === "SA",
    staleTime: 0,
    refetchOnMount: true,
  });
  const tenants = org === SA_ORG_SLUG
    ? (isGatewayMode && apiTenants ? [] : DEMO_TENANTS)   // SA sidebar uses API or demo
    : [];

  // Open renewal-requests count — badges the SA nav item that leads to the
  // Renewals tab (hidden when 0).
  const { data: openRenewalRequests } = useQuery<unknown[]>({
    queryKey: ["sa-renewal-requests", "OPEN"],
    queryFn: () => api.get<unknown[]>("/api/v1/tenants/sa/renewal-requests?status=OPEN"),
    enabled: isGatewayMode && org === SA_ORG_SLUG && user.role === "SA",
    staleTime: 0,
    refetchOnMount: true,
  });
  const renewalsOpenCount = openRenewalRequests?.length ?? 0;

  return (
    <aside className={`fixed top-[60px] left-0 bottom-0 w-60 bg-[#0f2d1f] flex flex-col z-40 border-r border-white/[0.06] overflow-hidden transition-transform duration-200 ${
      isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
    }`}>
      {/* User identity */}
      <div className="px-3.5 py-3 border-b border-white/[0.08] bg-white/[0.04] shrink-0">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-extrabold text-white tracking-wide ${ROLE_BADGE[user.role] ?? "bg-gray-500"} px-[7px] py-0.5 rounded shrink-0`}>
            {user.role}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white m-0 truncate">{user.name}</p>
            {user.role === "SA" ? (
              <p className="text-[11px] text-eth-gold mt-px m-0">{t("roles.SA")}</p>
            ) : (
              <p className="text-[11px] text-emerald-300 mt-px m-0 truncate">
                {tenantName ?? (!user.tenantName?.match(/^[0-9a-f-]{36}$/i) ? user.tenantName : org)}
                {user.warehouseName && <span className="text-green-400"> › {user.warehouseName}</span>}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-2">
        {navItems.map((item, idx) => {
          // Role-restricted items: hide if user's role is not in the allowed list
          if (item.roles && !item.roles.includes(user.role)) return null;
          if (item.type === "section") {
            return (
              <p key={idx} className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
                {t(item.label)}
              </p>
            );
          }
          if (item.disabled) {
            return (
              <span
                key={idx}
                className="flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium mb-px text-white/25 border-l-[3px] border-transparent cursor-not-allowed select-none"
                title={t("common.coming_soon_badge")}
              >
                <span className="text-[15px] leading-none shrink-0 opacity-40">{item.icon}</span>
                {t(item.label)}
                <span className="ml-auto text-[9px] font-bold uppercase tracking-wide text-white/20">{t("nav.soon_badge")}</span>
              </span>
            );
          }
          if (item.type === "link" && item.planFlag && plan != null && !plan.feature_flags[item.planFlag]) {
            return (
              <span
                key={idx}
                className="flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium mb-px text-white/25 border-l-[3px] border-transparent cursor-not-allowed select-none"
                title={t("nav.upgrade_to_unlock").replace("{feature}", t(`sa.feature_${item.planFlag}`))}
              >
                <span className="text-[15px] leading-none shrink-0 opacity-40">{item.icon}</span>
                {t(item.label)}
                <span className="ml-auto text-[9px] font-bold uppercase tracking-wide bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded">{t("nav.upgrade_badge")}</span>
              </span>
            );
          }
          const href = `/${org}/${item.page}`;
          const isActive = item.page === "dashboard"
            ? pathname === `/${org}/dashboard`
            : pathname.startsWith(`/${org}/${item.page}`);
          return (
            <Link
              key={idx}
              href={href}
              onClick={() => onClose?.()}
              className={`flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px border-l-[3px] transition-all ${
                isActive
                  ? "bg-eth-gold/[0.12] text-eth-gold border-eth-gold"
                  : "text-white/65 border-transparent hover:bg-white/[0.08] hover:text-white/95"
              }`}
            >
              <span className="text-[15px] leading-none shrink-0">{item.icon}</span>
              {t(item.label)}
              {item.badge === "renewalsOpenCount" && renewalsOpenCount > 0 && (
                <span className="ml-auto text-[10px] font-bold bg-red-500 text-white rounded-full px-1.5 py-0.5 min-w-[18px] text-center shrink-0">
                  {renewalsOpenCount}
                </span>
              )}
            </Link>
          );
        })}

        {/* PLAN_GATE: LOGISTICS — render disabled when !plan?.feature_flags?.LOGISTICS */}
        {/* PLAN_GATE: TRANSFERS_SISTER — render disabled when !plan?.feature_flags?.TRANSFERS_SISTER */}

        {/* SA gateway mode: real API tenants */}
        {isGatewayMode && apiTenants && apiTenants.length > 0 && (
          <>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
              {t("dashboard.tenants_heading")}
            </p>
            {apiTenants.map((ten) => {
              const tenHref = `/${ten.slug ?? ten.id}/dashboard`;
              const tenActive = pathname.startsWith(tenHref);
              return (
                <Link
                  key={ten.id}
                  href={tenHref}
                  onClick={() => onClose?.()}
                  className={`flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px border-l-[3px] transition-all ${
                    tenActive
                      ? "bg-eth-gold/[0.12] text-eth-gold border-eth-gold"
                      : "text-white/65 border-transparent hover:bg-white/[0.08] hover:text-white/95"
                  }`}
                >
                  <span className="text-[15px] leading-none">🏢</span>
                  {ten.name}
                </Link>
              );
            })}
          </>
        )}

        {/* SA demo mode: hardcoded demo tenants */}
        {tenants.length > 0 && (
          <>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
              {t("dashboard.tenants_heading")}
            </p>
            {tenants.map((ten) => {
              const tenHref = `/${ten.slug}/dashboard`;
              const tenActive = pathname.startsWith(tenHref);
              return (
                <Link
                  key={ten.id}
                  href={tenHref}
                  onClick={() => onClose?.()}
                  className={`flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px border-l-[3px] transition-all ${
                    tenActive
                      ? "bg-eth-gold/[0.12] text-eth-gold border-eth-gold"
                      : "text-white/65 border-transparent hover:bg-white/[0.08] hover:text-white/95"
                  }`}
                >
                  <span className="text-[15px] leading-none">{ten.logo}</span>
                  {ten.name}
                </Link>
              );
            })}
          </>
        )}

        {/* Non-SA: back to admin if SA is viewing a tenant */}
        {org !== SA_ORG_SLUG && user.role === "SA" && (
          <>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
              {t("layout.admin_section")}
            </p>
            <Link
              href={`/${SA_ORG_SLUG}/dashboard`}
              onClick={() => onClose?.()}
              className={`flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px border-l-[3px] transition-all ${
                pathname.startsWith(`/${SA_ORG_SLUG}/dashboard`)
                  ? "bg-eth-gold/[0.12] text-eth-gold border-eth-gold"
                  : "text-eth-gold border-transparent hover:bg-white/[0.08]"
              }`}
            >
              <span className="text-[15px]">⬅</span>
              {t("layout.all_tenants")}
            </Link>
          </>
        )}
      </nav>

      {/* Contract expiry notice — TA only, EXPIRING stage only (GRACE/READ_ONLY
          get the top banner shown to all tenant users instead; see OrgLayout). */}
      {user.role === "TA" && contractStatus?.stage === "EXPIRING" && contractStatus.contract_end && (
        <div className="mx-2 mb-1 px-2.5 py-2 rounded text-[11px] bg-amber-800/50 text-amber-200">
          <p className="font-bold m-0">{t("layout.contract_expiring_soon")}</p>
          <p className="m-0 opacity-80">
            {t("layout.contract_ends_days")
              .replace("{date}", contractStatus.contract_end)
              .replace("{n}", String(contractStatus.days_left ?? ""))}
          </p>
        </div>
      )}

      {/* Sign out */}
      <div className="px-2 py-2.5 border-t border-white/[0.08] shrink-0">
        <button
          onClick={() => { logout(); router.push("/login"); }}
          className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded border-0 cursor-pointer text-sm font-medium bg-transparent text-white/40 hover:bg-white/[0.08] hover:text-white/70 transition-all"
        >
          <span className="text-[15px]">🚪</span>
          {t("layout.sign_out")}
        </button>
      </div>
    </aside>
  );
}

/* ── Tenant name + branding resolver ─────────────────────────────────────── */
// Must be rendered inside QueryClientProvider so useQuery works.
function TenantBrandingResolver({
  org,
  onName,
  onLogo,
  onBanner,
}: {
  org: string;
  onName:   (n: string | null) => void;
  onLogo:   (u: string | null) => void;
  onBanner: (u: string | null) => void;
}) {
  const name = useTenantName(org);
  const session = getSession();
  const tenantId = session?.tenantId ?? "";
  const { data } = useQuery<{ id: string; name: string; logo_url?: string | null; banner_url?: string | null }>({
    queryKey: ["tenant-branding", tenantId],
    queryFn:  () => api.get(`/api/v1/tenants/${tenantId}`),
    enabled:  !!tenantId,
    staleTime: 120_000,
    retry: false,
  });
  useEffect(() => { onName(name); }, [name, onName]);
  useEffect(() => { onLogo(data?.logo_url ?? null); }, [data?.logo_url, onLogo]);
  useEffect(() => { onBanner(data?.banner_url ?? null); }, [data?.banner_url, onBanner]);
  return null;
}

function PlanResolver({ onPlan }: { onPlan: (p: PlanData | null) => void }) {
  const session = getSession();
  const tenantId = session?.tenantId ?? "";
  const { data } = useQuery<PlanData>({
    queryKey: ["tenant-plan", tenantId],
    queryFn:  () => api.get<PlanData>("/api/v1/tenants/me/plan"),
    enabled:  isGatewayMode && !!tenantId,
    staleTime: 60_000,
    retry: false,
  });
  useEffect(() => { onPlan(data ?? null); }, [data, onPlan]);
  return null;
}

const PAGE_LABELS: Record<string, string> = {
  dashboard:           "Dashboard",
  products:            "Products",
  warehouses:          "Warehouses",
  lots:                "Lot Traceability",
  inventory:           "Inventory",
  transfers:           "Transfers",
  adjustments:         "Adjustments",
  "stock-count":       "Stock Count",
  analytics:           "Analytics",
  reports:             "Reports",
  "audit-log":         "Audit Log",
  "approval-policies": "Approval Policies",
  "settings/org-setup":"Org Setup",
  "settings/personnel":"Personnel",
  "settings/tenant-admin":"Tenant Admin",
  permissions:         "Permissions",
};

/* ── Layout ───────────────────────────────────────────────────────────────── */
export default function OrgLayout({ children }: { children: React.ReactNode }) {
  const params   = useParams();
  const router   = useRouter();
  const pathname = usePathname();
  const org     = params.org as string;
  const checked = useRef(false);
  const [user, setUser]         = useState<SessionUser | null>(null);
  const [ready, setReady]       = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [apiTenantName, setApiTenantName]     = useState<string | null>(null);
  const [apiLogoUrl,    setApiLogoUrl]         = useState<string | null>(null);
  const [apiBannerUrl,  setApiBannerUrl]       = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen]          = useState(false);
  const [contactOpen, setContactOpen]          = useState(false);
  const [plan, setPlan]                        = useState<PlanData | null>(null);
  const setActiveTenant   = useInventoryStore((s) => s.setActiveTenant);
  const { contractStatus } = useContractStatus();

  // Derive page label from the path segment after /[org]/
  const pageLabel = (() => {
    const after = pathname.replace(`/${org}/`, "");
    // Match longest key first (settings/org-setup before settings)
    const key = Object.keys(PAGE_LABELS)
      .filter(k => after === k || after.startsWith(k + "/") || after.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    return key ? PAGE_LABELS[key] : null;
  })();
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));

  useEffect(() => {
    useInventoryStore.persist.rehydrate();
    try { localStorage.removeItem("smart-audit-log-v1"); } catch { /* storage unavailable */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;

    const session = getSession();
    if (!session) { router.replace(`/login?from=/${org}/dashboard`); return; }
    // SA has tenantId=undefined — only redirect non-SA users missing a tenantId.
    if (!session.tenantId && session.role !== "SA") {
      router.replace(`/login?reason=session_expired`); return;
    }
    // PENDING_SETUP: user has no position yet; force them back to change-password.
    if (session.role === "PENDING_SETUP" || (session.mustResetPassword && session.role !== "SA")) {
      router.replace(`/change-password?userId=${session.id}`); return;
    }
    // Account-owner terms re-acceptance gate — checked after mustResetPassword.
    if (session.termsAcceptanceRequired) {
      router.replace("/accept-terms"); return;
    }

    if (org === SA_ORG_SLUG && session.role !== "SA") {
      router.replace(`/${session.orgSlug}/dashboard`); return;
    }
    if (org !== SA_ORG_SLUG && session.role !== "SA") {
      // Allow both demo tenants (in DEMO_TENANTS) and live API-created tenants
      // (not in DEMO_TENANTS but orgSlug matches the URL org param)
      if (session.orgSlug !== org) {
        router.replace(`/${session.orgSlug}/dashboard`); return;
      }
    }

    setUser(session);
    setReady(true);
    setActiveTenant(org !== SA_ORG_SLUG ? org : "");
    // Tenant name is resolved by TenantNameResolver (rendered inside QueryClientProvider).
  }, [org, router, setActiveTenant]);

  if (!ready || !user) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#0f2d1f]">
        <div className="w-10 h-10 rounded-full border-[3px] border-eth-gold/25 border-t-eth-gold animate-spin" />
        <p className="text-emerald-300 text-sm font-medium">{t("common.loading")}</p>
      </div>
    );
  }

  const firstName = user.name.split(" ")[0] ?? user.name;
  const demoTenant = org !== SA_ORG_SLUG ? DEMO_TENANTS.find((ten) => ten.slug === org) : null;
  // For API-created tenants, show empty string while the real name is loading async.
  // Never fall back to the raw UUID — it flashes confusingly in the header breadcrumb.
  const resolvedName = apiTenantName ?? (
    user.tenantName && !user.tenantName.match(/^[0-9a-f-]{36}$/i)
      ? user.tenantName
      : null
  );
  // Use org slug as fallback while resolvedName is loading — always shows something
  const viewingTenant = demoTenant ?? (org !== SA_ORG_SLUG
    ? { name: resolvedName ?? org, logo: "🏢", slug: org }
    : null);

  return (
    <QueryClientProvider client={qc}>
      {org !== SA_ORG_SLUG && (
        <TenantBrandingResolver
          org={org}
          onName={setApiTenantName}
          onLogo={setApiLogoUrl}
          onBanner={setApiBannerUrl}
        />
      )}
      {org !== SA_ORG_SLUG && <PlanResolver onPlan={setPlan} />}
      <div className="min-h-screen bg-gray-100">
        {/* ── Top banner ── */}
        <header className="fixed top-0 left-0 right-0 z-[60] h-14 bg-[#0f2d1f] flex items-center px-6 gap-4 shadow-[0_2px_12px_rgba(0,0,0,0.35)]">
          {/* Hamburger — mobile only */}
          <button
            onClick={() => setSidebarOpen(prev => !prev)}
            className="md:hidden flex flex-col justify-center items-center w-9 h-9 gap-[5px] rounded border-0 bg-transparent cursor-pointer shrink-0 hover:bg-white/[0.08] transition-all"
            aria-label={t("nav.toggle_menu")}
          >
            <span className={`block w-5 h-0.5 bg-white/70 rounded transition-all duration-200 ${sidebarOpen ? "rotate-45 translate-y-[7px]" : ""}`} />
            <span className={`block w-5 h-0.5 bg-white/70 rounded transition-all duration-200 ${sidebarOpen ? "opacity-0" : ""}`} />
            <span className={`block w-5 h-0.5 bg-white/70 rounded transition-all duration-200 ${sidebarOpen ? "-rotate-45 -translate-y-[7px]" : ""}`} />
          </button>

          {/* Logo */}
          <Link href={`/${user.orgSlug}/dashboard`} className="flex items-center gap-2 no-underline shrink-0">
            <Logo />
            {/* i18n-ignore: brand name */}
            <span className="font-bold text-sm text-white whitespace-nowrap">
              SMART <span className="text-eth-gold font-medium">{t("nav.inventory")}</span>
            </span>
          </Link>

          {/* Centre: org breadcrumb */}
          <div className="flex-1 flex justify-center">
            {viewingTenant ? (
              <span className="text-sm text-white/70 flex items-center gap-1">
                <span className="text-eth-gold font-semibold flex items-center gap-1.5">
                  {apiLogoUrl
                    ? <img src={apiLogoUrl} alt="" className="w-5 h-5 rounded object-cover shrink-0" />
                    : <span>{viewingTenant.logo}</span>
                  }
                  {viewingTenant.name}
                </span>
                {user.warehouseName && (
                  <span className="text-emerald-300"> › {user.warehouseName}</span>
                )}
                {pageLabel && (
                  <span className="text-white/45"> › {pageLabel}</span>
                )}
              </span>
            ) : (
              <span className="text-sm font-semibold text-eth-gold">{t("roles.SA")}</span>
            )}
          </div>

          {/* Right controls */}
          <div className="flex items-center gap-2.5 shrink-0">
            {org !== "admin" && <NotificationBell org={org} />}
            <LangSwitcher />
            <span className={`text-[10px] font-extrabold text-white tracking-wide ${ROLE_BADGE[user.role] ?? "bg-gray-500"} px-2 py-0.5 rounded`}>
              {user.role}
            </span>
            <span className="text-sm text-emerald-100 whitespace-nowrap">
              {t("layout.welcome")},{" "}
              <strong className="text-eth-gold font-bold">{firstName}</strong>
            </span>
            <button
              onClick={() => { logout(); router.push("/login"); }}
              className="text-xs font-semibold text-gray-400 cursor-pointer bg-white/[0.07] border border-white/15 rounded px-3 py-1.5"
            >
              {t("layout.sign_out")}
            </button>
          </div>
        </header>

        {/* Ethiopian stripe */}
        <div
          className="fixed top-14 left-0 right-0 z-[59] h-1"
          style={{ background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)" }}
        />

        {/* Body */}
        <div className="w-full pt-[60px]">
          {/* Mobile overlay — closes sidebar on tap */}
          {sidebarOpen && (
            <div
              className="fixed inset-0 z-[39] bg-black/50 md:hidden"
              onClick={() => setSidebarOpen(false)}
            />
          )}
          <Sidebar user={user} org={org} tenantName={apiTenantName ?? undefined} plan={plan} onClose={() => setSidebarOpen(false)} isOpen={sidebarOpen} />
          <main className="w-full md:w-[calc(100%-240px)] md:ml-60 min-h-[calc(100vh-60px)] overflow-auto bg-gray-100">
            {process.env.NODE_ENV !== "production" && !process.env.NEXT_PUBLIC_API_URL && !bannerDismissed && (
              <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center justify-between gap-3">
                <p className="text-xs text-amber-800 font-medium m-0">⚠ {t("demo.mode_banner")}</p>
                <button
                  onClick={() => setBannerDismissed(true)}
                  className="text-amber-600 border-0 bg-transparent cursor-pointer text-sm font-bold shrink-0 hover:text-amber-900"
                >
                  ✕
                </button>
              </div>
            )}
            {/* Contract grace/read-only banners — all tenant users, never SA. */}
            {org !== SA_ORG_SLUG && contractStatus?.stage === "GRACE" && (
              <div className="bg-amber-50 border-b border-amber-200 px-4 py-2.5 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-amber-900 font-medium m-0 flex-1 min-w-0">
                  ⚠ {t("contract.banner_grace")
                    .replace("{date}", contractStatus.contract_end ?? "")
                    .replace("{read_only_since}", contractStatus.read_only_since ?? "")}
                </p>
                {user.role === "TA" && (
                  <Link
                    href={`/${org}/settings/tenant-admin?tab=plan`}
                    className="text-xs font-bold text-amber-900 underline shrink-0 whitespace-nowrap"
                  >
                    {t("contract.request_renewal_link")}
                  </Link>
                )}
                {user.role === "TA" && (
                  <PublicContactLink
                    className="text-xs font-bold text-amber-900 underline shrink-0 whitespace-nowrap"
                    prefix=" · "
                    onClick={() => setContactOpen(true)}
                  />
                )}
              </div>
            )}
            {org !== SA_ORG_SLUG && contractStatus?.stage === "READ_ONLY" && (
              <div className="bg-red-50 border-b border-red-200 px-4 py-2.5 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-red-900 font-medium m-0 flex-1 min-w-0">
                  ⛔ {t("contract.banner_read_only").replace("{date}", contractStatus.contract_end ?? "")}
                </p>
                {user.role === "TA" && (
                  <Link
                    href={`/${org}/settings/tenant-admin?tab=plan`}
                    className="text-xs font-bold text-red-900 underline shrink-0 whitespace-nowrap"
                  >
                    {t("contract.request_renewal_link")}
                  </Link>
                )}
                {user.role === "TA" && (
                  <PublicContactLink
                    className="text-xs font-bold text-red-900 underline shrink-0 whitespace-nowrap"
                    prefix=" · "
                    onClick={() => setContactOpen(true)}
                  />
                )}
              </div>
            )}
            {children}
          </main>
        </div>
      </div>
      <ContactModal open={contactOpen} onClose={() => setContactOpen(false)} />
      <GlobalToast />
    </QueryClientProvider>
  );
}

/* ── Nav definitions ──────────────────────────────────────────────────────── */
type NavItem =
  | { type: "section"; label: string; roles?: string[] }
  | { type: "link"; icon: string; label: string; page: string; roles?: string[]; disabled?: boolean; planFlag?: string; badge?: "renewalsOpenCount" };

const SA_NAV: NavItem[] = [
  { type: "section", label: "nav.section_overview" },
  { type: "link", icon: "🏠", label: "nav.dashboard", page: "dashboard" },
  { type: "link", icon: "🔔", label: "sa.tab_renewals", page: "dashboard?tab=renewals", badge: "renewalsOpenCount" },
  { type: "section", label: "nav.section_system" },
  { type: "link", icon: "💳", label: "sa.nav_plans_pricing", page: "settings/plans" },
  { type: "link", icon: "☎️", label: "sa.nav_contact", page: "settings/contact" },
  // These pages are planned but not yet built — links are intentionally
  // disabled until the pages exist. Do not remove; placeholder only.
  { type: "link", icon: "🔐", label: "nav.permissions", page: "dashboard", disabled: true },
  { type: "link", icon: "📋", label: "nav.audit",       page: "dashboard", disabled: true },
  { type: "link", icon: "❓", label: "nav.help",        page: "help" },
];

// NAV ORDER: Do not change without updating PRD-APPENDIX.md §A — confirmed structure.
// All labels are i18n keys rendered via t(item.label) — never hardcode English in JSX.
const TENANT_NAV: NavItem[] = [
  { type: "section", label: "nav.section_inventory" },
  { type: "link", icon: "🏠", label: "nav.dashboard",        page: "dashboard"         },
  { type: "link", icon: "🏭", label: "nav.products",         page: "products"          },
  { type: "link", icon: "🏗️", label: "nav.warehouses",       page: "warehouses"        },
  { type: "link", icon: "🔍", label: "nav.lot_traceability", page: "lots"              },
  { type: "section", label: "nav.section_operations" },
  { type: "link", icon: "📦", label: "nav.inventory",        page: "inventory"         },
  { type: "link", icon: "🔄", label: "nav.transfers",        page: "transfers"         },
  { type: "link", icon: "📋", label: "nav.adjustments",      page: "adjustments"       },
  { type: "link", icon: "🔢", label: "nav.stock_count",      page: "stock-count"       },
  { type: "section", label: "nav.section_reports" },
  { type: "link", icon: "📈", label: "nav.analytics",        page: "analytics",        planFlag: "AI_ANALYTICS" },
  { type: "link", icon: "📊", label: "nav.reports",          page: "reports"           },
  { type: "link", icon: "📋", label: "nav.audit",            page: "audit-log"         },
  { type: "link", icon: "📜", label: "nav.approval_policies", page: "approval-policies" },
  { type: "section", label: "nav.settings", roles: ["SA", "TA"] },
  { type: "link", icon: "🏢", label: "nav.org_setup",        page: "settings/org-setup",  roles: ["SA", "TA"] },
  { type: "link", icon: "👥", label: "nav.personnel",        page: "settings/personnel",  roles: ["SA", "TA"] },
  { type: "link", icon: "⚙️",  label: "nav.tenant_admin",    page: "settings/tenant-admin", roles: ["TA"] },
  { type: "section", label: "nav.help_section" },
  { type: "link", icon: "❓", label: "nav.help",            page: "help" },
];
