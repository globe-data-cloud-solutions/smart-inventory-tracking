"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { cn } from "@/lib/utils";

interface SidebarProps {
  user: SessionUser;
}

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const navItems =
    user.role === "SA"
      ? SA_NAV
      : getTenantNav(user.tenantId ?? "");

  return (
    <aside className="fixed inset-y-0 left-0 w-64 bg-slate-900 flex flex-col z-40">
      {/* Logo */}
      <div className="h-16 flex items-center gap-3 px-5 border-b border-white/10">
        <div className="w-8 h-8 rounded-lg bg-brand-500 flex items-center justify-center flex-shrink-0">
          <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5 text-white" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0v10l-8 4m0-14L4 17m8 4V11" />
          </svg>
        </div>
        <span className="text-white font-semibold text-sm truncate">SMART Inventory</span>
      </div>

      {/* User badge */}
      <div className="mx-3 mt-4 p-3 rounded-lg bg-white/5 border border-white/10">
        <p className="text-white text-sm font-medium truncate">{user.name}</p>
        <div className="flex items-center gap-2 mt-1">
          <RoleBadge role={user.role} />
          {user.warehouseName && (
            <p className="text-slate-400 text-xs truncate">📍 {user.warehouseName}</p>
          )}
          {user.tenantName && !user.warehouseName && (
            <p className="text-slate-400 text-xs truncate">{user.tenantName}</p>
          )}
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          if (item.type === "section") {
            return (
              <p key={item.label} className="px-3 pt-4 pb-1 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                {item.label}
              </p>
            );
          }
          const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href ?? ""));
          return (
            <Link
              key={item.label}
              href={item.href ?? "#"}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                active
                  ? "bg-brand-600 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              )}
            >
              <span className="text-lg leading-none">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}

        {/* Tenant links for SA */}
        {user.role === "SA" && (
          <>
            <p className="px-3 pt-4 pb-1 text-xs font-semibold text-slate-500 uppercase tracking-wider">Tenants</p>
            {DEMO_TENANTS.map((t) => (
              <Link
                key={t.id}
                href={`/dashboard/tenants/${t.slug}`}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  pathname === `/dashboard/tenants/${t.slug}`
                    ? "bg-brand-600 text-white"
                    : "text-slate-300 hover:bg-white/10 hover:text-white"
                )}
              >
                <span className="text-lg">{t.logo}</span>
                {t.name}
              </Link>
            ))}
          </>
        )}
      </nav>

      {/* Logout */}
      <div className="p-3 border-t border-white/10">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-white/10 hover:text-white transition-colors"
        >
          <span className="text-lg">🚪</span>
          Sign out
        </button>
      </div>
    </aside>
  );
}

function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, string> = {
    SA:  "bg-red-500",
    TA:  "bg-purple-500",
    NM:  "bg-blue-500",
    RM:  "bg-indigo-500",
    WM:  "bg-teal-500",
    LM:  "bg-cyan-500",
    AU:  "bg-gray-500",
    SYS: "bg-orange-500",
  };
  return (
    <span className={cn("text-xs text-white px-1.5 py-0.5 rounded font-medium", colors[role] ?? "bg-gray-500")}>
      {role}
    </span>
  );
}

const SA_NAV = [
  { type: "section",  label: "Overview" },
  { type: "link", icon: "🏠", label: "Dashboard",     href: "/dashboard" },
  { type: "link", icon: "📊", label: "All Tenants",   href: "/dashboard" },
  { type: "section",  label: "System" },
  { type: "link", icon: "🔐", label: "Permissions",   href: "/dashboard" },
  { type: "link", icon: "📋", label: "Audit Logs",    href: "/dashboard" },
  { type: "link", icon: "⚙️", label: "Settings",      href: "/dashboard" },
];

function getTenantNav(tenantId: string) {
  return [
    { type: "section",  label: "Inventory" },
    { type: "link", icon: "🏠", label: "Dashboard",     href: "/dashboard" },
    { type: "link", icon: "📦", label: "Inventory",     href: "/dashboard/inventory" },
    { type: "link", icon: "🏭", label: "Products",      href: "/dashboard/products" },
    { type: "link", icon: "🏗️", label: "Warehouses",    href: "/dashboard" },
    { type: "section",  label: "Operations" },
    { type: "link", icon: "🔄", label: "Transfers",     href: "/dashboard" },
    { type: "link", icon: "📋", label: "Adjustments",   href: "/dashboard" },
    { type: "link", icon: "🔢", label: "Stock Count",   href: "/dashboard" },
    { type: "section",  label: "Reports" },
    { type: "link", icon: "📈", label: "Analytics",     href: "/dashboard/analytics" },
    { type: "link", icon: "📊", label: "Reports",       href: "/dashboard/reports" },
    { type: "link", icon: "🔍", label: "Audit Log",     href: "/dashboard" },
  ];
}
