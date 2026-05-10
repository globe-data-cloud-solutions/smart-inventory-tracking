"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";

interface SidebarProps {
  user: SessionUser;
}

const ROLE_COLORS: Record<string, string> = {
  SA:  "#DC2626", TA: "#7C3AED", NM: "#2563EB",
  RM:  "#0D9488", WM: "#059669", LM: "#0891B2",
  AU:  "#6B7280", SYS:"#D97706",
};

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();
  const router   = useRouter();

  const handleLogout = () => { logout(); router.push("/login"); };

  const navItems = user.role === "SA" ? SA_NAV : TENANT_NAV;

  return (
    /*
     * Sidebar starts at top: 60px (56px header + 4px Ethiopian stripe).
     * No logo here — the header already carries the brand mark.
     * User identity sits at the very top so it's immediately visible.
     */
    <aside
      style={{
        position: "fixed",
        top: 60,           /* sits directly below the header + stripe */
        left: 0,
        bottom: 0,
        width: 240,
        background: "#0f2d1f",
        display: "flex",
        flexDirection: "column",
        zIndex: 40,
        borderRight: "1px solid rgba(255,255,255,0.06)",
        overflow: "hidden",
      }}
    >
      {/* ── User identity — top of sidebar, always visible ── */}
      <div style={{
        padding: "12px 14px",
        borderBottom: "1px solid rgba(255,255,255,0.08)",
        background: "rgba(255,255,255,0.04)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Role badge */}
          <span style={{
            fontSize: 10, fontWeight: 800, color: "#fff", letterSpacing: "0.04em",
            background: ROLE_COLORS[user.role] ?? "#6B7280",
            padding: "2px 7px", borderRadius: 3, flexShrink: 0,
          }}>
            {user.role}
          </span>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: "#fff", margin: 0,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {user.name}
            </p>
            {user.tenantName && (
              <p style={{ fontSize: 11, color: "#6ee7b7", margin: 0, marginTop: 1,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {user.tenantName}
                {user.warehouseName && <span style={{ color: "#4ade80" }}> › {user.warehouseName}</span>}
              </p>
            )}
            {user.role === "SA" && (
              <p style={{ fontSize: 11, color: "#FCDD09", margin: 0, marginTop: 1 }}>
                All tenants
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── Navigation ── */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "8px 8px" }}>
        {navItems.map((item, idx) => {
          if (item.type === "section") {
            return (
              <p key={idx} style={{
                fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: "0.08em", color: "rgba(255,255,255,0.3)",
                padding: "14px 10px 4px", margin: 0,
              }}>
                {item.label}
              </p>
            );
          }
          const active = item.href === "/dashboard"
            ? pathname === "/dashboard"
            : pathname.startsWith(item.href ?? "NOMATCH");
          return (
            <Link key={idx} href={item.href ?? "#"} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "8px 10px", borderRadius: 5,
              fontSize: 13, fontWeight: 500, textDecoration: "none",
              marginBottom: 1,
              background: active ? "rgba(252,221,9,0.12)" : "transparent",
              color: active ? "#FCDD09" : "rgba(255,255,255,0.65)",
              borderLeft: active ? "3px solid #FCDD09" : "3px solid transparent",
              transition: "all 0.12s",
            }}>
              <span style={{ fontSize: 15, lineHeight: 1, flexShrink: 0 }}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}

        {/* SA-only: tenant quick links */}
        {user.role === "SA" && (
          <>
            <p style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.08em", color: "rgba(255,255,255,0.3)",
              padding: "14px 10px 4px", margin: 0,
            }}>
              Tenants
            </p>
            {DEMO_TENANTS.map((t) => {
              const active = pathname === `/dashboard/tenants/${t.slug}`;
              return (
                <Link key={t.id} href={`/dashboard/tenants/${t.slug}`} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 10px", borderRadius: 5,
                  fontSize: 13, fontWeight: 500, textDecoration: "none",
                  marginBottom: 1,
                  background: active ? "rgba(252,221,9,0.12)" : "transparent",
                  color: active ? "#FCDD09" : "rgba(255,255,255,0.65)",
                  borderLeft: active ? "3px solid #FCDD09" : "3px solid transparent",
                  transition: "all 0.12s",
                }}>
                  <span style={{ fontSize: 15, lineHeight: 1 }}>{t.logo}</span>
                  {t.name}
                </Link>
              );
            })}
          </>
        )}
      </nav>

      {/* ── Sign out ── */}
      <div style={{ padding: "10px 8px", borderTop: "1px solid rgba(255,255,255,0.08)", flexShrink: 0 }}>
        <button
          onClick={handleLogout}
          style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10,
            padding: "8px 10px", borderRadius: 5, border: "none", cursor: "pointer",
            fontSize: 13, fontWeight: 500, textAlign: "left",
            background: "transparent", color: "rgba(255,255,255,0.4)",
            transition: "all 0.12s",
          }}
        >
          <span style={{ fontSize: 15 }}>🚪</span>
          Sign out
        </button>
      </div>
    </aside>
  );
}

const SA_NAV = [
  { type: "section", label: "Overview" },
  { type: "link", icon: "🏠", label: "Dashboard",   href: "/dashboard" },
  { type: "section", label: "System" },
  { type: "link", icon: "🔐", label: "Permissions", href: "/dashboard" },
  { type: "link", icon: "📋", label: "Audit Logs",  href: "/dashboard" },
  { type: "link", icon: "⚙️", label: "Settings",    href: "/dashboard" },
];

const TENANT_NAV = [
  { type: "section", label: "Inventory" },
  { type: "link", icon: "🏠", label: "Dashboard",   href: "/dashboard" },
  { type: "link", icon: "📦", label: "Inventory",   href: "/dashboard/inventory" },
  { type: "link", icon: "🏭", label: "Products",    href: "/dashboard/products" },
  { type: "link", icon: "🏗️", label: "Warehouses",  href: "/dashboard" },
  { type: "section", label: "Operations" },
  { type: "link", icon: "🔄", label: "Transfers",   href: "/dashboard" },
  { type: "link", icon: "📋", label: "Adjustments", href: "/dashboard" },
  { type: "link", icon: "🔢", label: "Stock Count", href: "/dashboard" },
  { type: "section", label: "Reports" },
  { type: "link", icon: "📈", label: "Analytics",   href: "/dashboard/analytics" },
  { type: "link", icon: "📊", label: "Reports",     href: "/dashboard/reports" },
  { type: "link", icon: "🔍", label: "Audit Log",   href: "/dashboard" },
];
