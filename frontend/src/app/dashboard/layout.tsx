"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { getSession, logout, type SessionUser } from "@/lib/demo-auth";
import { Sidebar } from "@/components/layout/Sidebar";
import { t } from "@/lib/i18n";

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

const ROLE_BADGE: Record<string, string> = {
  SA: "bg-red-600", TA: "bg-violet-600", NM: "bg-blue-600", RM: "bg-teal-600",
  WM: "bg-emerald-600", LM: "bg-cyan-600", AU: "bg-gray-500", SYS: "bg-amber-600",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();
  const checked  = useRef(false);
  const [user, setUser]   = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    const session = getSession();
    if (!session) { router.replace(`/login?from=${encodeURIComponent(pathname)}`); return; }
    setUser(session); setReady(true);
  }, [router, pathname]);

  if (!ready || !user) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#0f2d1f]">
        <div className="w-10 h-10 rounded-full border-[3px] border-eth-gold/25 border-t-eth-gold animate-spin" />
        <p className="text-emerald-300 text-sm font-medium">{t("common.loading")}</p>
      </div>
    );
  }

  const firstName = user.name.split(" ")[0] ?? user.name;
  const handleLogout = () => { logout(); router.push("/login"); };

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Top banner */}
      <header className="fixed top-0 left-0 right-0 z-[60] h-14 bg-[#0f2d1f] flex items-center px-6 gap-4 shadow-[0_2px_12px_rgba(0,0,0,0.35)]">
        <Link href="/dashboard" className="flex items-center gap-2 no-underline shrink-0">
          <Logo />
          <span className="font-bold text-sm text-white whitespace-nowrap">
            SMART <span className="text-eth-gold font-medium">{t("nav.inventory")}</span>
          </span>
        </Link>

        <div className="flex-1 flex justify-center">
          <span className="text-sm text-white/55 font-medium">
            {user.role === "SA" ? (
              <span className="text-eth-gold font-semibold">{t("roles.SA")}</span>
            ) : (
              <>
                {user.tenantName}
                {user.warehouseName && <span className="text-emerald-300"> › {user.warehouseName}</span>}
              </>
            )}
          </span>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <span className={`text-[10px] font-extrabold text-white tracking-wide ${ROLE_BADGE[user.role] ?? "bg-gray-500"} px-2 py-0.5 rounded`}>
            {user.role}
          </span>
          <span className="text-sm text-emerald-100 whitespace-nowrap">
            {t("layout.welcome")}, <strong className="text-eth-gold font-bold">{firstName}</strong>
          </span>
          <button onClick={handleLogout}
            className="text-xs font-semibold text-gray-400 cursor-pointer bg-white/[0.07] border border-white/15 rounded px-3 py-1.5">
            {t("layout.sign_out")}
          </button>
        </div>
      </header>

      {/* Ethiopian stripe */}
      <div
        className="fixed top-14 left-0 right-0 z-[59] h-1"
        style={{ background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)" }}
      />

      <div className="flex pt-[60px]">
        <Sidebar user={user} />
        <main className="flex-1 ml-60 min-h-[calc(100vh-60px)] overflow-auto bg-gray-100">
          {children}
        </main>
      </div>
    </div>
  );
}
