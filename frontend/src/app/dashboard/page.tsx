"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSession } from "@/lib/demo-auth";

/** Backward-compatibility redirect: /dashboard → /{orgSlug}/dashboard */
export default function DashboardRedirect() {
  const router = useRouter();
  useEffect(() => {
    const session = getSession();
    router.replace(session ? `/${session.orgSlug}/dashboard` : "/login");
  }, [router]);
  return (
    <div style={{ minHeight: "100vh", background: "#0f2d1f", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <p style={{ color: "#6ee7b7", fontSize: 14 }}>Redirecting…</p>
    </div>
  );
}
