"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, PlanData } from "../types";

const FEATURE_MATRIX: Record<string, { name: string; description: string; tiers: string[] }> = {
  CORE_INVENTORY: {
    name: "Core Inventory Management",
    description: "Receive, transfer, issue, and count inventory with immutable ledger",
    tiers: ["STARTER", "GROWTH", "ENTERPRISE"],
  },
  TRANSFERS_PULL_PUSH: {
    name: "Pull & Push Transfers",
    description: "Transfer inventory between facilities with approval workflows",
    tiers: ["STARTER", "GROWTH", "ENTERPRISE"],
  },
  TRANSFERS_SISTER: {
    name: "Sister Transfers",
    description: "Lateral transfers between facilities at the same level",
    tiers: ["GROWTH", "ENTERPRISE"],
  },
  LOT_TRACEABILITY: {
    name: "Lot & Batch Traceability",
    description: "Track batch numbers, manufacture dates, and expiry tracking",
    tiers: ["STARTER", "GROWTH", "ENTERPRISE"],
  },
  LOGISTICS: {
    name: "Logistics & Fleet Management",
    description: "Manage drivers, vehicles, and delivery routes",
    tiers: ["GROWTH", "ENTERPRISE"],
  },
  AUDIT_EXPORT: {
    name: "Audit Log Export",
    description: "Export audit logs for compliance and record-keeping",
    tiers: ["GROWTH", "ENTERPRISE"],
  },
  CUSTOM_BRANDING: {
    name: "Custom Branding",
    description: "Add your logo, banner, and custom colors",
    tiers: ["GROWTH", "ENTERPRISE"],
  },
  AI_ANALYTICS: {
    name: "AI Forecasting & Analytics",
    description: "Demand forecasting, replenishment recommendations, and insights",
    tiers: ["GROWTH", "ENTERPRISE"],
  },
  API_ACCESS: {
    name: "API Access",
    description: "Integrate SMART with your external systems via REST API",
    tiers: ["ENTERPRISE"],
  },
};

export function FeaturesTab({ tenantId, isLoading }: TabProps) {
  const { data: plan, isLoading: loadingPlan } = useQuery<PlanData>({
    queryKey: ["tenant-admin-features"],
    queryFn: () => api.get<PlanData>(`/api/v1/tenants/me/plan`),
    staleTime: 30_000,
  });

  if (loadingPlan || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!plan) {
    return <div className="flex items-center justify-center py-12 text-red-600">{t("common.error")}</div>;
  }

  return (
    <div className="space-y-6">
      {/* Plan Tier Summary */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-800 mb-1">Current Plan: {plan.plan_tier}</h3>
            <p className="text-sm text-gray-600">
              {Object.values(FEATURE_MATRIX).filter((f) => f.tiers.includes(plan.plan_tier)).length} features available
            </p>
          </div>
          <button className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700">
            View Pricing
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
                  <h4 className="font-semibold text-gray-800 mb-1">{feature.name}</h4>
                  <p className="text-sm text-gray-600 mb-2">{feature.description}</p>
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
                        {tier}
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
        <h4 className="font-semibold text-gray-800 mb-2">🚀 Want More Features?</h4>
        <p className="text-sm text-gray-700 mb-4">
          Upgrade to unlock advanced features like AI analytics, custom branding, and API access.
        </p>
        <div className="flex gap-3">
          <button className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700">
            Request Upgrade
          </button>
          <button className="px-4 py-2 text-sm font-medium text-emerald-600 bg-white border border-emerald-600 rounded hover:bg-emerald-50">
            View Plans
          </button>
        </div>
      </div>

      {/* Plan Comparison Link */}
      <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 text-center">
        <p className="text-sm text-gray-600">
          Need help choosing a plan?{" "}
          <a href="#" className="font-semibold text-blue-600 hover:text-blue-700">
            Compare plans
          </a>{" "}
          or{" "}
          <a href="#" className="font-semibold text-blue-600 hover:text-blue-700">
            contact support
          </a>
        </p>
      </div>
    </div>
  );
}
