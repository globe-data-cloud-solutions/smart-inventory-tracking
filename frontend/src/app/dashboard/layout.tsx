"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { getSession, type SessionUser } from "@/lib/demo-auth";
import { Sidebar } from "@/components/layout/Sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();
  const checked  = useRef(false);
  const [user, setUser]   = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Run only once per mount — avoids double-check on hot reload
    if (checked.current) return;
    checked.current = true;

    const session = getSession();
    if (!session) {
      // Redirect to login, preserving the intended URL so the user returns after sign-in
      router.replace(`/login?from=${encodeURIComponent(pathname)}`);
      return;
    }
    setUser(session);
    setReady(true);
  }, [router, pathname]);

  // While checking auth, show a full-screen spinner — never show a blank page
  if (!ready || !user) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4" style={{ background: "#1B4332" }}>
        <div className="w-10 h-10 border-4 border-white/20 border-t-yellow-300 rounded-full animate-spin" />
        <p className="text-green-300 text-sm font-medium">Checking session…</p>
      </div>
    );
  }

  const roleColors: Record<string, string> = {
    SA: "#DC2626", TA: "#7C3AED", NM: "#2563EB", RM: "#0D9488",
    WM: "#0D9488", LM: "#0891B2", AU: "#6B7280", SYS: "#D97706",
  };

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <Sidebar user={user} />
      <div className="flex-1 ml-64 flex flex-col min-h-screen">
        {/* Top bar */}
        <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 flex-shrink-0 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-green-400" title="Online" />
            <div>
              <p className="text-sm font-semibold text-gray-900">SMART Inventory Tracker</p>
              {user.tenantName && <p className="text-xs text-gray-400">{user.tenantName}</p>}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {user.warehouseName && (
              <span className="hidden sm:inline text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                📍 {user.warehouseName}
              </span>
            )}
            <span
              className="text-xs font-bold text-white px-2 py-0.5 rounded"
              style={{ background: roleColors[user.role] ?? "#6B7280" }}
            >
              {user.role}
            </span>
            <span className="text-sm text-gray-600 hidden sm:inline">{user.email}</span>
          </div>
        </header>

        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
