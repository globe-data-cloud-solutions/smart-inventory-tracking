"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, PlanData } from "../types";

// name/description keys shared with PlanTab.tsx — see tenant_admin.features.flag.* / flag_desc.* in locales/en.json
const FEATURE_MATRIX: Record<string, { tiers: string[] }> = {
  CORE_INVENTORY: { tiers: ["STARTER", "GROWTH", "ENTERPRISE"] },
  TRANSFERS_PULL_PUSH: { tiers: ["STARTER", "GROWTH", "ENTERPRISE"] },
  TRANSFERS_SISTER: { tiers: ["GROWTH", "ENTERPRISE"] },
  LOT_TRACEABILITY: { tiers: ["STARTER", "GROWTH", "ENTERPRISE"] },
  LOGISTICS: { tiers: ["GROWTH", "ENTERPRISE"] },
  AUDIT_EXPORT: { tiers: ["GROWTH", "ENTERPRISE"] },
  CUSTOM_BRANDING: { tiers: ["GROWTH", "ENTERPRISE"] },
  AI_ANALYTICS: { tiers: ["GROWTH", "ENTERPRISE"] },
  API_ACCESS: { tiers: ["ENTERPRISE"] },
};

const PLAN_TIER_KEYS: Record<string, string> = {
  STARTER: "tenant_admin.plan.tier.STARTER",
  GROWTH: "tenant_admin.plan.tier.GROWTH",
  ENTERPRISE: "tenant_admin.plan.tier.ENTERPRISE",
};

function tierLabel(code: string): string {
  const key = PLAN_TIER_KEYS[code];
  return key ? t(key) : code;
}

export function FeaturesTab({ tenantId, isLoading }: TabProps) {
  const planPath = tenantId ? `/api/v1/tenants/${tenantId}/plan` : `/api/v1/tenants/me/plan`;
  const { data: plan, isLoading: loadingPlan } = useQuery<PlanData>({
    queryKey: ["tenant-admin-features", tenantId ?? "me"],
    queryFn: () => api.get<PlanData>(planPath),
    staleTime: 30_000,
  });

  if (loadingPlan || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!plan) {
    return <div className="flex items-center justify-center py-12 text-red-600">{t("common.error")}</div>;
  }

  const planTierLabel = tierLabel(plan.plan_tier);
  const availableCount = Object.values(FEATURE_MATRIX).filter((f) => f.tiers.includes(plan.plan_tier)).length;

  return (
    <div className="space-y-6">
      {/* Plan Tier Summary */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-800 mb-1">
              {t("tenant_admin.features.current_plan").replace("{tier}", planTierLabel)}
            </h3>
            <p className="text-sm text-gray-600">
              {t("tenant_admin.features.count_available").replace("{n}", String(availableCount))}
            </p>
          </div>
          <button className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700">
            {t("tenant_admin.features.view_pricing_btn")}
          </button>
        </div>
      </div>

      {/* Feature List */}
      <div className="space-y-3">
        {Object.entries(FEATURE_MATRIX).map(([key, feature]) => {
          const isIncluded = plan.feature_flags[key] ?? false;
          const isAvailableInCurrentTier = feature.tiers.includes(plan.plan_tier);

          return (
            <div
              key={key}
              className={`border rounded-lg p-4 transition-all ${
                isIncluded
                  ? "bg-white border-green-200"
                  : isAvailableInCurrentTier
                    ? "bg-gray-50 border-gray-200"
                    : "bg-amber-50 border-amber-200"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="text-2xl mt-1">
                  {isIncluded ? "✅" : isAvailableInCurrentTier ? "✓" : "🔒"}
                </span>
                <div className="flex-1">
                  <h4 className="font-semibold text-gray-800 mb-1">{t(`tenant_admin.features.flag.${key}`)}</h4>
                  <p className="text-sm text-gray-600 mb-2">{t(`tenant_admin.features.flag_desc.${key}`)}</p>
                  <div className="flex flex-wrap gap-1">
                    {feature.tiers.map((tier) => (
                      <span
                        key={tier}
                        className={`inline-block text-xs px-2 py-1 rounded ${
                          tier === plan.plan_tier
                            ? "bg-blue-100 text-blue-800 font-medium"
                            : "bg-gray-200 text-gray-700"
                        }`}
                      >
                        {tierLabel(tier)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Upgrade CTA */}
      <div className="bg-gradient-to-r from-emerald-50 to-teal-50 rounded-lg border border-emerald-200 p-6">
        <h4 className="font-semibold text-gray-800 mb-2">🚀 {t("tenant_admin.features.want_more_title")}</h4>
        <p className="text-sm text-gray-700 mb-4">
          {t("tenant_admin.features.upgrade_text")}
        </p>
        <div className="flex gap-3">
          <button className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700">
            {t("tenant_admin.features.request_upgrade_btn")}
          </button>
          <button className="px-4 py-2 text-sm font-medium text-emerald-600 bg-white border border-emerald-600 rounded hover:bg-emerald-50">
            {t("tenant_admin.features.view_plans_btn")}
          </button>
        </div>
      </div>

      {/* Plan Comparison Link */}
      <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 text-center">
        <p className="text-sm text-gray-600">
          {t("tenant_admin.features.need_help_prefix")}{" "}
          <a href="#" className="font-semibold text-blue-600 hover:text-blue-700">
            {t("tenant_admin.features.compare_plans_link")}
          </a>{" "}
          {t("tenant_admin.features.or_word")}{" "}
          <a href="#" className="font-semibold text-blue-600 hover:text-blue-700">
            {t("tenant_admin.features.contact_support_link")}
          </a>
        </p>
      </div>
    </div>
  );
}
