"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSession } from "@/lib/demo-auth";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

/* ── Types ───────────────────────────────────────────────────────────────── */
type OrgType   = "PRODUCER" | "RETAILER" | "HYBRID";
type Locale    = "en" | "am" | "or";

interface WizardState {
  name:                 string;
  industry:             string;
  skuLimit:             string;
  orgType:              OrgType | "";
  locale:               Locale;
  adminName:            string;
  adminEmail:           string;
  adminPassword:        string;
  adminPasswordConfirm: string;
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

const TOTAL_STEPS = 5;

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
              <span className={`text-[11px] whitespace-nowrap ${active ? "font-bold text-[#1B4332]" : "font-medium text-gray-400"}`}>
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
    name: "", industry: "", skuLimit: "500", orgType: "", locale: "en",
    adminName: "", adminEmail: "", adminPassword: "", adminPasswordConfirm: "",
  });

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

  function nextStep() {
    if (step === 1 && !form.name.trim()) { setError(t("wizard.company_required")); return; }
    if (step === 2 && !form.orgType)     { setError(t("wizard.select_org_type"));  return; }
    if (step === 4) {
      if (!form.adminName.trim())                        { setError(t("wizard.admin_name_required"));      return; }
      if (!form.adminEmail.trim())                       { setError(t("wizard.admin_email_required"));     return; }
      if (form.adminPassword.length < 8)                 { setError(t("wizard.admin_password_required")); return; }
      if (form.adminPassword !== form.adminPasswordConfirm) { setError(t("wizard.admin_password_mismatch")); return; }
    }
    setError("");
    setStep((s) => Math.min(s + 1, TOTAL_STEPS));
  }

  async function launch() {
    setLoading(true);
    setError("");
    let tenantId: string | null = null;
    try {
      // Step 1: Create the tenant
      const tenantData = await api.post<TenantCreateResponse>("/api/v1/tenants/", {
        name:               form.name.trim(),
        default_locale:     form.locale,
        organisation_type:  form.orgType || null,
      });
      tenantId = tenantData.id;

      // Step 2: Create the TA admin user
      try {
        await api.post(`/api/v1/tenants/${tenantId}/users`, {
          name:     form.adminName.trim(),
          email:    form.adminEmail.trim(),
          role:     "TA",
          password: form.adminPassword,
        });
      } catch (userErr: unknown) {
        // Rollback: remove the orphaned tenant
        try { await api.delete(`/api/v1/tenants/${tenantId}`); } catch { /* ignore rollback errors */ }
        throw userErr;
      }

      setResult({
        id:            tenantData.id,
        name:          tenantData.name,
        slug:          tenantData.slug ?? tenantData.id,
        org_type:      form.orgType as OrgType,
        feature_flags: FLAG_DEFAULTS[form.orgType as OrgType],
        adminEmail:    form.adminEmail.trim(),
      });
      setStep(6);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unexpected error");
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
  if (step === 6 && result) {
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
                  setForm({ name: "", industry: "", skuLimit: "500", orgType: "", locale: "en",
                            adminName: "", adminEmail: "", adminPassword: "", adminPasswordConfirm: "" });
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
          <span className="font-bold text-[15px] text-white">
            SMART <span className="text-[#FCDD09]">Inventory</span>
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

      <div className="max-w-[680px] mx-auto mt-12 px-4 pb-12">
        <StepBar current={step} />

        <div className="bg-white rounded-xl shadow-md overflow-hidden">
          {/* Card header */}
          <div className="bg-[#1B4332] px-8 py-5">
            <p className="font-bold text-lg text-white m-0">
              {step === 1 && t("wizard.step1_title")}
              {step === 2 && t("wizard.step2_title")}
              {step === 3 && t("wizard.step3_title")}
              {step === 4 && t("wizard.step_admin_title")}
              {step === 5 && t("wizard.step4_title")}
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
                {form.orgType === "PRODUCER" && (
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
                )}
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

            {/* ── Step 5: Review ── */}
            {step === 5 && form.orgType && (
              <div className="flex flex-col gap-5">
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: t("wizard.company_label"),    value: form.name },
                    { label: t("wizard.industry_label"),   value: form.industry || "—" },
                    { label: t("wizard.org_type_label"),   value: ORG_META[form.orgType].label },
                    { label: t("wizard.language_label"),   value: `${LOCALE_META[form.locale].label} (${form.locale})` },
                    { label: t("wizard.admin_email_label"), value: form.adminEmail },
                    ...(form.orgType === "PRODUCER" ? [{ label: t("wizard.sku_limit_label_short"), value: form.skuLimit }] : []),
                  ].map(({ label, value }) => (
                    <div key={label} className="px-3.5 py-2.5 bg-gray-50 rounded-md border border-gray-200">
                      <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 m-0">{label}</p>
                      <p className="text-sm font-semibold text-gray-900 mt-1 mb-0">{value}</p>
                    </div>
                  ))}
                </div>

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
