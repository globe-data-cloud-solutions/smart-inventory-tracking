"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { getSession } from "@/lib/demo-auth";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

/* ── Types ───────────────────────────────────────────────────────────────── */
type OrgType       = "PRODUCER" | "RETAILER" | "HYBRID";
type Locale        = "en" | "am" | "or";
type PlanTier      = "STARTER" | "GROWTH" | "ENTERPRISE";
type BillingPeriod = "MONTHLY" | "ANNUAL";

interface WizardState {
  name:                 string;
  industry:             string;
  skuLimit:             string;
  orgType:              OrgType | "";
  planTier:             PlanTier;
  billingPeriod:        BillingPeriod;
  locale:               Locale;
  adminName:            string;
  adminEmail:           string;
  adminPassword:        string;
  adminPasswordConfirm: string;
  contractStart:        string;
  contractEnd:          string;
}

// Live per-tier limits — never hardcoded (CLAUDE.md §15).
interface TierConfigEntry {
  tier: string;
  max_warehouses: number | null;
  max_users: number | null;
  sku_cap: number | null;
}

function limitText(n: number | null): string {
  return n === null ? t("tenant_admin.plan.unlimited") : String(n);
}

interface ContactEntry {
  id:             string;
  full_name:      string;
  position_title: string;
  email:          string;
  phone:          string;
  mobile:         string;
}

interface AddressState {
  line1:    string;
  line2:    string;
  city:     string;
  state:    string;
  postal:   string;
  country:  string;
}

interface WizardResult {
  id: string; name: string; slug: string; org_type: OrgType;
  feature_flags: Record<string, boolean>;
  adminEmail: string;
}

interface TenantCreateResponse {
  id: string;
  name: string;
  slug: string | null;
  organisation_type: string | null;
  onboarding_complete: boolean;
  default_locale: string;
  is_active: boolean;
}

/* ── Feature flag defaults (mirrors wizard_service.py) ───────────────────── */
const FLAG_DEFAULTS: Record<OrgType, Record<string, boolean>> = {
  PRODUCER: { LOGISTICS: false, AI_ANALYTICS: false, ADVANCED_BATCH_TRACKING: true,  FLEET_MANAGEMENT: false },
  RETAILER: { LOGISTICS: true,  AI_ANALYTICS: true,  ADVANCED_BATCH_TRACKING: false, FLEET_MANAGEMENT: true  },
  HYBRID:   { LOGISTICS: true,  AI_ANALYTICS: true,  ADVANCED_BATCH_TRACKING: true,  FLEET_MANAGEMENT: true  },
};

/* ORG_META color is per-org-type runtime data — style= required for border/bg alpha */
const ORG_META: Record<OrgType, { label: string; desc: string; color: string }> = {
  PRODUCER: { label: t("wizard.org_types.PRODUCER"), color: "#0891B2", desc: t("wizard.org_type_desc.PRODUCER") },
  RETAILER: { label: t("wizard.org_types.RETAILER"), color: "#059669", desc: t("wizard.org_type_desc.RETAILER") },
  HYBRID:   { label: t("wizard.org_types.HYBRID"),   color: "#7C3AED", desc: t("wizard.org_type_desc.HYBRID") },
};

const LOCALE_META: Record<Locale, { label: string; native: string }> = {
  en: { label: "English",               native: "English" },
  am: { label: "Amharic",               native: "አማርኛ" },
  or: { label: "Oromifa (Afaan Oromoo)", native: "Afaan Oromoo" },
};

const TOTAL_STEPS = 6;

function blankContact(): ContactEntry {
  return { id: Math.random().toString(36).slice(2), full_name: "", position_title: "", email: "", phone: "", mobile: "" };
}

function blankAddress(): AddressState {
  return { line1: "", line2: "", city: "", state: "", postal: "", country: "" };
}

/* ── Logo ────────────────────────────────────────────────────────────────── */
function Logo() {
  return (
    <svg width={32} height={32} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <rect width="40" height="40" rx="7" fill="#FCDD09" />
      <polygon points="20,4 36,12 36,24 20,32 4,24 4,12" fill="#0f2d1f" />
      <polygon points="20,10 30,16 30,23 20,29 10,23 10,16" fill="#FCDD09" />
      <polygon points="20,16 25,19 25,23 20,26 15,23 15,19" fill="#0f2d1f" />
    </svg>
  );
}

