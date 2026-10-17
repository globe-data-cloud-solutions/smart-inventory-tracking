"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { IS_GATEWAY_MODE, publicGet } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatCurrency } from "@/lib/utils";
import { PackagesListOut } from "@/lib/billing-types";

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

const TIER_ORDER = ["STARTER", "GROWTH", "ENTERPRISE"];

interface PlanComparisonModalProps {
  open: boolean;
  onClose: () => void;
  currentTier?: string;
}

function limitText(n: number | null): string {
  return n === null ? t("tenant_admin.plan.unlimited") : String(n);
}

export function PlanComparisonModal({ open, onClose, currentTier }: PlanComparisonModalProps) {
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const { data: catalog, isLoading, isError } = useQuery<PackagesListOut>({
    queryKey: ["public-packages"],
    queryFn: () => publicGet<PackagesListOut>("/api/v1/tenants/public/packages"),
    enabled: open && IS_GATEWAY_MODE,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (open) closeBtnRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const packages = (catalog?.packages ?? [])
    .slice()
    .sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("billing.compare.title")}
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto p-6"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900">{t("billing.compare.title")}</h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none px-2"
          >
            ×
          </button>
        </div>

        {!IS_GATEWAY_MODE ? (
          <p className="text-sm text-gray-500 py-8 text-center">{t("billing.compare.unavailable")}</p>
        ) : isLoading ? (
          <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>
        ) : isError || !catalog ? (
          <p className="text-sm text-red-600 py-8 text-center">{t("common.error")}</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {packages.map((pkg) => {
              const isCurrent = currentTier === pkg.tier;
              const monthly = pkg.prices.MONTHLY;
              const annual = pkg.prices.ANNUAL;
              return (
                <div
                  key={pkg.tier}
                  className={`rounded-lg border-2 p-4 flex flex-col ${
                    isCurrent ? "border-brand-600 bg-brand-50" : "border-gray-200"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <h3 className="font-bold text-gray-900">{pkg.display_name ?? pkg.tier}</h3>
                    {isCurrent && (
                      <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-brand-600 text-white">
                        {t("billing.compare.your_plan_badge")}
                      </span>
                    )}
                  </div>

                  {monthly ? (
                    <p className="text-xl font-bold text-gray-900">
                      {formatCurrency(monthly.total, monthly.currency)}
                      <span className="text-xs font-normal text-gray-400 ml-1">{t("signup.per_month")}</span>
                    </p>
                  ) : (
                    <p className="text-sm text-gray-400">{t("common.unknown")}</p>
                  )}
                  {annual && (
                    <p className="text-xs text-gray-500 mt-0.5">
                      {formatCurrency(annual.total, annual.currency)} <span>{t("signup.per_year")}</span>
                    </p>
                  )}

                  <ul className="text-xs text-gray-500 mt-3 space-y-1">
                    <li>{t("tenant_admin.plan.max_warehouses")}: {limitText(pkg.max_warehouses)}</li>
                    <li>{t("tenant_admin.plan.max_users")}: {limitText(pkg.max_users)}</li>
                    <li>{t("tenant_admin.plan.sku_cap")}: {limitText(pkg.sku_cap)}</li>
                  </ul>

                  <ul className="text-xs mt-3 space-y-1 flex-1">
                    {FEATURE_FLAG_CODES.map((code) => (
                      <li
                        key={code}
                        className={pkg.feature_flags[code] ? "text-gray-700" : "text-gray-400"}
                      >
                        {pkg.feature_flags[code] ? "✓" : "—"} {t(`tenant_admin.features.flag.${code}`)}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        )}

        <p className="text-xs text-gray-400 text-center mt-6">{t("billing.compare.note")}</p>
      </div>
    </div>
  );
}
