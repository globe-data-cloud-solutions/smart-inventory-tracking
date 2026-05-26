"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { logout, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;

interface RealTenant {
  id: string;
  name: string;
  organisation_type: string | null;
  is_active: boolean;
}

interface SidebarProps { user: SessionUser; }

const ROLE_BADGE: Record<string, string> = {
  SA: "bg-red-600", TA: "bg-violet-600", NM: "bg-blue-600", RM: "bg-teal-600",
  WM: "bg-emerald-600", LM: "bg-cyan-600", AU: "bg-gray-500", SYS: "bg-amber-600",
};

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();
  const router   = useRouter();
  const handleLogout = () => { logout(); router.push("/login"); };
  const navItems = user.role === "SA" ? SA_NAV : TENANT_NAV;

  const [realTenants, setRealTenants] = useState<RealTenant[]>([]);
  useEffect(() => {
    if (user.role === "SA" && isGatewayMode) {
      api.get<RealTenant[]>("/api/v1/tenants/")
        .then((data) => setRealTenants(data))
        .catch(() => { /* silently ignore — show demo tenants as fallback */ });
    }
  }, [user.role]);

  const linkCls = (active: boolean) =>
    `flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-medium no-underline mb-px border-l-[3px] transition-all ${
      active
        ? "bg-eth-gold/[0.12] text-eth-gold border-eth-gold"
        : "text-white/65 border-transparent hover:bg-white/[0.08] hover:text-white/95"
    }`;

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
            {user.tenantName && (
              <p className="text-[11px] text-emerald-300 m-0 mt-px truncate">
                {user.tenantName}
                {user.warehouseName && <span className="text-green-400"> › {user.warehouseName}</span>}
              </p>
            )}
            {user.role === "SA" && (
              <p className="text-[11px] text-eth-gold m-0 mt-px">{t("dashboard.tenants_heading")}</p>
            )}
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-2">
        {navItems.map((item, idx) => {
          if (item.type === "section") {
            return (
              <p key={idx} className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
                {item.label}
              </p>
            );
          }
          const active = item.href === "/dashboard"
            ? pathname === "/dashboard"
            : pathname.startsWith(item.href ?? "NOMATCH");
          return (
            <Link key={idx} href={item.href ?? "#"} className={linkCls(active)}>
              <span className="text-[15px] leading-none shrink-0">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}

        {user.role === "SA" && (
          <>
            <p className="text-[10px] font-bold uppercase tracking-widest text-white/30 px-2.5 pt-3.5 pb-1 m-0">
              {t("dashboard.tenants_heading")}
            </p>
            {isGatewayMode ? (
              realTenants.map((ten) => {
                const active = pathname.startsWith(`/${ten.id}/`);
                return (
                  <Link key={ten.id} href={`/${ten.id}/dashboard`} className={linkCls(active)}>
                    <span className="text-[15px] leading-none">🏢</span>
                    {ten.name}
                  </Link>
                );
              })
            ) : (
              DEMO_TENANTS.map((ten) => {
                const active = pathname === `/dashboard/tenants/${ten.slug}`;
                return (
                  <Link key={ten.id} href={`/dashboard/tenants/${ten.slug}`} className={linkCls(active)}>
                    <span className="text-[15px] leading-none">{ten.logo}</span>
                    {ten.name}
                  </Link>
                );
              })
            )}
          </>
        )}
      </nav>

      {/* Sign out */}
      <div className="px-2 py-2.5 border-t border-white/[0.08] shrink-0">
        <button onClick={handleLogout}
          className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded border-0 cursor-pointer text-sm font-medium bg-transparent text-white/40 hover:bg-white/[0.08] hover:text-white/70 transition-all text-left">
          <span className="text-[15px]">🚪</span>
          {t("layout.sign_out")}
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
