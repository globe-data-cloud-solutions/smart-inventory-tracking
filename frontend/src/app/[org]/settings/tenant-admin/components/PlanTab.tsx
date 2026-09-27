"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, PlanData } from "../types";

const PLAN_TIERS = {
  STARTER: { name: "Starter", color: "blue" },
  GROWTH: { name: "Growth", color: "emerald" },
  ENTERPRISE: { name: "Enterprise", color: "purple" },
};

const FEATURE_DESCRIPTIONS: Record<string, string> = {
  CORE_INVENTORY: "Core inventory management",
  TRANSFERS_PULL_PUSH: "Pull/Push transfers",
  TRANSFERS_SISTER: "Sister transfers",
  LOT_TRACEABILITY: "Lot & batch traceability",
  LOGISTICS: "Logistics & fleet management",
  AUDIT_EXPORT: "Audit log export",
  CUSTOM_BRANDING: "Custom branding",
  AI_ANALYTICS: "AI forecasting & analytics",
  API_ACCESS: "API access",
};

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

  const tier = PLAN_TIERS[plan.plan_tier as keyof typeof PLAN_TIERS] || { name: plan.plan_tier, color: "gray" };

  return (
    <div className="space-y-6">
      {/* Current Plan Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-6">{t("wizard.plan_tier")}</h3>

        <div className="mb-6">
          <div className={`inline-block px-4 py-2 rounded-lg font-bold text-white bg-${tier.color}-600`}>
            {tier.name}
          </div>
        </div>

        {/* Resource Limits */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">Max Warehouses</p>
            <p className="text-2xl font-bold text-gray-800">
              {plan.max_warehouses === null ? "Unlimited" : plan.max_warehouses}
            </p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">Max Users</p>
            <p className="text-2xl font-bold text-gray-800">
              {plan.max_users === null ? "Unlimited" : plan.max_users}
            </p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600 mb-1">SKU Cap</p>
            <p className="text-2xl font-bold text-gray-800">
              {plan.sku_cap === null ? "Unlimited" : plan.sku_cap}
            </p>
          </div>
        </div>

        {/* Upgrade Info */}
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-900">
            💡 Need more resources? Contact support or request an upgrade to unlock additional capacity.
          </p>
        </div>
      </div>

      {/* Features Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Available Features</h3>

        <div className="space-y-3">
          {Object.entries(FEATURE_DESCRIPTIONS).map(([key, desc]) => {
            const enabled = plan.feature_flags[key] ?? false;
            return (
              <div key={key} className="flex items-start gap-3">
                <span className={`text-xl mt-0.5 ${enabled ? "✅" : "❌"}`} />
                <div>
                  <p className={`text-sm font-medium ${enabled ? "text-gray-800" : "text-gray-500"}`}>
                    {desc}
                  </p>
                  <p className="text-xs text-gray-500">{key}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Request Upgrade CTA */}
      <div className="bg-gradient-to-r from-emerald-50 to-blue-50 rounded-lg border border-emerald-200 p-6">
        <h4 className="font-semibold text-gray-800 mb-2">Ready to Upgrade?</h4>
        <p className="text-sm text-gray-700 mb-4">
          Request a plan upgrade to unlock more features, users, and warehouses.
        </p>
        <button className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700">
          Request Plan Upgrade
        </button>
      </div>
    </div>
  );
}
