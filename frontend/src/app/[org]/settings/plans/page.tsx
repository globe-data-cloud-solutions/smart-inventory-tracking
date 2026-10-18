"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { api } from "@/lib/api";

/* ── Types (mirror backend response shapes — amounts are strings, per the API) ── */

interface TierConfigEntry {
  tier: string;
  max_warehouses: number | null;
  max_users: number | null;
  display_name: string | null;
  sku_cap: number | null;
  feature_flags: Record<string, boolean>;
  is_public: boolean | null;
  sort_order: number | null;
}

interface PriceHistoryEntry {
  id: string;
  amount: string;
  currency: string;
  effective_from: string;
  reason: string;
  created_by: string | null;
  created_by_email: string | null;
  created_at: string;
}

interface PriceSnapshot {
  id: string;
  amount: string;
  currency: string;
  effective_from: string;
  subtotal: string;
  vat_rate: string;
  vat_amount: string;
  total: string;
}

interface TierPricing {
  tier: string;
  billing_period: string;
  current: PriceSnapshot | null;
  scheduled: PriceHistoryEntry[];
  history: PriceHistoryEntry[];
}

interface AddonPricing {
  billing_period: string;
  current: PriceSnapshot | null;
  scheduled: PriceHistoryEntry[];
  history: PriceHistoryEntry[];
}

interface AddonCatalogEntry {
  code: string;
  display_name: string;
  description: string | null;
  is_active: boolean;
  is_public: boolean;
  sort_order: number;
  prices: AddonPricing[];
}

interface ConfigLogEntry {
  id: string;
  entity_type: string;
  entity_key: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  reason: string | null;
  actor_email: string | null;
  created_at: string;
}

const TIERS = ["STARTER", "GROWTH", "ENTERPRISE"] as const;
const PERIODS = ["MONTHLY", "ANNUAL"] as const;
const FEATURE_FLAG_CODES = [
  "CORE_INVENTORY", "TRANSFERS_PULL_PUSH", "TRANSFERS_SISTER", "LOT_TRACEABILITY",
  "LOGISTICS", "AUDIT_EXPORT", "CUSTOM_BRANDING", "AI_ANALYTICS", "API_ACCESS",
] as const;

const TIER_BADGE: Record<string, string> = {
  STARTER: "bg-gray-100 text-gray-600",
  GROWTH: "bg-blue-100 text-blue-700",
  ENTERPRISE: "bg-amber-100 text-amber-700",
};

function money(amount: string, currency: string): string {
  const n = Number(amount);
  return `${Number.isFinite(n) ? n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : amount} ${currency}`;
}

/* ── Main page ─────────────────────────────────────────────────────────────── */

type TabId = "packages" | "prices" | "addons" | "history";

export default function PlansAndPricingPage() {
  const session = getSession();
  const [tab, setTab] = useState<TabId>("packages");

  if (!session || session.role !== "SA") {
    return <p className="p-8 text-gray-500">{t("platform_plans.restricted")}</p>;
  }

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="bg-white border-b border-gray-200 px-6 py-6">
        <h1 className="text-2xl font-bold text-gray-900">{t("platform_plans.title")}</h1>
        <p className="text-sm text-gray-600 mt-1">{t("platform_plans.subtitle")}</p>
      </div>

      <div className="bg-white border-b border-gray-200 px-6">
        <div className="flex gap-8">
          {(["packages", "prices", "addons", "history"] as const).map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`px-1 py-3 text-sm font-semibold border-b-2 -mb-px transition-colors ${
                tab === id ? "border-[#0f2d1f] text-[#0f2d1f]" : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t(`platform_plans.tab_${id}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="p-6 max-w-5xl mx-auto">
        {tab === "packages" && <PackagesTab />}
        {tab === "prices" && <PricesTab />}
        {tab === "addons" && <AddonsTab />}
        {tab === "history" && <HistoryTab />}
      </div>
    </div>
  );
}

