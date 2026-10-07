"use client";

import { Fragment, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatCurrency } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { TabProps, PlanData, TenantAddonOut } from "../types";

const PLAN_TIERS = {
  STARTER: { nameKey: "tenant_admin.plan.tier.STARTER", className: "bg-blue-600" },
  GROWTH: { nameKey: "tenant_admin.plan.tier.GROWTH", className: "bg-emerald-600" },
  ENTERPRISE: { nameKey: "tenant_admin.plan.tier.ENTERPRISE", className: "bg-purple-600" },
};

const SELECTABLE_TIERS = ["STARTER", "GROWTH", "ENTERPRISE"] as const;

// Live per-tier limits — never hardcoded (CLAUDE.md §15). Only the fields this
// form needs; the full catalog shape lives in settings/plans/page.tsx.
interface TierConfigEntry {
  tier: string;
  max_warehouses: number | null;
  max_users: number | null;
  sku_cap: number | null;
}

function limitText(n: number | null): string {
  return n === null ? t("tenant_admin.plan.unlimited") : String(n);
}

function TierChangeForm({ tenantId, plan }: { tenantId: string; plan: PlanData }) {
  const qc = useQueryClient();
  const [selectedTier, setSelectedTier] = useState(plan.plan_tier);
  const [skuCap, setSkuCap] = useState<number | null>(plan.sku_cap);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { data: tierConfig } = useQuery<TierConfigEntry[]>({
    queryKey: ["platform-tier-config"],
    queryFn: () => api.get<TierConfigEntry[]>("/api/v1/tenants/platform/tier-config"),
    staleTime: 30_000,
  });

  const saveMutation = useMutation({
    mutationFn: () => api.patch(`/api/v1/tenants/${tenantId}/plan`, { plan_tier: selectedTier, sku_cap: skuCap }),
    onSuccess: () => {
      setConfirm(false);
      setError(null);
      setSuccess(t("common.success"));
      void qc.invalidateQueries({ queryKey: ["tenant-admin-plan", tenantId] });
      void qc.invalidateQueries({ queryKey: ["tenant-admin-features", tenantId] });
      void qc.invalidateQueries({ queryKey: ["sa-registry-header"] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : t("common.error")),
  });

  const hasChanges = selectedTier !== plan.plan_tier || skuCap !== plan.sku_cap;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa.admin_sub_plan")}</h3>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
        {SELECTABLE_TIERS.map((tier) => {
          const entry = tierConfig?.find((e) => e.tier === tier);
          const selected = selectedTier === tier;
          return (
            <button
              key={tier}
              type="button"
              onClick={() => { setSelectedTier(tier); setSuccess(null); }}
              className={`flex flex-col items-start px-4 py-3 rounded-lg text-left border-2 transition-colors ${
                selected ? "border-[#0f2d1f] bg-emerald-50" : "border-gray-200 bg-white hover:border-gray-300"
              }`}
            >
              <span className="text-sm font-bold text-gray-800">{tier}</span>
              {entry ? (
                <span className="text-xs text-gray-500 mt-1">
                  {t("tenant_admin.plan.max_warehouses")}: {limitText(entry.max_warehouses)} · {t("tenant_admin.plan.max_users")}: {limitText(entry.max_users)}
                </span>
              ) : (
                <span className="text-xs text-gray-400 mt-1">{t("common.loading")}</span>
              )}
            </button>
          );
        })}
      </div>

      <div className="mb-5 max-w-xs">
        <label className="block text-sm font-medium text-gray-700 mb-1">{t("sa.plan_sku_cap_label")}</label>
        <input
          type="number"
          min={0}
          placeholder={t("sa.plan_sku_cap_unlimited")}
          value={skuCap ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            setSkuCap(v === "" ? null : Math.max(0, parseInt(v, 10)));
            setSuccess(null);
          }}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f] focus:ring-1 focus:ring-[#0f2d1f]"
        />
        <p className="text-xs text-gray-400 mt-1">{t("sa.plan_sku_cap_hint")}</p>
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
        <button
          type="button"
          disabled={!hasChanges}
          onClick={() => { setConfirm(true); setSuccess(null); setError(null); }}
          className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50"
        >
          {t("sa.admin_save_btn")}
        </button>
      )}
    </div>
  );
}

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

// Error codes billing.py's _map_value_error / inline checks can raise on the
// SA invoice/payment actions below — mapped to sa_tenant.billing_error.<code>.
const BILLING_ERROR_CODES = new Set([
  "INVOICE_ALREADY_PENDING",
  "NO_LIVE_SUBSCRIPTION",
  "INVALID_PAYMENT_STATE",
  "WRONG_PROVIDER",
  "PRICE_NOT_AVAILABLE",
  "PAYMENT_NOT_FOUND",
]);

