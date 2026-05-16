"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSession } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";

/** Backward-compatibility redirect: /dashboard → /{orgSlug}/dashboard */
export default function DashboardRedirect() {
  const router = useRouter();
  useEffect(() => {
    const session = getSession();
    router.replace(session ? `/${session.orgSlug}/dashboard` : "/login");
  }, [router]);
  return (
    <div className="min-h-screen bg-[#0f2d1f] flex items-center justify-center">
      <p className="text-emerald-300 text-sm">{t("common.loading")}</p>
    </div>
  );
}
