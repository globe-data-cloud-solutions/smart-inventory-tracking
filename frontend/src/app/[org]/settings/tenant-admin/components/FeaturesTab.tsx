"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatCurrency } from "@/lib/utils";
import { PlanComparisonModal } from "@/components/features/billing/PlanComparisonModal";
import { PublicContactLink } from "@/components/features/auth/PublicContactLink";
import { ContactModal } from "@/components/features/contact/ContactModal";
import { TabProps, PlanData, TenantAddonOut, ProrationPreview, ProrationInvoiceOut } from "../types";

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

function RequestUpgradeSection({ planTier }: { planTier: string }) {
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

interface AddonCatalogEntry {
  code: string;
  display_name: string;
  is_active: boolean;
  prices: { billing_period: string; current: { amount: string; currency: string } | null }[];
}

const ADDON_ERROR_CODES = new Set([
  "ADDON_NOT_FOUND", "ADDON_INACTIVE", "FEATURE_ALREADY_IN_PACKAGE", "ADDON_ALREADY_ACTIVE",
  "NOTE_REQUIRED", "NO_LIVE_SUBSCRIPTION", "ADDON_PRICE_NOT_AVAILABLE",
  "ADDON_GRANT_NOT_FOUND", "ADDON_NOT_ACTIVE", "INVALID_SOURCE", "INVOICE_PENDING_SETTLE_FIRST",
]);

function addonErrorMessage(e: unknown): string {
  const code = (e as { code?: string } | undefined)?.code;
  if (code && ADDON_ERROR_CODES.has(code)) return t(`sa_tenant.addon_error.${code}`);
  return e instanceof Error ? e.message : t("common.error");
}

// SA-only (tenantId present): replaces the old raw feature-flag override
// toggles (PATCH /{tenant_id}/feature-flags, removed S10) — overrides are now
// expressed as free OVERRIDE or priced PURCHASED add-ons (migration 072),
// which survive a plan change by construction (get_tenant_entitlements()).
function TenantAddonsSection({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const addonsQueryKey = ["tenant-addons", tenantId];

  const { data: addons } = useQuery<TenantAddonOut[]>({
    queryKey: addonsQueryKey,
    queryFn: () => api.get<TenantAddonOut[]>(`/api/v1/tenants/${tenantId}/addons`),
    staleTime: 10_000,
  });
  const { data: catalog } = useQuery<AddonCatalogEntry[]>({
    queryKey: ["platform-addons-catalog"],
    queryFn: () => api.get<AddonCatalogEntry[]>("/api/v1/tenants/platform/addons"),
    staleTime: 60_000,
  });
  const { data: subscription } = useQuery<{ billing_period: string | null }>({
    queryKey: ["tenant-admin-subscription", tenantId],
    queryFn: () => api.get(`/api/v1/tenants/${tenantId}/subscription`),
    staleTime: 30_000,
  });

  const [grantForm, setGrantForm] = useState<{ source: "OVERRIDE" | "PURCHASED"; code: string; note: string } | null>(null);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [grantedInvoice, setGrantedInvoice] = useState<ProrationInvoiceOut | null>(null);
  const [cancelRow, setCancelRow] = useState<string | null>(null);
  const [cancelNote, setCancelNote] = useState("");
  const [cancelError, setCancelError] = useState<string | null>(null);

  const { data: addonPreview, isLoading: loadingAddonPreview } = useQuery<ProrationPreview>({
    queryKey: ["proration-preview", tenantId, "addon", grantForm?.code],
    queryFn: () => api.get<ProrationPreview>(
      `/api/v1/tenants/${tenantId}/proration-preview?addon=${encodeURIComponent(grantForm!.code)}`,
    ),
    enabled: grantForm?.source === "PURCHASED" && !!grantForm.code,
    staleTime: 10_000,
  });

  function invalidate() {
    void qc.invalidateQueries({ queryKey: addonsQueryKey });
    void qc.invalidateQueries({ queryKey: ["tenant-admin-features", tenantId] });
    void qc.invalidateQueries({ queryKey: ["tenant-admin-plan", tenantId] });
  }

  const grantMutation = useMutation({
    mutationFn: (body: { addon_code: string; source: string; note?: string }) =>
      api.post<{ proration_invoice: ProrationInvoiceOut | null }>(`/api/v1/tenants/${tenantId}/addons`, body),
    onSuccess: (data) => {
      setGrantForm(null);
      setGrantError(null);
      setGrantedInvoice(data.proration_invoice ?? null);
      invalidate();
    },
    onError: (e: unknown) => setGrantError(addonErrorMessage(e)),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/tenants/${tenantId}/addons/${id}/cancel`, { note: cancelNote.trim() }),
    onSuccess: () => { setCancelRow(null); setCancelNote(""); setCancelError(null); invalidate(); },
    onError: (e: unknown) => setCancelError(addonErrorMessage(e)),
  });

  const active = (addons ?? []).filter((a) => a.status === "ACTIVE");
  const cancelled = (addons ?? []).filter((a) => a.status === "CANCELLED");
  const activeCodes = new Set(active.map((a) => a.addon_code));
  const pickable = (catalog ?? []).filter((c) => c.is_active && !activeCodes.has(c.code));

  const previewEntry = grantForm?.source === "PURCHASED" ? catalog?.find((c) => c.code === grantForm.code) : null;
  const previewPrice = previewEntry?.prices.find((p) => p.billing_period === subscription?.billing_period)?.current ?? null;

  function startGrant(source: "OVERRIDE" | "PURCHASED") {
    setGrantForm({ source, code: pickable[0]?.code ?? "", note: "" });
    setGrantError(null);
    setGrantedInvoice(null);
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa_tenant.addons.heading")}</h3>

      <p className="text-xs font-bold text-gray-500 uppercase mb-2">{t("sa_tenant.addons.active_heading")}</p>
      {active.length === 0 ? (
        <p className="text-sm text-gray-500 mb-4">{t("sa_tenant.addons.empty")}</p>
      ) : (
        <div className="space-y-2 mb-4">
          {active.map((a) => (
            <div key={a.id} className="flex items-center justify-between border border-gray-200 rounded px-3 py-2">
              <div>
                <p className="text-sm font-semibold text-gray-800">{a.display_name}</p>
                <p className="text-xs text-gray-500">
                  {a.source === "OVERRIDE" ? t("sa_tenant.addons.source_override") : t("sa_tenant.addons.source_purchased")}
                  {" · "}{t("sa_tenant.addons.since_label")} {a.starts_on}
                  {a.source === "PURCHASED" && ` · ${formatCurrency(a.amount, a.currency)}`}
                </p>
              </div>
              {cancelRow === a.id ? (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={cancelNote}
                    onChange={(e) => setCancelNote(e.target.value)}
                    placeholder={t("sa_tenant.addons.note_required_label")}
                    className="px-2 py-1 text-xs border border-gray-300 rounded outline-none focus:border-red-600"
                  />
                  <button type="button" disabled={cancelMutation.isPending || !cancelNote.trim()}
                    onClick={() => cancelMutation.mutate(a.id)}
                    className="px-2.5 py-1 text-xs font-bold text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50">
                    {t("sa_tenant.billing.confirm_yes")}
                  </button>
                  <button type="button" onClick={() => { setCancelRow(null); setCancelError(null); }}
                    className="px-2.5 py-1 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
                    {t("sa_tenant.billing.confirm_no")}
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => { setCancelRow(a.id); setCancelNote(""); setCancelError(null); }}
                  className="text-xs font-semibold text-red-600 hover:text-red-700 underline">
                  {t("sa_tenant.addons.cancel_btn")}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {cancelError && <p className="text-xs text-red-600 mb-3">{cancelError}</p>}
      {grantedInvoice && (
        <p className="text-xs text-blue-800 bg-blue-50 border border-blue-200 rounded px-3 py-2 mb-3">
          {t("billing.proration.invoice_raised")
            .replace("{period}", `${grantedInvoice.period_start} → ${grantedInvoice.period_end}`)
            .replace("{total}", formatCurrency(grantedInvoice.total, "ETB"))}
        </p>
      )}

      {cancelled.length > 0 && (
        <>
          <p className="text-xs font-bold text-gray-400 uppercase mb-2">{t("sa_tenant.addons.cancelled_heading")}</p>
          <div className="space-y-1 mb-4">
            {cancelled.map((a) => (
              <p key={a.id} className="text-xs text-gray-400">
                {a.display_name} — {t("sa_tenant.addons.since_label")} {a.starts_on} {t("sa_tenant.addons.until_label")} {a.cancelled_at?.slice(0, 10) ?? "—"}
              </p>
            ))}
          </div>
        </>
      )}

      {grantForm ? (
        <div className="p-3 bg-gray-50 rounded border border-gray-200 space-y-2">
          <div className="flex gap-2">
            <select
              value={grantForm.code}
              onChange={(e) => setGrantForm((f) => (f ? { ...f, code: e.target.value } : f))}
              className="px-2 py-1.5 text-xs border border-gray-300 rounded outline-none"
            >
              {pickable.map((c) => (
                <option key={c.code} value={c.code}>{c.display_name}</option>
              ))}
            </select>
            <input
              type="text"
              value={grantForm.note}
              onChange={(e) => setGrantForm((f) => (f ? { ...f, note: e.target.value } : f))}
              placeholder={grantForm.source === "OVERRIDE" ? t("sa_tenant.addons.note_required_label") : t("sa_tenant.addons.note_optional_label")}
              className="flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded outline-none"
            />
          </div>
          {grantForm.source === "PURCHASED" && (
            <>
              <p className="text-xs text-gray-500">
                {previewPrice
                  ? t("sa_tenant.addons.price_preview").replace("{amount}", formatCurrency(previewPrice.amount, previewPrice.currency))
                  : t("sa_tenant.addons.price_unavailable")}
              </p>
              {loadingAddonPreview ? (
                <p className="text-xs text-gray-400">{t("common.loading")}</p>
              ) : addonPreview?.blocked_code ? (
                <p className="text-xs font-semibold text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1.5">
                  {t(`billing.proration.blocked.${addonPreview.blocked_code}`)}
                </p>
              ) : addonPreview?.will_invoice ? (
                <p className="text-xs text-gray-700 bg-blue-50 border border-blue-200 rounded px-2 py-1.5">
                  {t("billing.proration.preview_charge")
                    .replace("{free_until}", addonPreview.free_until ?? "")
                    .replace("{months}", String(addonPreview.remaining_months))
                    .replace("{subtotal}", formatCurrency(addonPreview.subtotal, addonPreview.currency ?? "ETB"))
                    .replace("{vat}", formatCurrency(addonPreview.vat, addonPreview.currency ?? "ETB"))
                    .replace("{total}", formatCurrency(addonPreview.total, addonPreview.currency ?? "ETB"))}
                </p>
              ) : addonPreview ? (
                <p className="text-xs text-gray-500">{t("billing.proration.no_charge_now")}</p>
              ) : null}
            </>
          )}
          {grantError && <p className="text-xs text-red-600">{grantError}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={
                grantMutation.isPending || !grantForm.code ||
                (grantForm.source === "OVERRIDE" && !grantForm.note.trim()) ||
                (grantForm.source === "PURCHASED" && addonPreview?.blocked_code != null)
              }
              onClick={() => grantMutation.mutate({ addon_code: grantForm.code, source: grantForm.source, note: grantForm.note.trim() || undefined })}
              className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50"
            >
              {grantMutation.isPending ? "…" : t("sa_tenant.billing.confirm_yes")}
            </button>
            <button type="button" onClick={() => { setGrantForm(null); setGrantError(null); }}
              className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
              {t("sa_tenant.billing.confirm_no")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <button type="button" disabled={pickable.length === 0} onClick={() => startGrant("OVERRIDE")}
            className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
            {t("sa_tenant.addons.grant_override_btn")}
          </button>
          <button type="button" disabled={pickable.length === 0} onClick={() => startGrant("PURCHASED")}
            className="px-3 py-1.5 text-xs font-bold text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50">
            {t("sa_tenant.addons.add_purchased_btn")}
          </button>
        </div>
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

  const [compareOpen, setCompareOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);

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
          <button
            type="button"
            onClick={() => setCompareOpen(true)}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700"
          >
            {t("tenant_admin.features.view_pricing_btn")}
          </button>
        </div>
      </div>

      {/* Feature List */}
      <div className="space-y-3">
        {Object.entries(FEATURE_MATRIX).map(([key, feature]) => {
          const isIncluded = plan.feature_flags[key] ?? false;
          const isAvailableInCurrentTier = feature.tiers.includes(plan.plan_tier);
          const isFromAddon = plan.addons.includes(key);
          const sourceLabel = isFromAddon
            ? t("tenant_admin.features.source_addon")
            : isIncluded
              ? t("tenant_admin.features.source_package")
              : t("tenant_admin.features.source_not_included");

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
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className="font-semibold text-gray-800">{t(`tenant_admin.features.flag.${key}`)}</h4>
                    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                      isFromAddon ? "bg-indigo-100 text-indigo-700" : isIncluded ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {sourceLabel}
                    </span>
                  </div>
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

      {/* SA mode: per-tenant add-ons (CLAUDE.md §15 S10 — replaces the S9 raw override toggles) */}
      {tenantId && <TenantAddonsSection tenantId={tenantId} />}

      {/* Upgrade CTA */}
      <div className="bg-gradient-to-r from-emerald-50 to-teal-50 rounded-lg border border-emerald-200 p-6">
        <h4 className="font-semibold text-gray-800 mb-2">🚀 {t("tenant_admin.features.want_more_title")}</h4>
        <p className="text-sm text-gray-700 mb-4">
          {t("tenant_admin.features.upgrade_text")}
        </p>
        <div className="flex gap-3 flex-wrap items-center">
          {!tenantId && <RequestUpgradeSection planTier={plan.plan_tier} />}
          <button
            type="button"
            onClick={() => setCompareOpen(true)}
            className="px-4 py-2 text-sm font-medium text-emerald-600 bg-white border border-emerald-600 rounded hover:bg-emerald-50"
          >
            {t("tenant_admin.features.view_plans_btn")}
          </button>
        </div>
      </div>

      {/* Plan Comparison Link */}
      <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 text-center">
        <p className="text-sm text-gray-600">
          {t("tenant_admin.features.need_help_prefix")}{" "}
          <button
            type="button"
            onClick={() => setCompareOpen(true)}
            className="font-semibold text-blue-600 hover:text-blue-700"
          >
            {t("tenant_admin.features.compare_plans_link")}
          </button>{" "}
          <PublicContactLink
            className="font-semibold text-blue-600 hover:text-blue-700"
            prefix={`${t("tenant_admin.features.or_contact_support_prefix")} `}
            labelKey="tenant_admin.features.contact_support_link"
            onClick={() => setContactOpen(true)}
          />
        </p>
      </div>

      <PlanComparisonModal open={compareOpen} onClose={() => setCompareOpen(false)} currentTier={plan.plan_tier} />
      <ContactModal open={contactOpen} onClose={() => setContactOpen(false)} />
    </div>
  );
}
