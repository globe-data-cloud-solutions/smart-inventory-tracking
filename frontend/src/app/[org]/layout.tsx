"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { getSession, logout, SA_ORG_SLUG, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";

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

/* ── Sidebar nav ──────────────────────────────────────────────────────────── */
const ROLE_COLORS: Record<string, string> = {
  SA: "#DC2626", TA: "#7C3AED", NM: "#2563EB",
  RM: "#0D9488", WM: "#059669", LM: "#0891B2",
  AU: "#6B7280", SYS: "#D97706",
};

function Sidebar({ user, org }: { user: SessionUser; org: string }) {
  const router = useRouter();

  const navItems = org === SA_ORG_SLUG ? SA_NAV : TENANT_NAV;
  const tenants  = org === SA_ORG_SLUG ? DEMO_TENANTS : [];

  return (
    <aside style={{
      position: "fixed", top: 60, left: 0, bottom: 0, width: 240,
      background: "#0f2d1f", display: "flex", flexDirection: "column",
      zIndex: 40, borderRight: "1px solid rgba(255,255,255,0.06)", overflow: "hidden",
    }}>
      {/* User identity */}
      <div style={{
        padding: "12px 14px", borderBottom: "1px solid rgba(255,255,255,0.08)",
        background: "rgba(255,255,255,0.04)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontSize: 10, fontWeight: 800, color: "#fff", letterSpacing: "0.04em",
            background: ROLE_COLORS[user.role] ?? "#6B7280",
            padding: "2px 7px", borderRadius: 3, flexShrink: 0,
          }}>{user.role}</span>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: "#fff", margin: 0,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {user.name}
            </p>
            {user.role === "SA" ? (
              <p style={{ fontSize: 11, color: "#FCDD09", margin: "1px 0 0" }}>
                System Administrator
              </p>
            ) : (
              <p style={{ fontSize: 11, color: "#6ee7b7", margin: "1px 0 0",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {user.tenantName}
                {user.warehouseName && <span style={{ color: "#4ade80" }}> › {user.warehouseName}</span>}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
        {navItems.map((item, idx) => {
          if (item.type === "section") {
            return (
              <p key={idx} style={{
                fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: "0.08em", color: "rgba(255,255,255,0.3)",
                padding: "14px 10px 4px", margin: 0,
              }}>{item.label}</p>
            );
          }
          const href = `/${org}/${item.page}`;
          return (
            <Link key={idx} href={href} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 10px", borderRadius: 5,
              fontSize: 13, fontWeight: 500, textDecoration: "none",
              marginBottom: 1, transition: "all 0.12s",
              color: "rgba(255,255,255,0.65)",
            }}
              className="sidebar-link"
            >
              <span style={{ fontSize: 15, lineHeight: 1, flexShrink: 0 }}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}

        {/* SA: quick links to all tenants */}
        {tenants.length > 0 && (
          <>
            <p style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.08em", color: "rgba(255,255,255,0.3)",
              padding: "14px 10px 4px", margin: 0,
            }}>Tenants</p>
            {tenants.map((t) => (
              <Link key={t.id} href={`/${t.slug}/dashboard`} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 10px", borderRadius: 5,
                fontSize: 13, fontWeight: 500, textDecoration: "none",
                marginBottom: 1, color: "rgba(255,255,255,0.65)", transition: "all 0.12s",
              }}
                className="sidebar-link"
              >
                <span style={{ fontSize: 15, lineHeight: 1 }}>{t.logo}</span>
                {t.name}
              </Link>
            ))}
          </>
        )}

        {/* Non-SA: back to admin link if SA is viewing a tenant */}
        {org !== SA_ORG_SLUG && user.role === "SA" && (
          <>
            <p style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.08em", color: "rgba(255,255,255,0.3)",
              padding: "14px 10px 4px", margin: 0,
            }}>Admin</p>
            <Link href={`/${SA_ORG_SLUG}/dashboard`} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 10px", borderRadius: 5,
              fontSize: 13, fontWeight: 500, textDecoration: "none",
              marginBottom: 1, color: "#FCDD09", transition: "all 0.12s",
            }}>
              <span style={{ fontSize: 15 }}>⬅</span>
              All Tenants
            </Link>
          </>
        )}
      </nav>

      {/* Sign out */}
      <div style={{ padding: "10px 8px", borderTop: "1px solid rgba(255,255,255,0.08)", flexShrink: 0 }}>
        <button
          onClick={() => { logout(); router.push("/login"); }}
          style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10,
            padding: "8px 10px", borderRadius: 5, border: "none", cursor: "pointer",
            fontSize: 13, fontWeight: 500, background: "transparent",
            color: "rgba(255,255,255,0.4)", transition: "all 0.12s",
          }}
        >
          <span style={{ fontSize: 15 }}>🚪</span>
          Sign out
        </button>
      </div>
    </aside>
  );
}

