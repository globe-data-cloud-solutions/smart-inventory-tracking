"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, PlanData } from "../types";

const PLAN_TIERS = {
  STARTER: { name: "Starter", color: "blue", className: "bg-blue-600" },
  GROWTH: { name: "Growth", color: "emerald", className: "bg-emerald-600" },
  ENTERPRISE: { name: "Enterprise", color: "purple", className: "bg-purple-600" },
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

  const tier = PLAN_TIERS[plan.plan_tier as keyof typeof PLAN_TIERS] || { name: plan.plan_tier, color: "gray", className: "bg-gray-600" };

  return (
    <div className="space-y-6">
      {/* Current Plan Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-6">{t("wizard.plan_tier")}</h3>

        <div className="mb-6">
          <div className={`inline-block px-4 py-2 rounded-lg font-bold text-white ${tier.className}`}>
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
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Upgrade CTA */}
      <UpgradeSection currentTier={tier.name} />
    </div>
  );
}

function UpgradeSection({ currentTier }: { currentTier: string }) {
  const [showModal, setShowModal] = useState(false);
  const [selectedTier, setSelectedTier] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const UPGRADE_PATHS = {
    Starter: [{ tier: "GROWTH", label: "Growth" }, { tier: "ENTERPRISE", label: "Enterprise" }],
    Growth: [{ tier: "ENTERPRISE", label: "Enterprise" }],
    Enterprise: [],
  } as const;

  const upgrades = UPGRADE_PATHS[currentTier as keyof typeof UPGRADE_PATHS] || [];

  if (upgrades.length === 0) {
    return (
      <div className="bg-gradient-to-r from-blue-50 to-emerald-50 rounded-lg border border-blue-200 p-6">
        <h4 className="font-semibold text-gray-800 mb-2">Enterprise Plan</h4>
        <p className="text-sm text-gray-700">You're on our highest plan tier. Contact support for custom arrangements.</p>
      </div>
    );
  }

  const handleUpgrade = async () => {
    if (!selectedTier) return;
    setError("");
    setLoading(true);

    try {
      const response = await fetch("/api/v1/tenants/me/plan", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_plan_tier: selectedTier }),
      });

      const data = await response.json();
      if (!response.ok) {
        setError(data.error?.message || "Upgrade failed");
        return;
      }

      setShowModal(false);
      window.location.reload(); // Reload to show new plan
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upgrade failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="bg-gradient-to-r from-emerald-50 to-blue-50 rounded-lg border border-emerald-200 p-6">
        <h4 className="font-semibold text-gray-800 mb-2">Ready to Upgrade?</h4>
        <p className="text-sm text-gray-700 mb-4">
          Upgrade to unlock more features, users, and warehouses.
        </p>
        <button
          onClick={() => setShowModal(true)}
          className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700"
        >
          Upgrade Plan
        </button>
      </div>

      {/* Upgrade Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-semibold text-gray-800">Upgrade Your Plan</h3>

            {error && (
              <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded text-sm">{error}</div>
            )}

            <div className="space-y-2">
              {upgrades.map((option) => (
                <button
                  key={option.tier}
                  onClick={() => setSelectedTier(option.tier)}
                  className={`w-full p-3 text-left rounded border-2 transition-colors ${
                    selectedTier === option.tier
                      ? "border-emerald-600 bg-emerald-50"
                      : "border-gray-200 bg-white hover:bg-gray-50"
                  }`}
                >
                  <p className="font-medium text-gray-800">{option.label}</p>
                  <p className="text-xs text-gray-500">Higher limits and more features</p>
                </button>
              ))}
            </div>

            <div className="flex gap-2 pt-4">
              <button
                onClick={() => setShowModal(false)}
                disabled={loading}
                className="flex-1 px-4 py-2 text-sm font-medium bg-gray-100 text-gray-800 rounded hover:bg-gray-200 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleUpgrade}
                disabled={!selectedTier || loading}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700 disabled:opacity-50"
              >
                {loading ? "Upgrading..." : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