/* ── Tab 1: Packages ──────────────────────────────────────────────────────── */

function PackagesTab() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery<TierConfigEntry[]>({
    queryKey: ["platform-tier-config"],
    queryFn: () => api.get<TierConfigEntry[]>("/api/v1/tenants/platform/tier-config"),
    staleTime: 0,
  });

  const [drafts, setDrafts] = useState<Record<string, TierConfigEntry>>({});
  const [reason, setReason] = useState("");
  const [savingTier, setSavingTier] = useState<string | null>(null);
  const [errorByTier, setErrorByTier] = useState<Record<string, string>>({});
  const [savedTier, setSavedTier] = useState<string | null>(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (data && !initialized.current) {
      setDrafts(Object.fromEntries(data.map((row) => [row.tier, row])));
      initialized.current = true;
    }
  }, [data]);

  function updateDraft(tier: string, patch: Partial<TierConfigEntry>) {
    setDrafts((d) => ({ ...d, [tier]: { ...d[tier]!, ...patch } }));
  }

  async function handleSave(tier: string) {
    const draft = drafts[tier];
    if (!draft || !reason.trim()) return;
    setSavingTier(tier);
    setErrorByTier((e) => ({ ...e, [tier]: "" }));
    setSavedTier(null);
    try {
      await api.patch("/api/v1/tenants/platform/tier-config", { reason, tiers: [draft] });
      await qc.invalidateQueries({ queryKey: ["platform-tier-config"] });
      await qc.invalidateQueries({ queryKey: ["platform-config-log"] });
      setSavedTier(tier);
    } catch (e: unknown) {
      setErrorByTier((err) => ({ ...err, [tier]: e instanceof Error ? e.message : t("platform_plans.error_generic") }));
    } finally {
      setSavingTier(null);
    }
  }

  function handleReset(tier: string) {
    const original = data?.find((r) => r.tier === tier);
    if (original) updateDraft(tier, original);
    setErrorByTier((e) => ({ ...e, [tier]: "" }));
    setSavedTier(null);
  }

  if (isLoading) return <p className="text-gray-400 text-sm">{t("common.loading")}</p>;
  if (isError || !data) return <p className="text-red-500 text-sm">{t("common.error")}</p>;

  const sortedTiers = [...data].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">{t("platform_plans.packages_note")}</p>

      <div>
        <label className="block text-xs font-bold text-gray-600 mb-1">
          {t("platform_plans.reason_label")} <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t("platform_plans.reason_placeholder")}
          className="w-full max-w-md px-3 py-2 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {sortedTiers.map((row) => {
          const draft = drafts[row.tier] ?? row;
          const err = errorByTier[row.tier];
          return (
            <div key={row.tier} className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <span className={`text-xs font-extrabold px-2 py-0.5 rounded ${TIER_BADGE[row.tier] ?? "bg-gray-100 text-gray-600"}`}>
                {row.tier}
              </span>

              <div>
                <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.field_display_name")}</label>
                <input
                  type="text"
                  value={draft.display_name ?? ""}
                  onChange={(e) => updateDraft(row.tier, { display_name: e.target.value })}
                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                />
              </div>

              {([
                ["max_warehouses", "field_max_warehouses"],
                ["max_users", "field_max_users"],
                ["sku_cap", "field_sku_cap"],
              ] as const).map(([field, labelKey]) => (
                <div key={field}>
                  <label className="block text-[11px] font-bold text-gray-500 mb-1">{t(`platform_plans.${labelKey}`)}</label>
                  <input
                    type="number"
                    min={1}
                    value={draft[field] ?? ""}
                    placeholder={t("platform_plans.unlimited")}
                    onChange={(e) => {
                      const v = e.target.value === "" ? null : parseInt(e.target.value, 10);
                      updateDraft(row.tier, { [field]: v });
                    }}
                    className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                  />
                </div>
              ))}

              <div>
                <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.field_sort_order")}</label>
                <input
                  type="number"
                  value={draft.sort_order ?? 0}
                  onChange={(e) => updateDraft(row.tier, { sort_order: parseInt(e.target.value, 10) || 0 })}
                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                />
              </div>

              <label className="flex items-center gap-2 text-xs font-semibold text-gray-600">
                <input
                  type="checkbox"
                  checked={draft.is_public ?? false}
                  onChange={(e) => updateDraft(row.tier, { is_public: e.target.checked })}
                />
                {t("platform_plans.field_is_public")}
              </label>

              <div>
                <p className="text-[11px] font-bold text-gray-500 mb-1.5">{t("platform_plans.features_heading")}</p>
                <div className="space-y-1">
                  {FEATURE_FLAG_CODES.map((code) => (
                    <label key={code} className="flex items-center gap-2 text-xs text-gray-700">
                      <input
                        type="checkbox"
                        checked={draft.feature_flags?.[code] ?? false}
                        onChange={(e) =>
                          updateDraft(row.tier, { feature_flags: { ...draft.feature_flags, [code]: e.target.checked } })
                        }
                      />
                      {t(`tenant_admin.features.flag.${code}`)}
                    </label>
                  ))}
                </div>
              </div>

              {err && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">{err}</p>}
              {savedTier === row.tier && (
                <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1.5">
                  {t("platform_plans.saved")}
                </p>
              )}

              <div className="flex items-center justify-between pt-1">
                <button
                  type="button"
                  onClick={() => handleReset(row.tier)}
                  className="text-xs font-semibold text-gray-500 hover:text-gray-700 underline"
                >
                  {t("platform_plans.reset_btn")}
                </button>
                <button
                  type="button"
                  disabled={savingTier === row.tier || !reason.trim()}
                  onClick={() => void handleSave(row.tier)}
                  className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingTier === row.tier ? t("platform_plans.saving") : t("platform_plans.save_btn")}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Tab 2: Prices ─────────────────────────────────────────────────────────── */

function PricesTab() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery<TierPricing[]>({
    queryKey: ["platform-package-prices"],
    queryFn: () => api.get<TierPricing[]>("/api/v1/tenants/platform/packages/prices"),
    staleTime: 0,
  });

  const [form, setForm] = useState({
    tier: "" as string,
    billing_period: "" as string,
    amount: "",
    effective_from: new Date().toISOString().slice(0, 10),
    reason: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      await api.post(`/api/v1/tenants/platform/packages/${form.tier}/prices`, {
        billing_period: form.billing_period,
        amount: form.amount,
        effective_from: form.effective_from,
        reason: form.reason,
      });
      await qc.invalidateQueries({ queryKey: ["platform-package-prices"] });
      await qc.invalidateQueries({ queryKey: ["platform-config-log"] });
      setSuccess(t("platform_plans.prices_note"));
      setForm((f) => ({ ...f, tier: "", billing_period: "", amount: "", reason: "" }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("platform_plans.error_generic"));
    } finally {
      setSubmitting(false);
    }
  }

  if (isLoading) return <p className="text-gray-400 text-sm">{t("common.loading")}</p>;
  if (isError || !data) return <p className="text-red-500 text-sm">{t("common.error")}</p>;

  return (
    <div className="space-y-6">
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-bold text-gray-800 mb-3">{t("platform_plans.prices_set_new")}</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_tier_label")}</label>
            <select
              value={form.tier}
              onChange={(e) => setForm((f) => ({ ...f, tier: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            >
              <option value="" disabled>{t("platform_plans.select_placeholder")}</option>
              {TIERS.map((tr) => (
                <option key={tr} value={tr}>{tr}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_period_label")}</label>
            <select
              value={form.billing_period}
              onChange={(e) => setForm((f) => ({ ...f, billing_period: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            >
              <option value="" disabled>{t("platform_plans.select_placeholder")}</option>
              <option value="MONTHLY">{t("platform_plans.prices_monthly")}</option>
              <option value="ANNUAL">{t("platform_plans.prices_annual")}</option>
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_amount_label")}</label>
            <input
              type="number"
              min={0}
              step="0.01"
              value={form.amount}
              onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_effective_label")}</label>
            <input
              type="date"
              value={form.effective_from}
              onChange={(e) => setForm((f) => ({ ...f, effective_from: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.reason_label")}</label>
            <input
              type="text"
              value={form.reason}
              onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
              placeholder={t("platform_plans.reason_placeholder")}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            />
          </div>
        </div>
        <p className="text-[11px] text-gray-400 mt-2">{t("platform_plans.prices_note")}</p>
        {error && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5 mt-2">{error}</p>}
        {success && <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1.5 mt-2">{success}</p>}
        <div className="flex justify-end mt-3">
          <button
            type="button"
            disabled={submitting || !form.tier || !form.billing_period || !form.amount || !form.reason.trim()}
            onClick={() => void handleSubmit()}
            className="px-4 py-2 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? t("platform_plans.saving") : t("platform_plans.prices_submit_btn")}
          </button>
        </div>
      </div>

      {TIERS.map((tier) => (
        <div key={tier} className="bg-white border border-gray-200 rounded-lg p-4">
          <span className={`text-xs font-extrabold px-2 py-0.5 rounded ${TIER_BADGE[tier]}`}>{tier}</span>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
            {PERIODS.map((period) => {
              const pricing = data.find((p) => p.tier === tier && p.billing_period === period);
              return (
                <div key={period} className="border border-gray-100 rounded p-3">
                  <h4 className="text-xs font-bold text-gray-700 mb-2">
                    {period === "MONTHLY" ? t("platform_plans.prices_monthly") : t("platform_plans.prices_annual")}
                  </h4>

                  <p className="text-[11px] font-bold text-gray-400 uppercase mb-1">{t("platform_plans.prices_current")}</p>
                  {pricing?.current ? (
                    <div className="text-sm text-gray-800 mb-3">
                      <p className="m-0 font-semibold">{money(pricing.current.amount, pricing.current.currency)}</p>
                      <p className="m-0 text-[11px] text-gray-400">
                        {t("platform_plans.prices_since")} {pricing.current.effective_from.slice(0, 10)} ·
                        {" "}{t("platform_plans.prices_vat_total")}: {money(pricing.current.total, pricing.current.currency)}
                      </p>
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 mb-3">{t("platform_plans.prices_no_current")}</p>
                  )}

                  <p className="text-[11px] font-bold text-gray-400 uppercase mb-1">{t("platform_plans.prices_scheduled")}</p>
                  {pricing && pricing.scheduled.length > 0 ? (
                    <ul className="text-xs text-gray-600 mb-3 space-y-0.5">
                      {pricing.scheduled.map((s) => (
                        <li key={s.id}>{money(s.amount, s.currency)} — {t("platform_plans.prices_since")} {s.effective_from.slice(0, 10)}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-gray-400 mb-3">{t("platform_plans.prices_no_scheduled")}</p>
                  )}

                  <p className="text-[11px] font-bold text-gray-400 uppercase mb-1">{t("platform_plans.prices_history")}</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[11px] border-collapse">
                      <tbody>
                        {(pricing?.history ?? []).map((h) => (
                          <tr key={h.id} className="border-b border-gray-50">
                            <td className="py-1 pr-2 text-gray-500 whitespace-nowrap">{h.effective_from.slice(0, 10)}</td>
                            <td className="py-1 pr-2 font-semibold text-gray-700 whitespace-nowrap">{money(h.amount, h.currency)}</td>
                            <td className="py-1 text-gray-500">{h.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Tab 3: Add-ons ───────────────────────────────────────────────────────── */

function AddonsTab() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery<AddonCatalogEntry[]>({
    queryKey: ["platform-addons"],
    queryFn: () => api.get<AddonCatalogEntry[]>("/api/v1/tenants/platform/addons"),
    staleTime: 0,
  });

  const [drafts, setDrafts] = useState<Record<string, AddonCatalogEntry>>({});
  const [catalogReason, setCatalogReason] = useState("");
  const [savingCode, setSavingCode] = useState<string | null>(null);
  const [errorByCode, setErrorByCode] = useState<Record<string, string>>({});
  const [savedCode, setSavedCode] = useState<string | null>(null);
  const initialized = useRef(false);

  const [priceForm, setPriceForm] = useState({
    addon_code: "",
    billing_period: "" as string,
    amount: "",
    effective_from: new Date().toISOString().slice(0, 10),
    reason: "",
  });
  const [priceSubmitting, setPriceSubmitting] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [priceSuccess, setPriceSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (data && !initialized.current) {
      setDrafts(Object.fromEntries(data.map((row) => [row.code, row])));
      initialized.current = true;
    }
  }, [data]);

  function updateDraft(code: string, patch: Partial<AddonCatalogEntry>) {
    setDrafts((d) => ({ ...d, [code]: { ...d[code]!, ...patch } }));
  }

  async function handleSaveCatalog(code: string) {
    const draft = drafts[code];
    if (!draft || !catalogReason.trim()) return;
    setSavingCode(code);
    setErrorByCode((e) => ({ ...e, [code]: "" }));
    setSavedCode(null);
    try {
      await api.patch(`/api/v1/tenants/platform/addons/${code}`, {
        display_name: draft.display_name,
        description: draft.description,
        is_active: draft.is_active,
        is_public: draft.is_public,
        sort_order: draft.sort_order,
        reason: catalogReason,
      });
      await qc.invalidateQueries({ queryKey: ["platform-addons"] });
      await qc.invalidateQueries({ queryKey: ["platform-config-log"] });
      setSavedCode(code);
    } catch (e: unknown) {
      setErrorByCode((err) => ({ ...err, [code]: e instanceof Error ? e.message : t("platform_plans.error_generic") }));
    } finally {
      setSavingCode(null);
    }
  }

  async function handleSubmitPrice() {
    setPriceSubmitting(true);
    setPriceError(null);
    setPriceSuccess(null);
    try {
      await api.post(`/api/v1/tenants/platform/addons/${priceForm.addon_code}/prices`, {
        billing_period: priceForm.billing_period,
        amount: priceForm.amount,
        effective_from: priceForm.effective_from,
        reason: priceForm.reason,
      });
      await qc.invalidateQueries({ queryKey: ["platform-addons"] });
      await qc.invalidateQueries({ queryKey: ["platform-config-log"] });
      setPriceSuccess(t("platform_plans.addons_price_saved"));
      setPriceForm((f) => ({ ...f, addon_code: "", billing_period: "", amount: "", reason: "" }));
    } catch (e: unknown) {
      setPriceError(e instanceof Error ? e.message : t("platform_plans.error_generic"));
    } finally {
      setPriceSubmitting(false);
    }
  }

  if (isLoading) return <p className="text-gray-400 text-sm">{t("common.loading")}</p>;
  if (isError || !data) return <p className="text-red-500 text-sm">{t("common.error")}</p>;

  const sorted = [...data].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">{t("platform_plans.addons_note")}</p>

      {/* Set new price */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-bold text-gray-800 mb-3">{t("platform_plans.addons_set_price")}</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.addons_code_label")}</label>
            <select
              value={priceForm.addon_code}
              onChange={(e) => setPriceForm((f) => ({ ...f, addon_code: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            >
              <option value="" disabled>{t("platform_plans.select_placeholder")}</option>
              {sorted.map((a) => (
                <option key={a.code} value={a.code}>{a.display_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_period_label")}</label>
            <select
              value={priceForm.billing_period}
              onChange={(e) => setPriceForm((f) => ({ ...f, billing_period: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            >
              <option value="" disabled>{t("platform_plans.select_placeholder")}</option>
              <option value="MONTHLY">{t("platform_plans.prices_monthly")}</option>
              <option value="ANNUAL">{t("platform_plans.prices_annual")}</option>
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_amount_label")}</label>
            <input
              type="number"
              min={0}
              step="0.01"
              value={priceForm.amount}
              onChange={(e) => setPriceForm((f) => ({ ...f, amount: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.prices_effective_label")}</label>
            <input
              type="date"
              value={priceForm.effective_from}
              onChange={(e) => setPriceForm((f) => ({ ...f, effective_from: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.reason_label")}</label>
            <input
              type="text"
              value={priceForm.reason}
              onChange={(e) => setPriceForm((f) => ({ ...f, reason: e.target.value }))}
              placeholder={t("platform_plans.reason_placeholder")}
              className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
            />
          </div>
        </div>
        {priceError && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5 mt-2">{priceError}</p>}
        {priceSuccess && <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1.5 mt-2">{priceSuccess}</p>}
        <div className="flex justify-end mt-3">
          <button
            type="button"
            disabled={priceSubmitting || !priceForm.addon_code || !priceForm.billing_period || !priceForm.amount || !priceForm.reason.trim()}
            onClick={() => void handleSubmitPrice()}
            className="px-4 py-2 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {priceSubmitting ? t("platform_plans.saving") : t("platform_plans.prices_submit_btn")}
          </button>
        </div>
      </div>

      {/* Catalog edit reason */}
      <div>
        <label className="block text-xs font-bold text-gray-600 mb-1">
          {t("platform_plans.reason_label")} <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={catalogReason}
          onChange={(e) => setCatalogReason(e.target.value)}
          placeholder={t("platform_plans.reason_placeholder")}
          className="w-full max-w-md px-3 py-2 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {sorted.map((row) => {
          const draft = drafts[row.code] ?? row;
          const err = errorByCode[row.code];
          return (
            <div key={row.code} className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <span className="text-xs font-extrabold px-2 py-0.5 rounded bg-indigo-100 text-indigo-700">{row.code}</span>

              <div>
                <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.field_display_name")}</label>
                <input
                  type="text"
                  value={draft.display_name}
                  onChange={(e) => updateDraft(row.code, { display_name: e.target.value })}
                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.addons_description_label")}</label>
                <input
                  type="text"
                  value={draft.description ?? ""}
                  onChange={(e) => updateDraft(row.code, { description: e.target.value })}
                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.field_sort_order")}</label>
                <input
                  type="number"
                  value={draft.sort_order}
                  onChange={(e) => updateDraft(row.code, { sort_order: parseInt(e.target.value, 10) || 0 })}
                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
                />
              </div>

              <div className="flex gap-4">
                <label className="flex items-center gap-2 text-xs font-semibold text-gray-600">
                  <input
                    type="checkbox"
                    checked={draft.is_active}
                    onChange={(e) => updateDraft(row.code, { is_active: e.target.checked })}
                  />
                  {t("platform_plans.addons_is_active")}
                </label>
                <label className="flex items-center gap-2 text-xs font-semibold text-gray-600">
                  <input
                    type="checkbox"
                    checked={draft.is_public}
                    onChange={(e) => updateDraft(row.code, { is_public: e.target.checked })}
                  />
                  {t("platform_plans.field_is_public")}
                </label>
              </div>

              <div className="border-t border-gray-100 pt-2">
                {row.prices.map((p) => (
                  <div key={p.billing_period} className="text-xs text-gray-600 mb-1">
                    <span className="font-bold text-gray-500">
                      {p.billing_period === "MONTHLY" ? t("platform_plans.prices_monthly") : t("platform_plans.prices_annual")}:
                    </span>{" "}
                    {p.current
                      ? money(p.current.amount, p.current.currency)
                      : t("platform_plans.prices_no_current")}
                    {p.scheduled.length > 0 && (
                      <span className="text-gray-400">
                        {" "}· {t("platform_plans.prices_scheduled")}: {money(p.scheduled[0]!.amount, p.scheduled[0]!.currency)}
                      </span>
                    )}
                  </div>
                ))}
              </div>

              {err && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">{err}</p>}
              {savedCode === row.code && (
                <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1.5">
                  {t("platform_plans.saved")}
                </p>
              )}

              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  disabled={savingCode === row.code || !catalogReason.trim()}
                  onClick={() => void handleSaveCatalog(row.code)}
                  className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingCode === row.code ? t("platform_plans.saving") : t("platform_plans.save_btn")}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Tab 4: Change history ────────────────────────────────────────────────── */

function HistoryTab() {
  const [entityType, setEntityType] = useState("");
  const [entityKey, setEntityKey] = useState("");

  const { data, isLoading, isError } = useQuery<ConfigLogEntry[]>({
    queryKey: ["platform-config-log", entityType, entityKey],
    queryFn: () => {
      const params = new URLSearchParams({ limit: "100" });
      if (entityType) params.set("entity_type", entityType);
      if (entityKey) params.set("entity_key", entityKey);
      return api.get<ConfigLogEntry[]>(`/api/v1/tenants/platform/config-log?${params.toString()}`);
    },
    staleTime: 0,
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-3 items-end">
        <div>
          <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.history_filter_entity_type")}</label>
          <select
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            className="px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
          >
            <option value="">{t("common.all")}</option>
            {/* i18n-ignore: backend entity_type enum code, not translated */}
            <option value="PACKAGE">PACKAGE</option>
            {/* i18n-ignore: backend entity_type enum code, not translated */}
            <option value="PRICE">PRICE</option>
            {/* i18n-ignore: backend entity_type enum code, not translated */}
            <option value="ADDON">ADDON</option>
            <option value="ADDON_PRICE">ADDON_PRICE</option>
          </select>
        </div>
        <div>
          <label className="block text-[11px] font-bold text-gray-500 mb-1">{t("platform_plans.history_filter_entity_key")}</label>
          <input
            type="text"
            value={entityKey}
            onChange={(e) => setEntityKey(e.target.value)}
            // i18n-ignore: example plan/price key codes
            placeholder="STARTER, STARTER/MONTHLY…"
            className="px-2 py-1.5 text-sm border border-gray-300 rounded outline-none"
          />
        </div>
      </div>

      {isLoading && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
      {isError && <p className="text-red-500 text-sm">{t("common.error")}</p>}
      {!isLoading && !isError && (
        <div className="bg-white border border-gray-200 rounded overflow-x-auto">
          <table className="w-full border-collapse text-sm min-w-[800px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                {[
                  "history_col_date", "history_col_entity", "history_col_field",
                  "history_col_old", "history_col_new", "history_col_reason", "history_col_by",
                ].map((key) => (
                  <th key={key} className="px-3 py-2 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    {t(`platform_plans.${key}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(!data || data.length === 0) && (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-sm text-gray-400">{t("common.no_data")}</td>
                </tr>
              )}
              {(data ?? []).map((row) => (
                <tr key={row.id} className="border-b border-gray-100">
                  <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{row.created_at.slice(0, 19).replace("T", " ")}</td>
                  <td className="px-3 py-2 text-xs text-gray-700 whitespace-nowrap">{row.entity_type} / {row.entity_key}</td>
                  <td className="px-3 py-2 text-xs text-gray-700 whitespace-nowrap">{row.field ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-gray-500 max-w-[160px] truncate">{row.old_value ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-gray-700 max-w-[160px] truncate">{row.new_value ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-gray-500 max-w-[200px] truncate">{row.reason ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{row.actor_email ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
