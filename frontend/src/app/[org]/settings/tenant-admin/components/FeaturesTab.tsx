"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, PlanData } from "../types";

// Tenant-specific overrides — distinct from the 9-code package feature matrix
// below (FEATURE_MATRIX): these 4 toggle operational features on top of
// whatever the tenant's plan already grants, and are reset whenever the plan
// changes (shared.plans.catalog.apply_package_to_tenant REPLACES feature_flags).
const OVERRIDE_FLAGS = ["LOGISTICS", "AI_ANALYTICS", "ADVANCED_BATCH_TRACKING", "FLEET_MANAGEMENT"] as const;

function FeatureOverrides({ tenantId, flags }: { tenantId: string; flags: Record<string, boolean> }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(OVERRIDE_FLAGS.map((f) => [f, flags[f] ?? false]))
  );
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => api.patch(`/api/v1/tenants/${tenantId}/feature-flags`, { feature_flags: draft }),
    onSuccess: () => {
      setConfirm(false);
      setError(null);
      setSuccess(t("common.success"));
      void qc.invalidateQueries({ queryKey: ["tenant-admin-features", tenantId] });
      void qc.invalidateQueries({ queryKey: ["sa-registry-header"] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : t("common.error")),
  });

  const hasChanges = OVERRIDE_FLAGS.some((f) => draft[f] !== (flags[f] ?? false));

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-2">{t("sa_tenant.features.overrides_heading")}</h3>
      <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-4">
        {t("sa_tenant.features.overrides_warning")}
      </p>
      <p className="text-xs text-gray-500 mb-5">{t("sa.features_hint")}</p>

      <div className="flex flex-col gap-4 mb-6">
        {OVERRIDE_FLAGS.map((flag) => (
          <label key={flag} className="flex items-center justify-between cursor-pointer">
            <span className="text-sm font-medium text-gray-700">{t(`sa.feature_${flag}`)}</span>
            <button
              type="button"
              onClick={() => { setDraft((prev) => ({ ...prev, [flag]: !prev[flag] })); setSuccess(null); }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                draft[flag] ? "bg-[#0f2d1f]" : "bg-gray-300"
              }`}
              aria-pressed={!!draft[flag]}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                draft[flag] ? "translate-x-6" : "translate-x-1"
              }`} />
            </button>
          </label>
        ))}
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {success && <p className="text-sm text-emerald-700 mb-3">{success}</p>}

      {confirm ? (
        <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
          <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
          <button type="button" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}
            className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
            {saveMutation.isPending ? "…" : t("sa.admin_confirm_yes")}
          </button>
          <button type="button" disabled={saveMutation.isPending} onClick={() => setConfirm(false)}
            className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
            {t("sa.admin_confirm_no")}
          </button>
        </div>
      ) : (
        <button type="button" disabled={!hasChanges}
          onClick={() => { setConfirm(true); setSuccess(null); setError(null); }}
          className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
          {t("sa.features_save_btn")}
        </button>
      )}
    </div>
  );
}

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

      {/* SA mode: per-tenant feature overrides (CLAUDE.md §15 S9) */}
      {tenantId && <FeatureOverrides tenantId={tenantId} flags={plan.feature_flags} />}

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
