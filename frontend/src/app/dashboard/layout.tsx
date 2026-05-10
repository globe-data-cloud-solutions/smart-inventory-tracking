"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { getSession, logout, type SessionUser } from "@/lib/demo-auth";
import { Sidebar } from "@/components/layout/Sidebar";

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

const ROLE_COLORS: Record<string, string> = {
  SA: "#DC2626", TA: "#7C3AED", NM: "#2563EB",
  RM: "#0D9488", WM: "#059669", LM: "#0891B2",
  AU: "#6B7280", SYS: "#D97706",
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
    if (!session) {
      router.replace(`/login?from=${encodeURIComponent(pathname)}`);
      return;
    }
    setUser(session);
    setReady(true);
  }, [router, pathname]);

  if (!ready || !user) {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 16,
        background: "#0f2d1f",
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: "50%",
          border: "3px solid rgba(252,221,9,0.25)",
          borderTopColor: "#FCDD09",
          animation: "spin 0.8s linear infinite",
        }} />
        <p style={{ color: "#6ee7b7", fontSize: 14, fontWeight: 500 }}>Checking session…</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  const firstName = user.name.split(" ")[0] ?? user.name;
  const handleLogout = () => { logout(); router.push("/login"); };

  return (
    <div style={{ minHeight: "100vh", background: "#F3F4F6" }}>

      {/* ── Dark green banner header — mirrors homepage hero colour ──────── */}
      <header style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 60,
        height: 56, background: "#0f2d1f",
        display: "flex", alignItems: "center",
        padding: "0 1.5rem", gap: "1rem",
        boxShadow: "0 2px 12px rgba(0,0,0,0.35)",
      }}>
        {/* Logo + wordmark */}
        <Link href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none", flexShrink: 0 }}>
          <Logo />
          <span style={{ fontWeight: 700, fontSize: 14, color: "#fff", whiteSpace: "nowrap" }}>
            SMART{" "}
            <span style={{ color: "#FCDD09", fontWeight: 500 }}>Inventory</span>
          </span>
        </Link>

        {/* Centre breadcrumb */}
        <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
          <span style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", fontWeight: 500 }}>
            {user.role === "SA" ? (
              <span style={{ color: "#FCDD09", fontWeight: 600 }}>System Administrator</span>
            ) : (
              <>
                {user.tenantName}
                {user.warehouseName && (
                  <span style={{ color: "#6ee7b7" }}> › {user.warehouseName}</span>
                )}
              </>
            )}
          </span>
        </div>

        {/* Right: role badge · Welcome FirstName · Sign out */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span style={{
            fontSize: 10, fontWeight: 800, color: "#fff", letterSpacing: "0.04em",
            background: ROLE_COLORS[user.role] ?? "#6B7280",
            padding: "3px 8px", borderRadius: 3,
          }}>
            {user.role}
          </span>
          <span style={{ fontSize: 13, color: "#d1fae5", whiteSpace: "nowrap" }}>
            Welcome,{" "}
            <strong style={{ color: "#FCDD09", fontWeight: 700 }}>{firstName}</strong>
          </span>
          <button
            onClick={handleLogout}
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

      {/* Ethiopian 3-stripe immediately below banner */}
      <div style={{
        position: "fixed", top: 56, left: 0, right: 0, zIndex: 59, height: 4,
        background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)",
      }} />

      {/* Body: sidebar (240px, starts at y=60) + scrollable main */}
      <div style={{ display: "flex", paddingTop: 60 }}>
        <Sidebar user={user} />
        <main style={{
          flex: 1,
          marginLeft: 240,   /* matches sidebar width */
          minHeight: "calc(100vh - 60px)",
          overflow: "auto",
          padding: 0,
          background: "#F3F4F6",
        }}>
          {children}
        </main>
      </div>
    </div>
  );
}
