"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getSession } from "@/lib/demo-auth";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabHelpBanner } from "@/components/ui/TabHelpBanner";
import { ProfileTab } from "../../tenant-admin/components/ProfileTab";
import { PlanTab } from "../../tenant-admin/components/PlanTab";
import { ContractTab } from "../../tenant-admin/components/ContractTab";
import { ContactTab } from "../../tenant-admin/components/ContactTab";
import { FeaturesTab } from "../../tenant-admin/components/FeaturesTab";

/* ── Tab definitions — same five tabs as the TA's own tenant-admin page,
   reused here (not copied) in SA mode via the tenantId prop. ── */
const TABS = [
  { id: "profile", labelKey: "sa.admin_sub_profile", icon: "👤" },
  { id: "plan", labelKey: "sa.admin_sub_plan", icon: "📊" },
  { id: "contract", labelKey: "sa.admin_sub_contract", icon: "📋" },
  { id: "contact", labelKey: "tenant_admin.tabs.contact", icon: "👥" },
  { id: "features", labelKey: "sa.admin_sub_features", icon: "✨" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/* Minimal header data — pulled from the existing SA registry list rather than
   adding a new backend field for signup_source (CLAUDE.md §15 S8). */
interface RegistryHeaderRow {
  id: string;
  name: string;
  slug: string | null;
  status: string;
  signup_source: string;
}

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: "bg-emerald-100 text-emerald-700",
  SUSPENDED: "bg-red-100 text-red-700",
  DEACTIVATED: "bg-gray-100 text-gray-600",
};

export default function SaTenantViewPage() {
  const params = useParams();
  const tenantId = params.tenantId as string;
  const session = getSession();
  const [activeTab, setActiveTab] = useState<TabId>("profile");

  if (!session || session.role !== "SA") {
    return <p className="p-8 text-gray-500">{t("sa_tenant.restricted")}</p>;
  }

  const { data: registry, isLoading: loadingRegistry } = useQuery<RegistryHeaderRow[]>({
    queryKey: ["sa-registry-header"],
    queryFn: () => api.get<RegistryHeaderRow[]>("/api/v1/tenants/sa/registry"),
    staleTime: 30_000,
  });

  const tenant = registry?.find((r) => r.id === tenantId) ?? null;
  const statusKey = (tenant?.status || "ACTIVE").toLowerCase();

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-6">
        <Link href="/admin/dashboard" className="text-sm font-semibold text-blue-600 hover:underline">
          {t("sa_tenant.back_to_registry")}
        </Link>
        <div className="flex items-center justify-between mt-2">
          <div>
            {loadingRegistry ? (
              <p className="text-gray-400 text-sm">{t("common.loading")}</p>
            ) : tenant ? (
              <>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold text-gray-900">{tenant.name}</h1>
                  <span className={`inline-block px-2 py-1 rounded text-xs font-semibold ${STATUS_BADGE[tenant.status] ?? "bg-gray-100 text-gray-600"}`}>
                    {t(`sa.tenant_status_${statusKey}`)}
                  </span>
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                    tenant.signup_source === "SELF_SIGNUP" ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"
                  }`}>
                    {tenant.signup_source === "SELF_SIGNUP" ? t("sa.source_self_signup") : t("sa.source_sa")}
                  </span>
                </div>
                <p className="text-sm text-gray-600 mt-1">{tenant.slug ?? tenant.id}</p>
              </>
            ) : (
              <p className="text-sm text-red-600">{t("common.error")}</p>
            )}
          </div>
        </div>
      </div>

      <TabHelpBanner
        storageKey="sa-tenant-view"
        message={t("sa_tenant.help_banner.content")}
      />

      {/* Tabs Navigation */}
      <div className="bg-white border-b border-gray-200 px-6">
        <div className="flex gap-8 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-2 py-4 border-b-2 font-medium text-sm whitespace-nowrap transition-all ${
                activeTab === tab.id
                  ? "border-eth-gold text-eth-gold"
                  : "border-transparent text-gray-600 hover:text-gray-900"
              }`}
            >
              <span className="mr-2">{tab.icon}</span>
              {t(tab.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content — tenantId passed through switches every tab's endpoints
          from /me/... to /{tenantId}/... and enables SA-only controls. */}
      <div className="p-6">
        <div className="max-w-4xl">
          {activeTab === "profile" && <ProfileTab tenantId={tenantId} />}
          {activeTab === "plan" && <PlanTab tenantId={tenantId} />}
          {activeTab === "contract" && <ContractTab tenantId={tenantId} />}
          {activeTab === "contact" && <ContactTab tenantId={tenantId} />}
          {activeTab === "features" && <FeaturesTab tenantId={tenantId} />}
        </div>
      </div>
    </div>
  );
}
