"use client";

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { TabHelpBanner } from "@/components/ui/TabHelpBanner";
import { ProfileTab } from "./components/ProfileTab";
import { PlanTab } from "./components/PlanTab";
import { ContractTab } from "./components/ContractTab";
import { ContactTab } from "./components/ContactTab";
import { FeaturesTab } from "./components/FeaturesTab";

/* ── Tab definitions ──────────────────────────────────────────────────────── */
const TABS = [
  { id: "profile", label: "Profile", icon: "👤" },
  { id: "plan", label: "Plan", icon: "📊" },
  { id: "contract", label: "Contract", icon: "📋" },
  { id: "contact", label: "Contact", icon: "👥" },
  { id: "features", label: "Features", icon: "✨" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/* ── Main page ──────────────────────────────────────────────────────────── */
export default function TenantAdminPage() {
  const params = useParams();
  const router = useRouter();
  const org = params.org as string;
  const checked = useRef(false);
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("profile");

  /* ── Auth guard: TA only ─────────────────────────────────────────────── */
  useEffect(() => {
    if (checked.current) return;
    checked.current = true;

    const session = getSession();
    if (!session) {
      router.replace(`/login?from=/${org}/settings/tenant-admin`);
      return;
    }

    // Only TA can access this page (SA can still use the SA admin dashboard)
    if (session.role !== "TA") {
      router.replace(`/${session.orgSlug}/dashboard`);
      return;
    }

    setUser(session);
    setReady(true);
  }, [org, router]);

  if (!ready || !user) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-gray-100">
        <div className="w-10 h-10 rounded-full border-[3px] border-eth-gold/25 border-t-eth-gold animate-spin" />
        <p className="text-emerald-600 text-sm font-medium">{t("common.loading")}</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Tenant Admin</h1>
            <p className="text-sm text-gray-600 mt-1">
              Manage your organization's profile, plan, contract, and features
            </p>
          </div>
        </div>
      </div>

      {/* Help Banner */}
      <TabHelpBanner title="Tenant Admin Settings">
        Manage your organization's profile, plan, contract details, and contacts. Request plan upgrades or renew your contract.
      </TabHelpBanner>

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
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      <div className="p-6">
        <div className="max-w-4xl">
          {activeTab === "profile" && <ProfileTab tenantId={org} />}
          {activeTab === "plan" && <PlanTab tenantId={org} />}
          {activeTab === "contract" && <ContractTab tenantId={org} />}
          {activeTab === "contact" && <ContactTab tenantId={org} />}
          {activeTab === "features" && <FeaturesTab tenantId={org} />}
        </div>
      </div>
    </div>
  );
}
