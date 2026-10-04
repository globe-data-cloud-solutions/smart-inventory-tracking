"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, PlanData } from "../types";

const PLAN_TIERS = {
  STARTER: { nameKey: "tenant_admin.plan.tier.STARTER", className: "bg-blue-600" },
  GROWTH: { nameKey: "tenant_admin.plan.tier.GROWTH", className: "bg-emerald-600" },
  ENTERPRISE: { nameKey: "tenant_admin.plan.tier.ENTERPRISE", className: "bg-purple-600" },
};

// Keys shared with FeaturesTab.tsx — see tenant_admin.features.flag.* / flag_desc.* in locales/en.json
const FEATURE_FLAG_CODES = [
  "CORE_INVENTORY",
  "TRANSFERS_PULL_PUSH",
  "TRANSFERS_SISTER",
  "LOT_TRACEABILITY",
  "LOGISTICS",
  "AUDIT_EXPORT",
  "CUSTOM_BRANDING",
  "AI_ANALYTICS",
  "API_ACCESS",
];

export function PlanTab({ tenantId, isLoading }: TabProps) {
  const { data: plan, isLoading: loadingPlan } = useQuery<PlanData>({
    queryKey: ["tenant-admin-plan"],
    queryFn: () => api.get<PlanData>(`/api/v1/tenants/me/plan`),
    staleTime: 30_000,
  });

  if (loadingPlan || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!plan) {
    return <div className="flex items-center justify-center py-12 text-red-600">{t("common.error")}</div>;
  }

  const tier = PLAN_TIERS[plan.plan_tier as keyof typeof PLAN_TIERS] || { nameKey: null, className: "bg-gray-600" };
  const tierName = tier.nameKey ? t(tier.nameKey) : plan.plan_tier;

  return (
    <div className="space-y-6">
      {/* Current Plan Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-6">{t("wizard.plan_tier")}</h3>

        <div className="mb-6">
          <div className={`inline-block px-4 py-2 rounded-lg font-bold text-white ${tier.className}`}>
            {tierName}
          </div>
        </div>

        {/* Resource Limits */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.plan.max_warehouses")}</p>
            <p className="text-2xl font-bold text-gray-800">
              {plan.max_warehouses === null ? t("tenant_admin.plan.unlimited") : plan.max_warehouses}
            </p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.plan.max_users")}</p>
            <p className="text-2xl font-bold text-gray-800">
              {plan.max_users === null ? t("tenant_admin.plan.unlimited") : plan.max_users}
            </p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.plan.sku_cap")}</p>
            <p className="text-2xl font-bold text-gray-800">
              {plan.sku_cap === null ? t("tenant_admin.plan.unlimited") : plan.sku_cap}
            </p>
          </div>
        </div>

        {/* Upgrade Info */}
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-900">
            💡 {t("tenant_admin.plan.upgrade_hint")}
          </p>
        </div>
      </div>

      {/* Features Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("tenant_admin.plan.available_features")}</h3>

        <div className="space-y-3">
          {FEATURE_FLAG_CODES.map((key) => {
            const enabled = plan.feature_flags[key] ?? false;
            return (
              <div key={key} className="flex items-start gap-3">
                <span className={`text-xl mt-0.5 ${enabled ? "✅" : "❌"}`} />
                <div>
                  <p className={`text-sm font-medium ${enabled ? "text-gray-800" : "text-gray-500"}`}>
                    {t(`tenant_admin.features.flag.${key}`)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Request Upgrade CTA */}
      <div className="bg-gradient-to-r from-emerald-50 to-blue-50 rounded-lg border border-emerald-200 p-6">
        <h4 className="font-semibold text-gray-800 mb-2">{t("tenant_admin.plan.ready_to_upgrade")}</h4>
        <p className="text-sm text-gray-700 mb-4">
          {t("tenant_admin.plan.upgrade_cta_text")}
        </p>
        <button className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700">
          {t("tenant_admin.plan.request_upgrade_btn")}
        </button>
      </div>
    </div>
  );
}