function billingErrorMessage(e: unknown): string {
  const code = (e as { code?: string } | undefined)?.code;
  if (code && BILLING_ERROR_CODES.has(code)) return t(`sa_tenant.billing_error.${code}`);
  return e instanceof Error ? e.message : t("common.error");
}

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

interface RaiseInvoiceResult {
  payment_id: string;
  period_start: string;
  period_end: string;
  total: string;
  // create_invoice()'s response omits currency (ETB is the platform's only
  // currency today) — formatCurrency() defaults to "ETB" when undefined.
  currency?: string;
}

function SubscriptionAndInvoices({ tenantId }: { tenantId?: string }) {
  const qc = useQueryClient();
  const subPath = tenantId ? `/api/v1/tenants/${tenantId}/subscription` : `/api/v1/tenants/me/subscription`;
  const subscriptionQueryKey = ["tenant-admin-subscription", tenantId ?? "me"];

  // ── TA-only: "how to pay" checkout instructions for a PENDING invoice ──────
  const [checkoutFor, setCheckoutFor] = useState<string | null>(null);
  const [checkoutInfo, setCheckoutInfo] = useState<CheckoutOut["checkout"] | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [loadingCheckout, setLoadingCheckout] = useState(false);

  // ── SA-only: raise / mark-paid / cancel invoice actions ────────────────────
  const [raiseConfirm, setRaiseConfirm] = useState(false);
  const [raiseResult, setRaiseResult] = useState<RaiseInvoiceResult | null>(null);
  const [raiseError, setRaiseError] = useState<string | null>(null);
  const [actionRow, setActionRow] = useState<{ paymentId: string; type: "markPaid" | "cancel" } | null>(null);
  const [actionRef, setActionRef] = useState("");
  const [actionNote, setActionNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const { data: subscription, isLoading, isError } = useQuery<SubscriptionOut>({
    queryKey: subscriptionQueryKey,
    queryFn: () => api.get<SubscriptionOut>(subPath),
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

  const invalidateSubscription = () => void qc.invalidateQueries({ queryKey: subscriptionQueryKey });

  const raiseMutation = useMutation({
    mutationFn: () => api.post<RaiseInvoiceResult>(`/api/v1/tenants/${tenantId}/invoices`, {}),
    onSuccess: (data) => {
      setRaiseConfirm(false);
      setRaiseError(null);
      setRaiseResult(data);
      invalidateSubscription();
    },
    onError: (e: unknown) => setRaiseError(billingErrorMessage(e)),
  });

  const markPaidMutation = useMutation({
    mutationFn: (paymentId: string) =>
      api.post(`/api/v1/tenants/${tenantId}/payments/${paymentId}/mark-paid`, {
        provider_reference: actionRef.trim() || undefined,
        note: actionNote.trim() || undefined,
      }),
    onSuccess: () => {
      setActionRow(null);
      setActionRef("");
      setActionNote("");
      setActionError(null);
      setActionSuccess(t("sa_tenant.billing.mark_paid_success"));
      invalidateSubscription();
    },
    onError: (e: unknown) => setActionError(billingErrorMessage(e)),
  });

  const cancelMutation = useMutation({
    mutationFn: (paymentId: string) =>
      api.post(`/api/v1/tenants/${tenantId}/payments/${paymentId}/cancel`, { note: actionNote.trim() }),
    onSuccess: () => {
      setActionRow(null);
      setActionNote("");
      setActionError(null);
      setActionSuccess(t("sa_tenant.billing.cancel_success"));
      invalidateSubscription();
    },
    onError: (e: unknown) => setActionError(billingErrorMessage(e)),
  });

  function toggleAction(paymentId: string, type: "markPaid" | "cancel") {
    setActionRow((cur) => (cur?.paymentId === paymentId && cur.type === type ? null : { paymentId, type }));
    setActionRef("");
    setActionNote("");
    setActionError(null);
    setActionSuccess(null);
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
  const pendingPayment = subscription.payments.find((p) => p.status === "PENDING") ?? null;

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
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">{t("tenant_admin.billing.invoices_heading")}</h3>
          {tenantId && (
            <div className="text-right">
              {raiseConfirm ? (
                <div className="flex items-center gap-2 p-2 bg-gray-50 rounded border border-gray-200">
                  <span className="text-xs text-gray-700">
                    {pendingPayment
                      ? t("sa_tenant.billing.raise_invoice_already_pending")
                      : t("sa_tenant.billing.raise_invoice_confirm")}
                  </span>
                  <button
                    type="button"
                    disabled={raiseMutation.isPending}
                    onClick={() => raiseMutation.mutate()}
                    className="px-2.5 py-1 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50"
                  >
                    {raiseMutation.isPending ? "…" : t("sa_tenant.billing.confirm_yes")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setRaiseConfirm(false)}
                    className="px-2.5 py-1 text-xs font-bold text-gray-600 rounded hover:bg-gray-200"
                  >
                    {t("sa_tenant.billing.confirm_no")}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => { setRaiseConfirm(true); setRaiseResult(null); setRaiseError(null); }}
                  className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35]"
                >
                  {t("sa_tenant.billing.raise_invoice_btn")}
                </button>
              )}
            </div>
          )}
        </div>

        {raiseError && <p className="text-xs text-red-600 mb-3">{raiseError}</p>}
        {raiseResult && (
          <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-3 py-2 mb-3">
            {t("sa_tenant.billing.raise_invoice_success")
              .replace("{period}", `${raiseResult.period_start} → ${raiseResult.period_end}`)
              .replace("{total}", formatCurrency(raiseResult.total, raiseResult.currency))}
          </p>
        )}
        {actionSuccess && (
          <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-3 py-2 mb-3">
            {actionSuccess}
          </p>
        )}

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
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                        <p>{p.period_start} → {p.period_end}</p>
                        <ul className="mt-1 space-y-0.5">
                          {p.line_items.map((li) => (
                            <li key={`${li.item_type}-${li.item_key}`} className="text-[11px] text-gray-400 font-normal">
                              {li.item_type === "ADDON" ? t("tenant_admin.billing.line_item_addon_prefix") : t("tenant_admin.billing.line_item_package_prefix")}
                              {" "}{li.description ?? li.item_key} — {formatCurrency(li.amount, p.currency)}
                            </li>
                          ))}
                        </ul>
                      </td>
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
                        {!tenantId && p.status === "PENDING" && (
                          <button
                            type="button"
                            onClick={() => void handleHowToPay(p.id)}
                            className="text-xs font-semibold text-brand-600 hover:text-brand-700 underline"
                          >
                            {t("tenant_admin.billing.how_to_pay_btn")}
                          </button>
                        )}
                        {tenantId && p.status === "PENDING" && (
                          <div className="flex gap-2 justify-end">
                            <button
                              type="button"
                              onClick={() => toggleAction(p.id, "markPaid")}
                              className="text-xs font-semibold text-emerald-600 hover:text-emerald-700 underline"
                            >
                              {t("sa_tenant.billing.mark_paid_btn")}
                            </button>
                            <button
                              type="button"
                              onClick={() => toggleAction(p.id, "cancel")}
                              className="text-xs font-semibold text-red-600 hover:text-red-700 underline"
                            >
                              {t("sa_tenant.billing.cancel_invoice_btn")}
                            </button>
                          </div>
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
                    {actionRow?.paymentId === p.id && actionRow.type === "markPaid" && (
                      <tr className="border-b border-gray-100 bg-emerald-50">
                        <td colSpan={7} className="px-3 py-3">
                          <p className="text-xs text-emerald-900 mb-2">
                            {t("sa_tenant.billing.mark_paid_confirm")
                              .replace("{amount}", formatCurrency(p.total, p.currency))
                              .replace("{contract_end}", p.period_end)}
                          </p>
                          <div className="flex flex-wrap gap-2 items-end">
                            <div>
                              <label className="block text-[11px] font-semibold text-gray-600 mb-1">
                                {t("sa_tenant.billing.provider_reference_label")}
                              </label>
                              <input
                                type="text"
                                value={actionRef}
                                onChange={(e) => setActionRef(e.target.value)}
                                className="px-2 py-1 text-xs border border-gray-300 rounded-md outline-none focus:border-emerald-600"
                              />
                            </div>
                            <div className="flex-1 min-w-[160px]">
                              <label className="block text-[11px] font-semibold text-gray-600 mb-1">
                                {t("sa_tenant.billing.note_optional_label")}
                              </label>
                              <input
                                type="text"
                                value={actionNote}
                                onChange={(e) => setActionNote(e.target.value)}
                                className="w-full px-2 py-1 text-xs border border-gray-300 rounded-md outline-none focus:border-emerald-600"
                              />
                            </div>
                            <button
                              type="button"
                              disabled={markPaidMutation.isPending}
                              onClick={() => markPaidMutation.mutate(p.id)}
                              className="px-3 py-1.5 text-xs font-bold text-white bg-emerald-600 rounded hover:bg-emerald-700 disabled:opacity-50"
                            >
                              {markPaidMutation.isPending ? "…" : t("sa_tenant.billing.confirm_yes")}
                            </button>
                            <button
                              type="button"
                              onClick={() => setActionRow(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200"
                            >
                              {t("sa_tenant.billing.confirm_no")}
                            </button>
                          </div>
                          {actionError && <p className="text-xs text-red-600 mt-2">{actionError}</p>}
                        </td>
                      </tr>
                    )}
                    {actionRow?.paymentId === p.id && actionRow.type === "cancel" && (
                      <tr className="border-b border-gray-100 bg-red-50">
                        <td colSpan={7} className="px-3 py-3">
                          <div className="flex flex-wrap gap-2 items-end">
                            <div className="flex-1 min-w-[200px]">
                              <label className="block text-[11px] font-semibold text-gray-600 mb-1">
                                {t("sa_tenant.billing.note_required_label")}
                              </label>
                              <input
                                type="text"
                                value={actionNote}
                                onChange={(e) => setActionNote(e.target.value)}
                                className="w-full px-2 py-1 text-xs border border-gray-300 rounded-md outline-none focus:border-red-600"
                              />
                            </div>
                            <button
                              type="button"
                              disabled={cancelMutation.isPending || !actionNote.trim()}
                              onClick={() => cancelMutation.mutate(p.id)}
                              className="px-3 py-1.5 text-xs font-bold text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50"
                            >
                              {cancelMutation.isPending ? "…" : t("sa_tenant.billing.confirm_yes")}
                            </button>
                            <button
                              type="button"
                              onClick={() => setActionRow(null)}
                              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200"
                            >
                              {t("sa_tenant.billing.confirm_no")}
                            </button>
                          </div>
                          {actionError && <p className="text-xs text-red-600 mt-2">{actionError}</p>}
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

// Read-only in both TA and SA modes — management (grant/cancel) lives on the
// Features tab's TenantAddonsSection (SA only). See CLAUDE.md §15 S10.
function AddonsReadOnlySection({ tenantId }: { tenantId?: string }) {
  const path = tenantId ? `/api/v1/tenants/${tenantId}/addons` : `/api/v1/tenants/me/addons`;
  const { data: addons, isLoading } = useQuery<TenantAddonOut[]>({
    queryKey: ["tenant-addons-readonly", tenantId ?? "me"],
    queryFn: () => api.get<TenantAddonOut[]>(path),
    staleTime: 10_000,
  });

  if (isLoading) return null;

  const active = (addons ?? []).filter((a) => a.status === "ACTIVE");
  const cancelled = (addons ?? []).filter((a) => a.status === "CANCELLED");

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("tenant_admin.plan.addons_heading")}</h3>
      {active.length === 0 && cancelled.length === 0 ? (
        <p className="text-sm text-gray-500">{t("sa_tenant.addons.empty")}</p>
      ) : (
        <div className="space-y-2">
          {active.map((a) => (
            <div key={a.id} className="flex items-center justify-between border border-gray-200 rounded px-3 py-2">
              <p className="text-sm font-semibold text-gray-800">{a.display_name}</p>
              <p className="text-xs text-gray-500">
                {a.source === "OVERRIDE" ? t("sa_tenant.addons.source_override") : t("sa_tenant.addons.source_purchased")}
                {" · "}{t("sa_tenant.addons.since_label")} {a.starts_on}
                {a.source === "PURCHASED" && ` · ${formatCurrency(a.amount, a.currency)}`}
              </p>
            </div>
          ))}
          {cancelled.map((a) => (
            <p key={a.id} className="text-xs text-gray-400">
              {a.display_name} — {t("sa_tenant.addons.since_label")} {a.starts_on} {t("sa_tenant.addons.until_label")} {a.cancelled_at?.slice(0, 10) ?? "—"}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function PlanTab({ tenantId, isLoading }: TabProps) {
  const planPath = tenantId ? `/api/v1/tenants/${tenantId}/plan` : `/api/v1/tenants/me/plan`;
  const { data: plan, isLoading: loadingPlan } = useQuery<PlanData>({
    queryKey: ["tenant-admin-plan", tenantId ?? "me"],
    queryFn: () => api.get<PlanData>(planPath),
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

        {!tenantId && (
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <p className="text-sm text-blue-900">💡 {t("tenant_admin.plan.upgrade_hint")}</p>
          </div>
        )}
      </div>

      {/* SA mode: tier change + SKU cap, above billing (CLAUDE.md §15 S9) */}
      {tenantId && <TierChangeForm tenantId={tenantId} plan={plan} />}

      <SubscriptionAndInvoices tenantId={tenantId} />

      <AddonsReadOnlySection tenantId={tenantId} />

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

      {/* Request Upgrade CTA — TA only; an SA managing the tenant has no one to ask */}
      {!tenantId && (
        <div className="bg-gradient-to-r from-emerald-50 to-blue-50 rounded-lg border border-emerald-200 p-6">
          <h4 className="font-semibold text-gray-800 mb-2">{t("tenant_admin.plan.ready_to_upgrade")}</h4>
          <p className="text-sm text-gray-700 mb-4">
            {t("tenant_admin.plan.upgrade_cta_text")}
          </p>
          <button className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded hover:bg-emerald-700">
            {t("tenant_admin.plan.request_upgrade_btn")}
          </button>
        </div>
      )}
    </div>
  );
}
