"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { PlanComparisonModal } from "./PlanComparisonModal";

const TIER_ORDER = ["STARTER", "GROWTH", "ENTERPRISE"];

interface RenewalRequestOut {
  id: string;
  request_type: "RENEWAL" | "UPGRADE";
  requested_tier: string | null;
  status: "OPEN" | "HANDLED" | "CANCELLED";
  created_at: string;
}

const UPGRADE_ERROR_CODES = new Set(["NOT_AN_UPGRADE", "REQUESTED_TIER_REQUIRED"]);

function upgradeErrorMessage(e: unknown): string {
  const code = (e as { code?: string } | undefined)?.code;
  if (code && UPGRADE_ERROR_CODES.has(code)) return t(`tenant_admin.features.upgrade_error.${code}`);
  return e instanceof Error ? e.message : t("common.error");
}

const UPGRADE_MESSAGE_MAX = 500;

const PLAN_TIER_KEYS: Record<string, string> = {
  STARTER: "tenant_admin.plan.tier.STARTER",
  GROWTH: "tenant_admin.plan.tier.GROWTH",
  ENTERPRISE: "tenant_admin.plan.tier.ENTERPRISE",
};

function tierLabel(code: string): string {
  const key = PLAN_TIER_KEYS[code];
  return key ? t(key) : code;
}

/**
 * TA-only "request an upgrade" flow (SA mode never renders this — SA changes
 * plans directly). Shared between FeaturesTab and the org-tree warehouse-cap
 * notice so both reuse the same dialog, error handling and open-request state.
 */
export function RequestUpgradeSection({ planTier }: { planTier: string }) {
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [tier, setTier] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: requests } = useQuery<RenewalRequestOut[]>({
    queryKey: ["tenant-renewal-requests"],
    queryFn: () => api.get<RenewalRequestOut[]>("/api/v1/tenants/me/renewal-requests"),
    staleTime: 10_000,
  });

  const openUpgradeRequest = (requests ?? []).find(
    (r) => r.status === "OPEN" && r.request_type === "UPGRADE",
  ) ?? null;

  const upgradeTiers = TIER_ORDER.filter((tr) => TIER_ORDER.indexOf(tr) > TIER_ORDER.indexOf(planTier));

  const submitMutation = useMutation({
    mutationFn: () => api.post<RenewalRequestOut>("/api/v1/tenants/me/renewal-requests", {
      request_type: "UPGRADE",
      requested_tier: tier,
      message: message.trim() || undefined,
    }),
    onSuccess: () => {
      setDialogOpen(false);
      setMessage("");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["tenant-renewal-requests"] });
    },
    onError: (e: unknown) => {
      const code = (e as { code?: string } | undefined)?.code;
      if (code === "UPGRADE_REQUEST_OPEN") {
        setDialogOpen(false);
        void qc.invalidateQueries({ queryKey: ["tenant-renewal-requests"] });
        return;
      }
      setError(upgradeErrorMessage(e));
    },
  });

  function startDialog() {
    setTier(upgradeTiers[0] ?? "");
    setMessage("");
    setError(null);
    setDialogOpen(true);
  }

  if (planTier === "ENTERPRISE") {
    return <p className="text-sm text-gray-600">{t("tenant_admin.features.top_plan_note")}</p>;
  }

  if (openUpgradeRequest) {
    return (
      <p className="text-sm text-gray-700">
        {t("tenant_admin.features.upgrade_open_notice")
          .replace("{tier}", tierLabel(openUpgradeRequest.requested_tier ?? ""))
          .replace("{date}", new Date(openUpgradeRequest.created_at).toLocaleDateString())}
      </p>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={startDialog}
        className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700"
      >
        {t("tenant_admin.features.request_upgrade_btn")}
      </button>

      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setDialogOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            className="bg-white rounded-lg shadow-xl w-full max-w-sm p-5"
          >
            <h3 className="text-base font-bold text-gray-900 mb-3">{t("tenant_admin.features.upgrade_dialog_title")}</h3>

            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("tenant_admin.features.upgrade_dialog_tier_label")}
            </label>
            <select
              value={tier}
              onChange={(e) => setTier(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-emerald-600 mb-3"
            >
              {upgradeTiers.map((tr) => (
                <option key={tr} value={tr}>{tierLabel(tr)}</option>
              ))}
            </select>

            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("tenant_admin.features.upgrade_dialog_message_label")}
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value.slice(0, UPGRADE_MESSAGE_MAX))}
              placeholder={t("tenant_admin.features.upgrade_dialog_message_placeholder")}
              maxLength={UPGRADE_MESSAGE_MAX}
              rows={3}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-emerald-600 resize-none mb-1"
            />

            <button
              type="button"
              onClick={() => setCompareOpen(true)}
              className="text-xs font-semibold text-blue-600 hover:text-blue-700 underline mb-3"
            >
              {t("tenant_admin.features.compare_plans_link")}
            </button>

            {error && <p className="text-xs text-red-600 mb-3">{error}</p>}

            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setDialogOpen(false)}
                className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200"
              >
                {t("sa_tenant.billing.confirm_no")}
              </button>
              <button
                type="button"
                disabled={submitMutation.isPending || !tier}
                onClick={() => submitMutation.mutate()}
                className="px-3 py-1.5 text-xs font-bold text-white bg-emerald-600 rounded hover:bg-emerald-700 disabled:opacity-50"
              >
                {submitMutation.isPending ? "…" : t("tenant_admin.features.upgrade_dialog_submit_btn")}
              </button>
            </div>
          </div>
        </div>
      )}

      <PlanComparisonModal open={compareOpen} onClose={() => setCompareOpen(false)} currentTier={planTier} />
    </>
  );
}
