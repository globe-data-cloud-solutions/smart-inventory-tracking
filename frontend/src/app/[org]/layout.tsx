"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { getSession, logout, SA_ORG_SLUG, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS, getLowStockProducts } from "@/lib/demo-data";
import { api } from "@/lib/api";
import { getCurrentLocale, setLocale, loadLocale, t } from "@/lib/i18n";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { useTenantName } from "@/hooks/useTenantName";

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
          "/api/v1/inventory/alerts?alert_type=AUTO_APPROVAL_NOTICE"
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
                          Auto-approved: {a.transfer_type} transfer {a.transfer_ref}
                        </p>
                        <p className="text-xs text-gray-500 m-0 mt-0.5">
                          {a.quantity.toLocaleString()} units {a.product_name} — {a.warehouse_name}
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
      {(["en", "am", "or"] as Locale[]).map((loc) => (
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

/* ── Sidebar nav ──────────────────────────────────────────────────────────── */
function Sidebar({ user, org, tenantName }: { user: SessionUser; org: string; tenantName?: string }) {
  const router = useRouter();

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

  return (
    <aside className="fixed top-[60px] left-0 bottom-0 w-60 bg-[#0f2d1f] flex flex-col z-40 border-r border-white/[0.06] overflow-hidden">
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
                {item.label}
              </p>
            );
          }
          const href = `/${org}/${item.page}`;
          return (
            <Link
              key={idx}
              href={href}
              className="flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px text-white/65 hover:bg-white/[0.08] hover:text-white/95 transition-all"
            >
              <span className="text-[15px] leading-none shrink-0">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}

        {/* SA gateway mode: real API tenants */}
        {isGatewayMode && apiTenants && apiTenants.length > 0 && (
          <>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
              {t("dashboard.tenants_heading")}
            </p>
            {apiTenants.map((ten) => (
              <Link
                key={ten.id}
                href={`/${ten.slug ?? ten.id}/dashboard`}
                className="flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px text-white/65 hover:bg-white/[0.08] hover:text-white/95 transition-all"
              >
                <span className="text-[15px] leading-none">🏢</span>
                {ten.name}
              </Link>
            ))}
          </>
        )}

        {/* SA demo mode: hardcoded demo tenants */}
        {tenants.length > 0 && (
          <>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
              {t("dashboard.tenants_heading")}
            </p>
            {tenants.map((ten) => (
              <Link
                key={ten.id}
                href={`/${ten.slug}/dashboard`}
                className="flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px text-white/65 hover:bg-white/[0.08] hover:text-white/95 transition-all"
              >
                <span className="text-[15px] leading-none">{ten.logo}</span>
                {ten.name}
              </Link>
            ))}
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
              className="flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px text-eth-gold hover:bg-white/[0.08] transition-all"
            >
              <span className="text-[15px]">⬅</span>
              {t("layout.all_tenants")}
            </Link>
          </>
        )}
      </nav>

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

/* ── Tenant name resolver ─────────────────────────��───────────────────────── */
// Must be rendered inside QueryClientProvider so useTenantName's useQuery works.
function TenantNameResolver({ org, onName }: { org: string; onName: (n: string | null) => void }) {
  const name = useTenantName(org);
  useEffect(() => { onName(name); }, [name, onName]);
  return null;
}

/* ── Layout ───────────────────────────────────────────────────────────────── */
export default function OrgLayout({ children }: { children: React.ReactNode }) {
  const params  = useParams();
  const router  = useRouter();
  const org     = params.org as string;
  const checked = useRef(false);
  const [user, setUser]         = useState<SessionUser | null>(null);
  const [ready, setReady]       = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [apiTenantName, setApiTenantName] = useState<string | null>(null);
  const setActiveTenant   = useInventoryStore((s) => s.setActiveTenant);
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));

  useEffect(() => {
    useInventoryStore.persist.rehydrate();
    useAuditStore.persist.rehydrate();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;

    const session = getSession();
    if (!session) { router.replace(`/login?from=/${org}/dashboard`); return; }

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
      {org !== SA_ORG_SLUG && <TenantNameResolver org={org} onName={setApiTenantName} />}
      <div className="min-h-screen bg-gray-100">
        {/* ── Top banner ── */}
        <header className="fixed top-0 left-0 right-0 z-[60] h-14 bg-[#0f2d1f] flex items-center px-6 gap-4 shadow-[0_2px_12px_rgba(0,0,0,0.35)]">
          {/* Logo */}
          <Link href={`/${user.orgSlug}/dashboard`} className="flex items-center gap-2 no-underline shrink-0">
            <Logo />
            <span className="font-bold text-sm text-white whitespace-nowrap">
              SMART <span className="text-eth-gold font-medium">{t("nav.inventory")}</span>
            </span>
          </Link>

          {/* Centre: org breadcrumb */}
          <div className="flex-1 flex justify-center">
            {viewingTenant ? (
              <span className="text-sm text-white/70">
                <span className="text-eth-gold font-semibold">{viewingTenant.logo} {viewingTenant.name}</span>
                {user.warehouseName && (
                  <span className="text-emerald-300"> › {user.warehouseName}</span>
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
        <div className="flex pt-[60px]">
          <Sidebar user={user} org={org} tenantName={apiTenantName ?? undefined} />
          <main className="flex-1 ml-60 min-h-[calc(100vh-60px)] overflow-auto bg-gray-100">
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
            {children}
          </main>
        </div>
      </div>
    </QueryClientProvider>
  );
}

/* ── Nav definitions ──────────────────────────────────────────────────────── */
type NavItem =
  | { type: "section"; label: string; roles?: string[] }
  | { type: "link"; icon: string; label: string; page: string; roles?: string[] };

const SA_NAV: NavItem[] = [
  { type: "section", label: "Overview" },
  { type: "link", icon: "🏠", label: "Dashboard",   page: "dashboard"   },
  { type: "section", label: "System" },
  { type: "link", icon: "🔐", label: "Permissions", page: "permissions" },
  { type: "link", icon: "📋", label: "Audit Log",   page: "audit-log"   },
];

const TENANT_NAV: NavItem[] = [
  { type: "section", label: "Inventory" },
  { type: "link", icon: "🏠", label: "Dashboard",       page: "dashboard"         },
  { type: "link", icon: "🏭", label: "Products",        page: "products"          },
  { type: "link", icon: "🏗️", label: "Warehouses",      page: "warehouses"        },
  { type: "link", icon: "🔍", label: "Lot Traceability",page: "lots"              },
  { type: "section", label: "Operations" },
  { type: "link", icon: "📦", label: "Inventory",       page: "inventory"         },
  { type: "link", icon: "🔄", label: "Transfers",       page: "transfers"         },
  { type: "link", icon: "📋", label: "Adjustments",     page: "adjustments"       },
  { type: "link", icon: "🔢", label: "Stock Count",     page: "stock-count"       },
  { type: "link", icon: "🚚", label: "Dispatch",        page: "dispatch"          },
  { type: "section", label: "Reports" },
  { type: "link", icon: "📈", label: "Analytics",       page: "analytics"         },
  { type: "link", icon: "📊", label: "Reports",         page: "reports"           },
  { type: "link", icon: "📋", label: "Audit Log",       page: "audit-log"         },
  { type: "section", label: "Settings", roles: ["SA", "TA"] },
  { type: "link", icon: "🏢", label: "Org Setup",       page: "settings/org-setup",  roles: ["SA", "TA"] },
  { type: "link", icon: "👥", label: "Personnel",       page: "settings/personnel",  roles: ["SA", "TA"] },
];