/* ── Step indicator ──────────────────────────────────────────────────────── */
function StepBar({ current }: { current: number }) {
  const labels = [
    t("wizard.step1_title"),
    t("wizard.step2_title"),
    t("wizard.step3_title"),
    t("wizard.step_admin_title"),
    t("wizard.step_contacts_title"),
    t("wizard.step4_title"),
  ];
  return (
    <div className="flex items-center mb-8">
      {labels.map((label, idx) => {
        const n      = idx + 1;
        const done   = n < current;
        const active = n === current;
        return (
          <div key={label} className={`flex items-center ${idx < labels.length - 1 ? "flex-1" : ""}`}>
            <div className="flex flex-col items-center gap-1">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center font-extrabold text-[13px] ring-2 ${
                done    ? "bg-[#1B4332] text-white ring-transparent" :
                active  ? "bg-[#FCDD09] text-[#0f2d1f] ring-[#1B4332]" :
                          "bg-gray-200 text-gray-400 ring-transparent"
              }`}>
                {done ? "✓" : n}
              </div>
              <span className={`text-[10px] whitespace-nowrap ${active ? "font-bold text-[#1B4332]" : "font-medium text-gray-400"}`}>
                {label}
              </span>
            </div>
            {idx < labels.length - 1 && (
              <div className={`flex-1 h-0.5 mx-2 mb-5 ${done ? "bg-[#1B4332]" : "bg-gray-200"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Flag badge ──────────────────────────────────────────────────────────── */
function FlagBadge({ name, enabled }: { name: string; enabled: boolean }) {
  return (
    <div className={`flex items-center justify-between px-3 py-2 border rounded-md ${enabled ? "bg-green-50 border-green-200" : "bg-gray-50 border-gray-200"}`}>
      <span className="text-[13px] text-gray-700">{name}</span>
      <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-400"}`}>
        {enabled ? t("wizard.enabled") : t("wizard.disabled")}
      </span>
    </div>
  );
}

/* ── Main wizard ─────────────────────────────────────────────────────────── */
export default function OnboardPage() {
  const router = useRouter();

  const [ready, setReady]     = useState(false);
  const [step, setStep]       = useState(1);
  const [loading, setLoading] = useState(false);
  const [result, setResult]   = useState<WizardResult | null>(null);
  const [error, setError]     = useState("");

  const [form, setForm] = useState<WizardState>({
    name: "", industry: "", skuLimit: "500", orgType: "", planTier: "GROWTH", billingPeriod: "ANNUAL", locale: "en",
    adminName: "", adminEmail: "", adminPassword: "", adminPasswordConfirm: "",
    contractStart: "", contractEnd: "",
  });

  const { data: tierConfig } = useQuery<TierConfigEntry[]>({
    queryKey: ["platform-tier-config"],
    queryFn: () => api.get<TierConfigEntry[]>("/api/v1/tenants/platform/tier-config"),
    staleTime: 30_000,
  });

  const [address, setAddress]                       = useState<AddressState>(blankAddress());
  const [primaryContact, setPrimaryContact]         = useState<ContactEntry>(blankContact());
  const [additionalContacts, setAdditionalContacts] = useState<ContactEntry[]>([]);

  useEffect(() => {
    const session = getSession();
    if (!session) { router.replace("/login?from=/onboard"); return; }
    if (session.role !== "SA") { router.replace(`/${session.orgSlug}/dashboard`); return; }
    setReady(true);
  }, [router]);

  function set<K extends keyof WizardState>(k: K, v: WizardState[K]) {
    setForm((f) => ({ ...f, [k]: v }));
    setError("");
  }

  function setAddr(k: keyof AddressState, v: string) {
    setAddress((a) => ({ ...a, [k]: v }));
    setError("");
  }

  function setPrimary(k: keyof ContactEntry, v: string) {
    setPrimaryContact((c) => ({ ...c, [k]: v }));
    setError("");
  }

  function setAdditional(id: string, k: keyof ContactEntry, v: string) {
    setAdditionalContacts((cs) => cs.map((c) => c.id === id ? { ...c, [k]: v } : c));
    setError("");
  }

  function addAdditionalContact() {
    setAdditionalContacts((cs) => [...cs, blankContact()]);
  }

  function removeAdditionalContact(id: string) {
    setAdditionalContacts((cs) => cs.filter((c) => c.id !== id));
  }

  function nextStep() {
    if (step === 1 && !form.name.trim()) { setError(t("wizard.company_required")); return; }
    if (step === 2 && !form.orgType)     { setError(t("wizard.select_org_type"));  return; }
    if (step === 4) {
      if (!form.adminName.trim())                        { setError(t("wizard.admin_name_required"));      return; }
      if (!form.adminEmail.trim())                       { setError(t("wizard.admin_email_required"));     return; }
      if (form.adminPassword.length < 8)                 { setError(t("wizard.admin_password_required")); return; }
      if (form.adminPassword !== form.adminPasswordConfirm) { setError(t("wizard.admin_password_mismatch")); return; }
    }
    if (step === 5) {
      if (!primaryContact.full_name.trim() || !primaryContact.email.trim()) {
        setError(t("wizard.contact_primary_required"));
        return;
      }
    }
    setError("");
    setStep((s) => Math.min(s + 1, TOTAL_STEPS));
  }

  async function launch() {
    setLoading(true);
    setError("");
    try {
      // Step 1: Create the tenant AND its TA admin user atomically — one DB
      // transaction server-side (CLAUDE.md §29: no rollback path is needed
      // because there is nothing left to roll back).
      const tenantData = await api.post<TenantCreateResponse>("/api/v1/tenants/", {
        name:               form.name.trim(),
        default_locale:     form.locale,
        organisation_type:  form.orgType || null,
        plan_tier:          form.planTier,
        billing_period:     form.billingPeriod,
        ...(form.industry.trim() ? { industry: form.industry.trim() } : {}),
        // SKU cap applies to every organisation_type, not just PRODUCER (CLAUDE.md §15).
        ...(form.skuLimit ? { sku_cap: parseInt(form.skuLimit, 10) } : {}),
        // Contract (the commercial agreement) is independent of the billing
        // period above (CLAUDE.md §15 decision B) — sent in the same create
        // call, no separate PATCH /contract step needed.
        ...(form.contractStart ? { contract_start: form.contractStart } : {}),
        ...(form.contractEnd   ? { contract_end:   form.contractEnd   } : {}),
        admin_name:     form.adminName.trim(),
        admin_email:    form.adminEmail.trim(),
        admin_password: form.adminPassword,
      });
      const tenantId = tenantData.id;

      // Step 2: Save contacts (best-effort — don't roll back tenant if this fails)
      if (primaryContact.full_name.trim() && primaryContact.email.trim()) {
        const contactRows = [
          {
            is_primary:     true,
            full_name:      primaryContact.full_name.trim(),
            position_title: primaryContact.position_title.trim() || null,
            email:          primaryContact.email.trim(),
            phone:          primaryContact.phone.trim() || null,
            mobile:         primaryContact.mobile.trim() || null,
          },
          ...additionalContacts
            .filter((c) => c.full_name.trim())
            .map((c) => ({
              is_primary:     false,
              full_name:      c.full_name.trim(),
              position_title: c.position_title.trim() || null,
              email:          c.email.trim() || null,
              phone:          c.phone.trim() || null,
              mobile:         c.mobile.trim() || null,
            })),
        ];

        // Include address fields if any are filled
        const hasAddress = Object.values(address).some((v) => v.trim());
        try {
          await api.post(`/api/v1/tenants/${tenantId}/contacts/bulk`, {
            contacts: contactRows,
            ...(hasAddress ? {
              address_line1:    address.line1.trim() || null,
              address_line2:    address.line2.trim() || null,
              city:             address.city.trim()  || null,
              state_province:   address.state.trim() || null,
              postal_code:      address.postal.trim() || null,
              country:          address.country.trim() || null,
            } : {}),
          });
        } catch { /* non-fatal — contacts can be added later via SA registry */ }
      }

      setResult({
        id:            tenantData.id,
        name:          tenantData.name,
        slug:          tenantData.slug ?? tenantData.id,
        org_type:      form.orgType as OrgType,
        feature_flags: FLAG_DEFAULTS[form.orgType as OrgType],
        adminEmail:    form.adminEmail.trim(),
      });
      setStep(7);
    } catch (err: unknown) {
      const code = (err as { code?: string } | undefined)?.code;
      if (code === "DUPLICATE_EMAIL") {
        setError(t("wizard.duplicate_email_error"));
      } else if (code === "SLUG_ALREADY_EXISTS") {
        setError(t("wizard.slug_exists_error"));
      } else {
        setError(err instanceof Error ? err.message : "Unexpected error");
      }
    } finally {
      setLoading(false);
    }
  }

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f2d1f]">
        {/* Spinner: animation properties are dynamic — style= required */}
        <div
          className="w-10 h-10 rounded-full border-[3px] border-[rgba(252,221,9,0.25)] border-t-[#FCDD09]"
          style={{ animation: "spin 0.8s linear infinite" }}
        />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  const inputClass = "w-full px-3 py-2.5 text-sm border border-gray-300 rounded-md outline-none bg-white focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]";

  /* ── Success screen ── */
  if (step === 7 && result) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center p-8">
        <div className="bg-white rounded-xl p-12 max-w-[480px] w-full text-center shadow-lg">
          <div className="w-18 h-18 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-6 text-4xl">
            ✓
          </div>
          <h2 className="text-2xl font-extrabold text-[#0f2d1f] m-0 mb-2">{t("wizard.success_title")}</h2>
          <p className="text-gray-500 text-sm m-0 mb-2">
            <strong className="text-[#1B4332]">{result.name}</strong> {t("wizard.success_desc")}
          </p>
          <p className="text-gray-500 text-sm m-0 mb-6">
            {t("wizard.admin_login_hint")}{" "}
            <code className="bg-gray-100 px-1.5 py-0.5 rounded text-[13px] text-[#1B4332] font-bold">
              {result.adminEmail}
            </code>
          </p>
          <div className="grid grid-cols-2 gap-2 mb-6">
            {Object.entries(result.feature_flags).map(([flag, enabled]) => (
              <FlagBadge key={flag} name={t(`wizard.flags.${flag}`) || flag} enabled={enabled} />
            ))}
          </div>
          <div className="flex flex-col gap-2.5">
            <Link
              href={`/${result.slug}/dashboard`}
              className="w-full py-3 bg-[#1B4332] rounded-md text-sm font-bold no-underline text-[#FCDD09] flex items-center justify-center hover:bg-[#0f2d1f] transition-colors"
            >
              {t("wizard.view_tenant_dash")} →
            </Link>
            <div className="flex gap-2.5">
              <button
                onClick={() => {
                  setStep(1); setResult(null);
                  setForm({ name: "", industry: "", skuLimit: "500", orgType: "", planTier: "GROWTH", billingPeriod: "ANNUAL", locale: "en",
                            adminName: "", adminEmail: "", adminPassword: "", adminPasswordConfirm: "",
                            contractStart: "", contractEnd: "" });
                  setAddress(blankAddress());
                  setPrimaryContact(blankContact());
                  setAdditionalContacts([]);
                }}
                className="flex-1 py-2.5 bg-gray-100 border-none rounded-md text-sm font-semibold cursor-pointer text-gray-700 hover:bg-gray-200 transition-colors"
              >
                {t("wizard.onboard_another")}
              </button>
              <Link
                href="/admin/dashboard"
                className="flex-1 py-2.5 bg-white border border-gray-200 rounded-md text-sm font-semibold no-underline text-gray-700 flex items-center justify-center hover:bg-gray-50 transition-colors"
              >
                {t("wizard.admin_dash")}
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const flags = form.orgType ? FLAG_DEFAULTS[form.orgType] : null;

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-[#0f2d1f] px-8 h-14 flex items-center justify-between shadow-[0_2px_12px_rgba(0,0,0,0.35)]">
        <Link href="/admin/dashboard" className="flex items-center gap-2.5 no-underline">
          <Logo />
          {/* i18n-ignore: brand name */}
          <span className="font-bold text-[15px] text-white">
            SMART {/* i18n-ignore: brand name */}
            <span className="text-[#FCDD09]">Inventory</span>
          </span>
        </Link>
        <span className="text-xs font-bold text-emerald-300">{t("wizard.title")}</span>
        <Link href="/admin/dashboard" className="text-xs text-gray-400 no-underline hover:text-gray-200 transition-colors">
          {t("wizard.back_to_admin")}
        </Link>
      </header>
      {/* Ethiopian flag stripe — multi-stop gradient, style= required */}
      <div
        className="h-1"
        style={{ background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)" }}
      />

      <div className="max-w-[740px] mx-auto mt-12 px-4 pb-12">
        <StepBar current={step} />

        <div className="bg-white rounded-xl shadow-md overflow-hidden">
          {/* Card header */}
          <div className="bg-[#1B4332] px-8 py-5">
            <p className="font-bold text-lg text-white m-0">
              {step === 1 && t("wizard.step1_title")}
              {step === 2 && t("wizard.step2_title")}
              {step === 3 && t("wizard.step3_title")}
              {step === 4 && t("wizard.step_admin_title")}
              {step === 5 && t("wizard.step_contacts_title")}
              {step === 6 && t("wizard.step4_title")}
            </p>
            <p className="text-xs text-emerald-300 mt-1 mb-0">
              {t("wizard.step_of")} {step} {t("wizard.of")} {TOTAL_STEPS}
            </p>
          </div>

          <div className="p-8">

            {/* ── Step 1: Company Info ── */}
            {step === 1 && (
              <div className="flex flex-col gap-5">
                <div>
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.org_name")} <span className="text-red-600">*</span>
                  </label>
                  <input
                    type="text" value={form.name} placeholder={t("wizard.org_name_placeholder")}
                    onChange={(e) => set("name", e.target.value)}
                    className={inputClass} autoFocus
                  />
                </div>
                <div>
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.industry")}{" "}
                    <span className="text-xs font-normal text-gray-400">({t("common.optional")})</span>
                  </label>
                  <input
                    type="text" value={form.industry} placeholder={t("wizard.industry_placeholder")}
                    onChange={(e) => set("industry", e.target.value)}
                    className={inputClass}
                  />
                </div>
                {/* Contract dates */}
                <div className="pt-1 border-t border-gray-100">
                  <p className="font-bold text-[13px] text-gray-700 mb-0.5">{t("wizard.contract_dates_heading")}</p>
                  <p className="text-[11px] text-gray-400 mb-2.5">{t("wizard.contract_dates_optional")}</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                        {t("wizard.contract_start")}
                      </label>
                      <input
                        type="date" value={form.contractStart}
                        onChange={(e) => set("contractStart", e.target.value)}
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                        {t("wizard.contract_end")}
                      </label>
                      <input
                        type="date" value={form.contractEnd}
                        onChange={(e) => set("contractEnd", e.target.value)}
                        className={inputClass}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Step 2: Org Type ── */}
            {step === 2 && (
              <div className="flex flex-col gap-3">
                {(["PRODUCER", "RETAILER", "HYBRID"] as OrgType[]).map((type) => {
                  const m        = ORG_META[type];
                  const selected = form.orgType === type;
                  return (
                    <button
                      key={type}
                      onClick={() => set("orgType", type)}
                      className="flex items-start gap-4 px-5 py-4 rounded-lg cursor-pointer text-left transition-all"
                      /* Per-org-type color — runtime data value, style= required */
                      style={{
                        border:     selected ? `2px solid ${m.color}` : "2px solid #E5E7EB",
                        background: selected ? `${m.color}10` : "#fff",
                      }}
                    >
                      <div
                        className="w-5 h-5 rounded-full flex-shrink-0 mt-0.5 transition-all"
                        style={{
                          border:     selected ? `6px solid ${m.color}` : "2px solid #D1D5DB",
                          background: selected ? "#fff" : "transparent",
                        }}
                      />
                      <div>
                        <p className="font-bold text-[15px] text-gray-900 m-0 mb-1">{m.label}</p>
                        <p className="text-[13px] text-gray-500 m-0">{m.desc}</p>
                        {selected && (
                          <div className="mt-2.5 grid grid-cols-2 gap-1.5">
                            {Object.entries(FLAG_DEFAULTS[type]).map(([flag, en]) => (
                              <FlagBadge key={flag} name={t(`wizard.flags.${flag}`) || flag} enabled={en} />
                            ))}
                          </div>
                        )}
                      </div>
                    </button>
                  );
                })}
                {/* SKU cap applies to every organisation_type, not just PRODUCER (CLAUDE.md §15) */}
                <div className="p-4 bg-green-50 rounded-lg border border-green-200">
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.sku_limit")}{" "}
                    <span className="text-xs font-normal text-gray-400">{t("wizard.sku_limit_hint")}</span>
                  </label>
                  <input
                    type="number" min={1} value={form.skuLimit}
                    onChange={(e) => set("skuLimit", e.target.value)}
                    className={`${inputClass} max-w-[180px]`}
                  />
                </div>

                {/* ── Plan Tier — limits read live from the package catalog, never hardcoded ── */}
                <div className="pt-2">
                  <p className="font-bold text-[13px] text-gray-700 mb-1">{t("wizard.plan_tier")}</p>
                  <p className="text-xs text-gray-400 mb-2.5">{t("wizard.plan_tier_hint")}</p>
                  <div className="grid grid-cols-3 gap-2">
                    {(["STARTER", "GROWTH", "ENTERPRISE"] as PlanTier[]).map((tier) => {
                      const selected = form.planTier === tier;
                      const entry = tierConfig?.find((e) => e.tier === tier);
                      const colors: Record<PlanTier, { ring: string; bg: string; badge: string }> = {
                        STARTER:    { ring: "#9CA3AF", bg: "#F9FAFB", badge: "bg-gray-100 text-gray-600" },
                        GROWTH:     { ring: "#3B82F6", bg: "#EFF6FF", badge: "bg-blue-100 text-blue-700" },
                        ENTERPRISE: { ring: "#D97706", bg: "#FFFBEB", badge: "bg-amber-100 text-amber-700" },
                      };
                      const c = colors[tier];
                      return (
                        <button
                          key={tier}
                          type="button"
                          onClick={() => set("planTier", tier)}
                          className="flex flex-col items-start px-3.5 py-3 rounded-lg text-left transition-all"
                          style={{
                            border:     selected ? `2px solid ${c.ring}` : "2px solid #E5E7EB",
                            background: selected ? c.bg : "#fff",
                          }}
                        >
                          <span className={`text-[11px] font-extrabold px-2 py-0.5 rounded mb-1.5 ${c.badge}`}>
                            {tier}
                          </span>
                          <span className="text-[12px] text-gray-500 leading-tight">
                            {entry
                              ? `${limitText(entry.max_warehouses)} ${t("tenant_admin.plan.max_warehouses")} · ${limitText(entry.max_users)} ${t("tenant_admin.plan.max_users")}`
                              : t("common.loading")}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* ── Billing Period ── */}
                <div className="pt-2">
                  <p className="font-bold text-[13px] text-gray-700 mb-1">{t("wizard.billing_period")}</p>
                  <div className="grid grid-cols-2 gap-2 max-w-xs">
                    {(["MONTHLY", "ANNUAL"] as BillingPeriod[]).map((period) => {
                      const selected = form.billingPeriod === period;
                      return (
                        <button
                          key={period}
                          type="button"
                          onClick={() => set("billingPeriod", period)}
                          className={`px-3.5 py-2.5 rounded-lg text-sm font-semibold transition-all ${
                            selected ? "border-2 border-[#1B4332] bg-green-50 text-[#1B4332]" : "border-2 border-gray-200 bg-white text-gray-600"
                          }`}
                        >
                          {t(`wizard.billing_period_${period.toLowerCase()}`)}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* ── Step 3: Locale ── */}
            {step === 3 && (
              <div className="flex flex-col gap-3">
                {(["en", "am", "or"] as Locale[]).map((loc) => {
                  const m        = LOCALE_META[loc];
                  const selected = form.locale === loc;
                  return (
                    <button
                      key={loc}
                      onClick={() => set("locale", loc)}
                      className={`flex items-center gap-4 px-5 py-4 rounded-lg cursor-pointer text-left transition-all border-2 ${
                        selected ? "border-[#1B4332] bg-green-50" : "border-gray-200 bg-white"
                      }`}
                    >
                      <div
                        className="w-5 h-5 rounded-full flex-shrink-0 transition-all"
                        style={{
                          border:     selected ? "6px solid #1B4332" : "2px solid #D1D5DB",
                          background: selected ? "#fff" : "transparent",
                        }}
                      />
                      <div>
                        <p className="font-bold text-[15px] text-gray-900 m-0 mb-0.5">{m.label}</p>
                        <p className="text-sm text-gray-500 m-0">{m.native}</p>
                      </div>
                      {loc === "or" && (
                        <span className="ml-auto text-[11px] font-bold bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full">
                          {t("wizard.needs_expert_review")}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}

            {/* ── Step 4: Admin User ── */}
            {step === 4 && (
              <div className="flex flex-col gap-5">
                <p className="text-sm text-gray-500 m-0 -mt-2">{t("wizard.admin_heading")}</p>
                <div>
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.admin_name_label")} <span className="text-red-600">*</span>
                  </label>
                  <input
                    type="text" value={form.adminName}
                    placeholder={t("wizard.admin_name_placeholder")}
                    onChange={(e) => set("adminName", e.target.value)}
                    className={inputClass} autoFocus
                  />
                </div>
                <div>
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.admin_email_label")} <span className="text-red-600">*</span>
                  </label>
                  <input
                    type="email" value={form.adminEmail}
                    placeholder={t("wizard.admin_email_placeholder")}
                    onChange={(e) => set("adminEmail", e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.admin_password_label")} <span className="text-red-600">*</span>
                  </label>
                  <input
                    type="password" value={form.adminPassword}
                    onChange={(e) => set("adminPassword", e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="block font-bold text-[13px] text-gray-700 mb-1.5">
                    {t("wizard.admin_confirm_password_label")} <span className="text-red-600">*</span>
                  </label>
                  <input
                    type="password" value={form.adminPasswordConfirm}
                    onChange={(e) => set("adminPasswordConfirm", e.target.value)}
                    className={inputClass}
                  />
                </div>
              </div>
            )}

            {/* ── Step 5: Tenant Contacts ── */}
            {step === 5 && (
              <div className="flex flex-col gap-7">

                {/* Address */}
                <div>
                  <p className="font-bold text-[13px] text-gray-700 mb-3 uppercase tracking-wider">
                    {t("wizard.contacts_address_heading")}
                    <span className="ml-2 text-[11px] font-normal normal-case tracking-normal text-gray-400">
                      ({t("common.optional")})
                    </span>
                  </p>
                  <div className="flex flex-col gap-3">
                    <input
                      type="text" value={address.line1}
                      placeholder={t("wizard.address_line1")}
                      onChange={(e) => setAddr("line1", e.target.value)}
                      className={inputClass}
                    />
                    <input
                      type="text" value={address.line2}
                      placeholder={`${t("wizard.address_line2")} (${t("common.optional")})`}
                      onChange={(e) => setAddr("line2", e.target.value)}
                      className={inputClass}
                    />
                    <div className="grid grid-cols-2 gap-3">
                      <input
                        type="text" value={address.city}
                        placeholder={t("wizard.address_city")}
                        onChange={(e) => setAddr("city", e.target.value)}
                        className={inputClass}
                      />
                      <input
                        type="text" value={address.state}
                        placeholder={t("wizard.address_state_province")}
                        onChange={(e) => setAddr("state", e.target.value)}
                        className={inputClass}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <input
                        type="text" value={address.postal}
                        placeholder={t("wizard.address_postal_code")}
                        onChange={(e) => setAddr("postal", e.target.value)}
                        className={inputClass}
                      />
                      <input
                        type="text" value={address.country}
                        placeholder={t("wizard.address_country")}
                        onChange={(e) => setAddr("country", e.target.value)}
                        className={inputClass}
                      />
                    </div>
                  </div>
                </div>

                {/* Primary contact */}
                <div>
                  <p className="font-bold text-[13px] text-gray-700 mb-3 uppercase tracking-wider">
                    {t("wizard.contacts_primary_heading")}
                    <span className="ml-2 text-[11px] font-normal normal-case tracking-normal text-red-500">*</span>
                  </p>
                  <div className="p-4 border border-[#1B4332] rounded-lg bg-green-50 flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                          {t("wizard.contact_full_name")} <span className="text-red-500">*</span>
                        </label>
                        <input
                          type="text" value={primaryContact.full_name}
                          onChange={(e) => setPrimary("full_name", e.target.value)}
                          className={inputClass}
                        />
                      </div>
                      <div>
                        <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                          {t("wizard.contact_position_title")}
                        </label>
                        <input
                          type="text" value={primaryContact.position_title}
                          onChange={(e) => setPrimary("position_title", e.target.value)}
                          className={inputClass}
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                          {t("wizard.contact_email")} <span className="text-red-500">*</span>
                        </label>
                        <input
                          type="email" value={primaryContact.email}
                          onChange={(e) => setPrimary("email", e.target.value)}
                          className={inputClass}
                        />
                      </div>
                      <div>
                        <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                          {t("wizard.contact_phone")}
                        </label>
                        <input
                          type="tel" value={primaryContact.phone}
                          onChange={(e) => setPrimary("phone", e.target.value)}
                          className={inputClass}
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                        {t("wizard.contact_mobile")}
                        <span className="ml-1 text-[11px] font-normal text-gray-400">({t("common.optional")})</span>
                      </label>
                      <input
                        type="tel" value={primaryContact.mobile}
                        onChange={(e) => setPrimary("mobile", e.target.value)}
                        className={`${inputClass} max-w-[260px]`}
                      />
                    </div>
                  </div>
                </div>

                {/* Additional contacts */}
                <div>
                  <p className="font-bold text-[13px] text-gray-700 mb-3 uppercase tracking-wider">
                    {t("wizard.contacts_additional_heading")}
                    <span className="ml-2 text-[11px] font-normal normal-case tracking-normal text-gray-400">
                      ({t("common.optional")})
                    </span>
                  </p>
                  <div className="flex flex-col gap-3">
                    {additionalContacts.map((c) => (
                      <div key={c.id} className="p-4 border border-gray-200 rounded-lg bg-gray-50 flex flex-col gap-3">
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                              {t("wizard.contact_full_name")}
                            </label>
                            <input
                              type="text" value={c.full_name}
                              onChange={(e) => setAdditional(c.id, "full_name", e.target.value)}
                              className={inputClass}
                            />
                          </div>
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                              {t("wizard.contact_position_title")}
                            </label>
                            <input
                              type="text" value={c.position_title}
                              onChange={(e) => setAdditional(c.id, "position_title", e.target.value)}
                              className={inputClass}
                            />
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                              {t("wizard.contact_email")}
                            </label>
                            <input
                              type="email" value={c.email}
                              onChange={(e) => setAdditional(c.id, "email", e.target.value)}
                              className={inputClass}
                            />
                          </div>
                          <div>
                            <label className="block text-[12px] font-semibold text-gray-600 mb-1">
                              {t("wizard.contact_phone")}
                            </label>
                            <input
                              type="tel" value={c.phone}
                              onChange={(e) => setAdditional(c.id, "phone", e.target.value)}
                              className={inputClass}
                            />
                          </div>
                        </div>
                        <div className="flex justify-end">
                          <button
                            type="button"
                            onClick={() => removeAdditionalContact(c.id)}
                            className="text-[12px] font-semibold text-red-500 hover:text-red-700 transition-colors"
                          >
                            {t("wizard.contacts_remove_btn")}
                          </button>
                        </div>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={addAdditionalContact}
                      className="self-start text-[13px] font-semibold text-[#1B4332] hover:text-[#0f2d1f] transition-colors"
                    >
                      {t("wizard.contacts_add_btn")}
                    </button>
                  </div>
                </div>

                <p className="text-[12px] text-gray-400 m-0 -mt-2">
                  {t("wizard.contacts_optional_note")}
                </p>
              </div>
            )}

            {/* ── Step 6: Review ── */}
            {step === 6 && form.orgType && (
              <div className="flex flex-col gap-5">
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: t("wizard.company_label"),    value: form.name },
                    { label: t("wizard.industry_label"),   value: form.industry || "—" },
                    { label: t("wizard.org_type_label"),   value: ORG_META[form.orgType].label },
                    { label: t("wizard.plan_tier"),         value: form.planTier },
                    { label: t("wizard.language_label"),   value: `${LOCALE_META[form.locale].label} (${form.locale})` },
                    { label: t("wizard.admin_email_label"), value: form.adminEmail },
                    ...(form.orgType === "PRODUCER" ? [{ label: t("wizard.sku_limit_label_short"), value: form.skuLimit }] : []),
                    ...(form.contractStart ? [{ label: t("wizard.contract_start"), value: form.contractStart }] : []),
                    ...(form.contractEnd   ? [{ label: t("wizard.contract_end"),   value: form.contractEnd   }] : []),
                  ].map(({ label, value }) => (
                    <div key={label} className="px-3.5 py-2.5 bg-gray-50 rounded-md border border-gray-200">
                      <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 m-0">{label}</p>
                      <p className="text-sm font-semibold text-gray-900 mt-1 mb-0">{value}</p>
                    </div>
                  ))}
                </div>

                {/* Primary contact summary */}
                {primaryContact.full_name.trim() && (
                  <div>
                    <p className="font-bold text-[13px] text-gray-700 m-0 mb-2">
                      {t("wizard.contacts_primary_heading")}
                    </p>
                    <div className="px-3.5 py-2.5 bg-green-50 rounded-md border border-green-200">
                      <p className="text-sm font-semibold text-gray-900 m-0">{primaryContact.full_name}</p>
                      {primaryContact.position_title && (
                        <p className="text-[12px] text-gray-500 m-0">{primaryContact.position_title}</p>
                      )}
                      <p className="text-[12px] text-gray-500 m-0">{primaryContact.email}</p>
                      {primaryContact.phone && (
                        <p className="text-[12px] text-gray-500 m-0">{primaryContact.phone}</p>
                      )}
                    </div>
                    {additionalContacts.filter((c) => c.full_name.trim()).length > 0 && (
                      <p className="text-[12px] text-gray-400 mt-1.5 m-0">
                        +{additionalContacts.filter((c) => c.full_name.trim()).length}{" "}
                        {t("wizard.contacts_additional_heading").toLowerCase()}
                      </p>
                    )}
                  </div>
                )}

                {flags && (
                  <div>
                    <p className="font-bold text-[13px] text-gray-700 m-0 mb-2">{t("wizard.feature_flags")}</p>
                    <div className="grid grid-cols-2 gap-2">
                      {Object.entries(flags).map(([flag, en]) => (
                        <FlagBadge key={flag} name={t(`wizard.flags.${flag}`) || flag} enabled={en} />
                      ))}
                    </div>
                  </div>
                )}

                <p className="text-xs text-gray-400 m-0">
                  {t("wizard.approval_rules_hint")}
                </p>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="mt-4 bg-red-50 border border-red-200 rounded-md px-3.5 py-2.5 text-[13px] text-red-600">
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-8 py-5 border-t border-gray-100 flex justify-between gap-3">
            <button
              onClick={() => { setError(""); setStep((s) => Math.max(s - 1, 1)); }}
              disabled={step === 1}
              className={`px-5 py-2.5 bg-gray-100 border border-gray-200 rounded-md text-sm font-semibold text-gray-700 transition-opacity ${
                step === 1 ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-gray-200"
              }`}
            >
              {t("wizard.back")}
            </button>

            {step < TOTAL_STEPS ? (
              <button
                onClick={nextStep}
                className="px-7 py-2.5 bg-[#1B4332] border-none rounded-md text-sm font-bold text-[#FCDD09] cursor-pointer hover:bg-[#0f2d1f] transition-colors"
              >
                {t("wizard.next")}
              </button>
            ) : (
              <button
                onClick={launch}
                disabled={loading}
                className={`px-7 py-2.5 border-none rounded-md text-sm font-bold text-white transition-colors ${
                  loading ? "bg-gray-400 cursor-not-allowed" : "bg-emerald-600 cursor-pointer hover:bg-emerald-700"
                }`}
              >
                {loading ? t("wizard.launching") : t("wizard.launch_btn")}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
