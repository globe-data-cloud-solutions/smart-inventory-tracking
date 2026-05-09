"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSession, type SessionUser } from "@/lib/demo-auth";
import { Sidebar } from "@/components/layout/Sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const session = getSession();
    if (!session) {
      router.replace("/login");
      return;
    }
    setUser(session);
    setReady(true);
  }, [router]);

  if (!ready || !user) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <Sidebar user={user} />
      <div className="flex-1 ml-64 flex flex-col min-h-screen">
        {/* Top bar */}
        <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 flex-shrink-0">
          <div>
            <h1 className="text-sm font-semibold text-gray-900">SMART Inventory Tracker</h1>
            {user.tenantName && (
              <p className="text-xs text-gray-500">{user.tenantName}</p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-green-400" title="Online" />
            <span className="text-sm text-gray-600">{user.email}</span>
          </div>
        </header>
        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
