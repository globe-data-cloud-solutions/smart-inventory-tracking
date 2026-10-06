"use client";

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatCurrency } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
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

const SUBSCRIPTION_BADGE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  ACTIVE: "success",
  PENDING_PAYMENT: "warning",
  PAST_DUE: "danger",
  CANCELLED: "neutral",
};

const PAYMENT_BADGE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  PAID: "success",
  PENDING: "warning",
  FAILED: "danger",
  CANCELLED: "neutral",
};

interface PaymentLineItem {
  item_type: string;
  item_key: string;
  description: string | null;
  quantity: number;
  unit_amount: string;
  amount: string;
}

interface PaymentOut {
  id: string;
  status: string;
  currency: string;
  subtotal: string;
  vat_rate: string;
  vat_amount: string;
  total: string;
  period_start: string;
  period_end: string;
  provider: string;
  provider_reference: string | null;
  paid_at: string | null;
  created_at: string;
  line_items: PaymentLineItem[];
}

interface SubscriptionOut {
  id: string | null;
  tier: string | null;
  billing_period: string | null;
  status: string | null;
  provider: string | null;
  amount: string | null;
  currency: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  payments: PaymentOut[];
}

interface CheckoutOut {
  payment_id: string;
  checkout: { type: string; instructions_key?: string; url?: string };
}

function SubscriptionAndInvoices({ tenantId }: { tenantId: string }) {
  const [checkoutFor, setCheckoutFor] = useState<string | null>(null);
  const [checkoutInfo, setCheckoutInfo] = useState<CheckoutOut["checkout"] | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [loadingCheckout, setLoadingCheckout] = useState(false);

  const { data: subscription, isLoading, isError } = useQuery<SubscriptionOut>({
    queryKey: ["tenant-admin-subscription", tenantId],
    queryFn: () => api.get<SubscriptionOut>("/api/v1/tenants/me/subscription"),
    staleTime: 30_000,
  });

  async function handleHowToPay(paymentId: string) {
    if (checkoutFor === paymentId) {
      setCheckoutFor(null);
      return;
    }
    setCheckoutFor(paymentId);
    setCheckoutInfo(null);
    setCheckoutError(null);
    setLoadingCheckout(true);
    try {
      const data = await api.get<CheckoutOut>(`/api/v1/tenants/me/invoices/${paymentId}/checkout`);
      setCheckoutInfo(data.checkout);
    } catch (e: unknown) {
      setCheckoutError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setLoadingCheckout(false);
    }
  }

  if (isLoading) {
    return <div className="flex items-center justify-center py-8 text-gray-500">{t("common.loading")}</div>;
  }
  if (isError) {
    return <div className="flex items-center justify-center py-8 text-red-600">{t("common.error")}</div>;
  }
  if (!subscription || !subscription.id) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-2">{t("tenant_admin.billing.subscription_heading")}</h3>
        <p className="text-sm text-gray-500">{t("tenant_admin.billing.no_subscription")}</p>
      </div>
    );
  }

  const badgeVariant = SUBSCRIPTION_BADGE[subscription.status ?? ""] ?? "neutral";
  const periodLabelKey = subscription.billing_period === "ANNUAL" ? "tenant_admin.billing.annual" : "tenant_admin.billing.monthly";

  return (
    <>
      {/* Subscription Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("tenant_admin.billing.subscription_heading")}</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <p className="text-sm text-gray-500">{t("tenant_admin.billing.package_label")}</p>
            <p className="font-semibold text-gray-800">
              {subscription.tier ? t(`tenant_admin.plan.tier.${subscription.tier}`) : "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500">{t("tenant_admin.billing.billing_period_label")}</p>
            <p className="font-semibold text-gray-800">{t(periodLabelKey)}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">{t("tenant_admin.billing.status_label")}</p>
            <Badge variant={badgeVariant}>
              {t(`tenant_admin.billing.status.${subscription.status ?? ""}`)}
            </Badge>
          </div>
          <div>
            <p className="text-sm text-gray-500">{t("tenant_admin.billing.current_period_label")}</p>
            <p className="font-semibold text-gray-800">
              {subscription.current_period_start ?? "—"} → {subscription.current_period_end ?? "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500">{t("tenant_admin.billing.amount_label")}</p>
            <p className="font-semibold text-gray-800">
              {subscription.amount !== null
                ? formatCurrency(subscription.amount, subscription.currency ?? "ETB")
                : "—"}
            </p>
          </div>
        </div>

        {subscription.status === "PENDING_PAYMENT" && (
          <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
            <p className="text-sm text-amber-900">{t("tenant_admin.billing.pending_note")}</p>
          </div>
        )}
      </div>

      {/* Invoices Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("tenant_admin.billing.invoices_heading")}</h3>

        {subscription.payments.length === 0 ? (
          <p className="text-sm text-gray-500">{t("tenant_admin.billing.no_invoices")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse min-w-[700px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {["col_period", "col_subtotal", "col_vat", "col_total", "col_status", "col_paid_date"].map((key) => (
                    <th key={key} className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                      {t(`tenant_admin.billing.${key}`)}
                    </th>
                  ))}
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {subscription.payments.map((p) => (
                  <Fragment key={p.id}>
                    <tr className="border-b border-gray-100">
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700">{p.period_start} → {p.period_end}</td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700">{formatCurrency(p.subtotal, p.currency)}</td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700">{formatCurrency(p.vat_amount, p.currency)}</td>
                      <td className="px-3 py-2 whitespace-nowrap font-semibold text-gray-800">{formatCurrency(p.total, p.currency)}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <Badge variant={PAYMENT_BADGE[p.status] ?? "neutral"}>
                          {t(`tenant_admin.billing.payment_status.${p.status}`)}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-500">{p.paid_at ?? "—"}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {p.status === "PENDING" && (
                          <button
                            type="button"
                            onClick={() => void handleHowToPay(p.id)}
                            className="text-xs font-semibold text-brand-600 hover:text-brand-700 underline"
                          >
                            {t("tenant_admin.billing.how_to_pay_btn")}
                          </button>
                        )}
                      </td>
                    </tr>
                    {checkoutFor === p.id && (
                      <tr className="border-b border-gray-100 bg-gray-50">
                        <td colSpan={7} className="px-3 py-3">
                          {loadingCheckout && <p className="text-xs text-gray-500">{t("common.loading")}</p>}
                          {checkoutError && <p className="text-xs text-red-600">{checkoutError}</p>}
                          {checkoutInfo?.type === "MANUAL" && checkoutInfo.instructions_key && (
                            <p className="text-xs text-gray-700">{t(checkoutInfo.instructions_key)}</p>
                          )}
                          {checkoutInfo?.type === "REDIRECT" && checkoutInfo.url && (
                            <p className="text-xs text-gray-700">
                              {t("tenant_admin.billing.checkout_url_label")}: {checkoutInfo.url}
                            </p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

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

      <SubscriptionAndInvoices tenantId={tenantId} />

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