/* ── Layout ───────────────────────────────────────────────────────────────── */
export default function OrgLayout({ children }: { children: React.ReactNode }) {
  const params   = useParams();
  const router   = useRouter();
  const org      = params.org as string;
  const checked  = useRef(false);
  const [user, setUser]   = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);
  const [qc]              = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;

    const session = getSession();
    if (!session) {
      router.replace(`/login?from=/${org}/dashboard`);
      return;
    }

    // Access control:
    //   "admin" org → SA only
    //   tenant org  → SA (any) OR the user whose orgSlug matches
    if (org === SA_ORG_SLUG && session.role !== "SA") {
      router.replace(`/${session.orgSlug}/dashboard`);
      return;
    }
    if (org !== SA_ORG_SLUG && session.role !== "SA") {
      // Verify the org matches a real tenant slug
      const tenant = DEMO_TENANTS.find((t) => t.slug === org);
      if (!tenant) {
        router.replace(`/${session.orgSlug}/dashboard`);
        return;
      }
      // Non-SA user must belong to this tenant
      if (session.orgSlug !== org) {
        router.replace(`/${session.orgSlug}/dashboard`);
        return;
      }
    }

    setUser(session);
    setReady(true);
  }, [org, router]);

  if (!ready || !user) {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 16,
        background: "#0f2d1f",
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: "50%",
          border: "3px solid rgba(252,221,9,0.25)", borderTopColor: "#FCDD09",
          animation: "spin 0.8s linear infinite",
        }} />
        <p style={{ color: "#6ee7b7", fontSize: 14, fontWeight: 500 }}>Loading…</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  const firstName = user.name.split(" ")[0] ?? user.name;

  // Resolve display tenant name for the org being viewed
  const viewingTenant = org !== SA_ORG_SLUG
    ? DEMO_TENANTS.find((t) => t.slug === org)
    : null;

  return (
    <QueryClientProvider client={qc}>
    <div style={{ minHeight: "100vh", background: "#F3F4F6" }}>

      {/* ── Top banner ── */}
      <header style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 60,
        height: 56, background: "#0f2d1f",
        display: "flex", alignItems: "center", padding: "0 1.5rem", gap: "1rem",
        boxShadow: "0 2px 12px rgba(0,0,0,0.35)",
      }}>
        {/* Logo */}
        <Link href={`/${user.orgSlug}/dashboard`} style={{
          display: "flex", alignItems: "center", gap: 8,
          textDecoration: "none", flexShrink: 0,
        }}>
          <Logo />
          <span style={{ fontWeight: 700, fontSize: 14, color: "#fff", whiteSpace: "nowrap" }}>
            SMART{" "}
            <span style={{ color: "#FCDD09", fontWeight: 500 }}>Inventory</span>
          </span>
        </Link>

        {/* Centre: org breadcrumb */}
        <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
          {viewingTenant ? (
            <span style={{ fontSize: 13, color: "rgba(255,255,255,0.7)" }}>
              <span style={{ color: "#FCDD09", fontWeight: 600 }}>{viewingTenant.logo} {viewingTenant.name}</span>
              {user.warehouseName && (
                <span style={{ color: "#6ee7b7" }}> › {user.warehouseName}</span>
              )}
            </span>
          ) : (
            <span style={{ fontSize: 13, fontWeight: 600, color: "#FCDD09" }}>
              System Administrator
            </span>
          )}
        </div>

        {/* Right: role · welcome · sign out */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span style={{
            fontSize: 10, fontWeight: 800, color: "#fff", letterSpacing: "0.04em",
            background: ROLE_COLORS[user.role] ?? "#6B7280",
            padding: "3px 8px", borderRadius: 3,
          }}>{user.role}</span>
          <span style={{ fontSize: 13, color: "#d1fae5", whiteSpace: "nowrap" }}>
            Welcome,{" "}
            <strong style={{ color: "#FCDD09", fontWeight: 700 }}>{firstName}</strong>
          </span>
          <button
            onClick={() => { logout(); router.push("/login"); }}
            style={{
              fontSize: 12, fontWeight: 600, color: "#9CA3AF", cursor: "pointer",
              background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: 4, padding: "5px 12px",
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Ethiopian stripe */}
      <div style={{
        position: "fixed", top: 56, left: 0, right: 0, zIndex: 59, height: 4,
        background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)",
      }} />

      {/* Body */}
      <div style={{ display: "flex", paddingTop: 60 }}>
        <Sidebar user={user} org={org} />
        <main style={{
          flex: 1, marginLeft: 240, minHeight: "calc(100vh - 60px)",
          overflow: "auto", background: "#F3F4F6",
        }}>
          {children}
        </main>
      </div>

      <style>{`
        .sidebar-link:hover {
          background: rgba(255,255,255,0.08) !important;
          color: rgba(255,255,255,0.95) !important;
        }
      `}</style>
    </div>
    </QueryClientProvider>
  );
}

/* ── Nav definitions ──────────────────────────────────────────────────────── */
const SA_NAV = [
  { type: "section", label: "Overview" },
  { type: "link", icon: "🏠", label: "Dashboard",   page: "dashboard" },
  { type: "section", label: "System" },
  { type: "link", icon: "🔐", label: "Permissions", page: "dashboard" },
  { type: "link", icon: "📋", label: "Audit Logs",  page: "dashboard" },
];

const TENANT_NAV = [
  { type: "section", label: "Inventory" },
  { type: "link", icon: "🏠", label: "Dashboard",   page: "dashboard"   },
  { type: "link", icon: "📦", label: "Inventory",   page: "inventory"   },
  { type: "link", icon: "🏭", label: "Products",    page: "products"    },
  { type: "link", icon: "🏗️", label: "Warehouses",  page: "warehouses"  },
  { type: "section", label: "Operations" },
  { type: "link", icon: "🔄", label: "Transfers",   page: "transfers"   },
  { type: "link", icon: "📋", label: "Adjustments", page: "adjustments" },
  { type: "link", icon: "🔢", label: "Stock Count", page: "dashboard"   },
  { type: "section", label: "Reports" },
  { type: "link", icon: "📈", label: "Analytics",   page: "analytics"   },
  { type: "link", icon: "📊", label: "Reports",     page: "reports"     },
  { type: "link", icon: "🔍", label: "Audit Log",   page: "dashboard"   },
];
