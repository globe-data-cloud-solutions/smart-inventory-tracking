"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSession } from "@/lib/demo-auth";

/* ── Types ───────────────────────────────────────────────────────────────── */
type OrgType   = "PRODUCER" | "RETAILER" | "HYBRID";
type Locale    = "en" | "am" | "or";

interface WizardState {
  name:     string;
  industry: string;
  skuLimit: string;
  orgType:  OrgType | "";
  locale:   Locale;
}

interface WizardResult {
  id: string; name: string; slug: string; org_type: OrgType;
  feature_flags: Record<string, boolean>;
}

/* ── Feature flag defaults (mirrors wizard_service.py) ───────────────────── */
const FLAG_DEFAULTS: Record<OrgType, Record<string, boolean>> = {
  PRODUCER: { LOGISTICS: false, AI_ANALYTICS: false, ADVANCED_BATCH_TRACKING: true,  FLEET_MANAGEMENT: false },
  RETAILER: { LOGISTICS: true,  AI_ANALYTICS: true,  ADVANCED_BATCH_TRACKING: false, FLEET_MANAGEMENT: true  },
  HYBRID:   { LOGISTICS: true,  AI_ANALYTICS: true,  ADVANCED_BATCH_TRACKING: true,  FLEET_MANAGEMENT: true  },
};

const APPROVAL_DEFAULTS: Record<OrgType, { low: number; medium: number }> = {
  PRODUCER: { low: 100,  medium: 500   },
  RETAILER: { low: 500,  medium: 5000  },
  HYBRID:   { low: 250,  medium: 2000  },
};

const ORG_META: Record<OrgType, { label: string; desc: string; color: string }> = {
  PRODUCER: { label: "Producer / Importer",      color: "#0891B2", desc: "Manufactures or imports goods. Batch/lot tracking, FEFO dispatch, production cycles." },
  RETAILER: { label: "Retailer / Distributor",   color: "#059669", desc: "Distributes or sells to consumers. Full logistics, multi-branch stock, unlimited SKUs." },
  HYBRID:   { label: "Hybrid (Both)",             color: "#7C3AED", desc: "Both producer and retailer. Full feature set enabled." },
};

const LOCALE_META: Record<Locale, { label: string; native: string }> = {
  en: { label: "English",                    native: "English" },
  am: { label: "Amharic",                    native: "አማርኛ" },
  or: { label: "Oromifa (Afaan Oromoo)",      native: "Afaan Oromoo" },
};

/* ── Constants ───────────────────────────────────────────────────────────── */
const DARK   = "#0f2d1f";
const FOREST = "#1B4332";
const GOLD   = "#FCDD09";
const TOTAL_STEPS = 4;

/* ── Logo ────────────────────────────────────────────────────────────────── */
function Logo() {
  return (
    <svg width={32} height={32} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <rect width="40" height="40" rx="7" fill={GOLD} />
      <polygon points="20,4 36,12 36,24 20,32 4,24 4,12" fill={DARK} />
      <polygon points="20,10 30,16 30,23 20,29 10,23 10,16" fill={GOLD} />
      <polygon points="20,16 25,19 25,23 20,26 15,23 15,19" fill={DARK} />
    </svg>
  );
}

/* ── Step indicator ──────────────────────────────────────────────────────── */
function StepBar({ current }: { current: number }) {
  const labels = ["Company Info", "Org Type", "Language", "Review"];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 0, marginBottom: "2rem" }}>
      {labels.map((label, idx) => {
        const n    = idx + 1;
        const done = n < current;
        const active = n === current;
        return (
          <div key={label} style={{ display: "flex", alignItems: "center", flex: idx < labels.length - 1 ? 1 : "none" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              <div style={{
                width: 32, height: 32, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                fontWeight: 800, fontSize: 13,
                background: done ? FOREST : active ? GOLD : "#E5E7EB",
                color: done ? "#fff" : active ? DARK : "#9CA3AF",
                border: active ? `2px solid ${FOREST}` : "2px solid transparent",
              }}>
                {done ? "✓" : n}
              </div>
              <span style={{ fontSize: 11, fontWeight: active ? 700 : 500, color: active ? FOREST : "#9CA3AF", whiteSpace: "nowrap" }}>
                {label}
              </span>
            </div>
            {idx < labels.length - 1 && (
              <div style={{ flex: 1, height: 2, background: done ? FOREST : "#E5E7EB", margin: "0 8px", marginBottom: 20 }} />
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
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "8px 12px", border: "1px solid #E5E7EB", borderRadius: 6,
      background: enabled ? "#F0FDF4" : "#F9FAFB",
    }}>
      <span style={{ fontSize: 13, color: "#374151" }}>{name}</span>
      <span style={{
        fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 99,
        background: enabled ? "#DCFCE7" : "#F3F4F6",
        color: enabled ? "#166534" : "#9CA3AF",
      }}>
        {enabled ? "Enabled" : "Disabled"}
      </span>
    </div>
  );
}

const FLAG_LABELS: Record<string, string> = {
  LOGISTICS: "Logistics Module",
  AI_ANALYTICS: "AI Analytics",
  ADVANCED_BATCH_TRACKING: "Advanced Batch Tracking",
  FLEET_MANAGEMENT: "Fleet Management",
};

/* ── Main wizard ─────────────────────────────────────────────────────────── */
export default function OnboardPage() {
  const router = useRouter();

  const [ready, setReady]   = useState(false);
  const [step, setStep]     = useState(1);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WizardResult | null>(null);
  const [error, setError]   = useState("");

  const [form, setForm] = useState<WizardState>({
    name: "", industry: "", skuLimit: "500", orgType: "", locale: "en",
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
    if (step === 1) {
      if (!form.name.trim()) { setError("Company name is required."); return; }
    }
    if (step === 2) {
      if (!form.orgType) { setError("Please select an organisation type."); return; }
    }
    setError("");
    setStep((s) => Math.min(s + 1, TOTAL_STEPS));
  }

  async function launch() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/v1/tenants/wizard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name:           form.name.trim(),
          industry:       form.industry.trim(),
          org_type:       form.orgType,
          default_locale: form.locale,
          sku_limit:      form.orgType === "PRODUCER" ? parseInt(form.skuLimit, 10) : null,
        }),
      });
      const json = (await res.json()) as { success: boolean; data?: WizardResult; error?: { message: string } };
      if (!json.success || !json.data) throw new Error(json.error?.message ?? "Failed to onboard tenant");
      setResult(json.data);
      setStep(5); // success state
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      setLoading(false);
    }
  }

  if (!ready) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: DARK }}>
        <div style={{ width: 40, height: 40, borderRadius: "50%", border: "3px solid rgba(252,221,9,0.25)", borderTopColor: GOLD, animation: "spin 0.8s linear infinite" }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  const INPUT: React.CSSProperties = {
    width: "100%", padding: "10px 12px", fontSize: 14, boxSizing: "border-box",
    border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", background: "#fff",
  };

  /* ── Success screen ── */
  if (step === 5 && result) {
    return (
      <div style={{ minHeight: "100vh", background: "#F3F4F6", display: "flex", alignItems: "center", justifyContent: "center", padding: "2rem" }}>
        <div style={{ background: "#fff", borderRadius: 12, padding: "3rem", maxWidth: 480, width: "100%", textAlign: "center", boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}>
          <div style={{ width: 72, height: 72, borderRadius: "50%", background: "#DCFCE7", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 1.5rem", fontSize: 36 }}>
            ✓
          </div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 800, color: DARK, margin: "0 0 0.5rem" }}>Tenant Onboarded!</h2>
          <p style={{ color: "#6B7280", fontSize: 14, margin: "0 0 1.5rem" }}>
            <strong style={{ color: FOREST }}>{result.name}</strong> is ready.<br />
            Slug: <code style={{ background: "#F3F4F6", padding: "1px 6px", borderRadius: 3, fontSize: 13 }}>/{result.slug}</code>
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: "1.5rem" }}>
            {Object.entries(result.feature_flags).map(([flag, enabled]) => (
              <FlagBadge key={flag} name={FLAG_LABELS[flag] ?? flag} enabled={enabled} />
            ))}
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button
              onClick={() => { setStep(1); setResult(null); setForm({ name: "", industry: "", skuLimit: "500", orgType: "", locale: "en" }); }}
              style={{ flex: 1, padding: "10px", background: "#F3F4F6", border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: "pointer", color: "#374151" }}
            >
              Onboard Another
            </button>
            <Link href="/admin/dashboard" style={{ flex: 1, padding: "10px", background: FOREST, borderRadius: 6, fontSize: 14, fontWeight: 700, textDecoration: "none", color: GOLD, display: "flex", alignItems: "center", justifyContent: "center" }}>
              Admin Dashboard →
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const flags = form.orgType ? FLAG_DEFAULTS[form.orgType] : null;
  const approvals = form.orgType ? APPROVAL_DEFAULTS[form.orgType] : null;

  return (
    <div style={{ minHeight: "100vh", background: "#F3F4F6" }}>
      {/* Header */}
      <header style={{ background: DARK, padding: "0 2rem", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between", boxShadow: "0 2px 12px rgba(0,0,0,0.35)" }}>
        <Link href="/admin/dashboard" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
          <Logo />
          <span style={{ fontWeight: 700, fontSize: 15, color: "#fff" }}>SMART <span style={{ color: GOLD }}>Inventory</span></span>
        </Link>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#6ee7b7" }}>Tenant Onboarding Wizard</span>
        <Link href="/admin/dashboard" style={{ fontSize: 12, color: "#9CA3AF", textDecoration: "none" }}>← Back to admin</Link>
      </header>
      <div style={{ height: 4, background: `linear-gradient(to right,#078930 0% 33.33%,${GOLD} 33.33% 66.66%,#DA121A 66.66% 100%)` }} />

      <div style={{ maxWidth: 680, margin: "3rem auto", padding: "0 1rem" }}>
        {/* Progress */}
        <StepBar current={step} />

        <div style={{ background: "#fff", borderRadius: 12, boxShadow: "0 2px 16px rgba(0,0,0,0.06)", overflow: "hidden" }}>
          {/* Card header */}
          <div style={{ background: FOREST, padding: "1.25rem 2rem" }}>
            <p style={{ fontWeight: 700, fontSize: 18, color: "#fff", margin: 0 }}>
              {step === 1 && "Organisation Info"}
              {step === 2 && "Organisation Type"}
              {step === 3 && "Default Language"}
              {step === 4 && "Review & Launch"}
            </p>
            <p style={{ fontSize: 12, color: "#6ee7b7", margin: "4px 0 0" }}>Step {step} of {TOTAL_STEPS}</p>
          </div>

          <div style={{ padding: "2rem" }}>

            {/* ── Step 1: Company Info ── */}
            {step === 1 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <div>
                  <label style={{ display: "block", fontWeight: 700, fontSize: 13, color: "#374151", marginBottom: 6 }}>
                    Company Name <span style={{ color: "#DC2626" }}>*</span>
                  </label>
                  <input
                    type="text" value={form.name} placeholder="e.g. Addis Beverages PLC"
                    onChange={(e) => set("name", e.target.value)}
                    style={INPUT} autoFocus
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontWeight: 700, fontSize: 13, color: "#374151", marginBottom: 6 }}>
                    Industry <span style={{ fontSize: 12, fontWeight: 400, color: "#9CA3AF" }}>(optional)</span>
                  </label>
                  <input
                    type="text" value={form.industry} placeholder="e.g. Bottled Water, Cement, FMCG"
                    onChange={(e) => set("industry", e.target.value)}
                    style={INPUT}
                  />
                </div>
              </div>
            )}

            {/* ── Step 2: Org Type ── */}
            {step === 2 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {(["PRODUCER", "RETAILER", "HYBRID"] as OrgType[]).map((type) => {
                  const m       = ORG_META[type];
                  const selected = form.orgType === type;
                  return (
                    <button
                      key={type}
                      onClick={() => set("orgType", type)}
                      style={{
                        display: "flex", alignItems: "flex-start", gap: 16,
                        padding: "1rem 1.25rem", borderRadius: 8, cursor: "pointer",
                        border: selected ? `2px solid ${m.color}` : "2px solid #E5E7EB",
                        background: selected ? `${m.color}10` : "#fff",
                        textAlign: "left", transition: "all 0.15s",
                      }}
                    >
                      <div style={{
                        width: 20, height: 20, borderRadius: "50%", flexShrink: 0, marginTop: 2,
                        border: selected ? `6px solid ${m.color}` : "2px solid #D1D5DB",
                        background: selected ? "#fff" : "transparent",
                        transition: "all 0.15s",
                      }} />
                      <div>
                        <p style={{ fontWeight: 700, fontSize: 15, color: "#111827", margin: "0 0 4px" }}>{m.label}</p>
                        <p style={{ fontSize: 13, color: "#6B7280", margin: 0 }}>{m.desc}</p>
                        {selected && (
                          <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                            {Object.entries(FLAG_DEFAULTS[type]).map(([flag, en]) => (
                              <FlagBadge key={flag} name={FLAG_LABELS[flag] ?? flag} enabled={en} />
                            ))}
                          </div>
                        )}
                      </div>
                    </button>
                  );
                })}
                {form.orgType === "PRODUCER" && (
                  <div style={{ padding: "1rem", background: "#F0FDF4", borderRadius: 8, border: "1px solid #BBF7D0" }}>
                    <label style={{ display: "block", fontWeight: 700, fontSize: 13, color: "#374151", marginBottom: 6 }}>
                      SKU Limit <span style={{ fontSize: 12, fontWeight: 400, color: "#9CA3AF" }}>Producers only — set by plan</span>
                    </label>
                    <input
                      type="number" min={1} value={form.skuLimit}
                      onChange={(e) => set("skuLimit", e.target.value)}
                      style={{ ...INPUT, maxWidth: 180 }}
                    />
                  </div>
                )}
              </div>
            )}

            {/* ── Step 3: Locale ── */}
            {step === 3 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {(["en", "am", "or"] as Locale[]).map((loc) => {
                  const m       = LOCALE_META[loc];
                  const selected = form.locale === loc;
                  return (
                    <button
                      key={loc}
                      onClick={() => set("locale", loc)}
                      style={{
                        display: "flex", alignItems: "center", gap: 16,
                        padding: "1rem 1.25rem", borderRadius: 8, cursor: "pointer",
                        border: selected ? `2px solid ${FOREST}` : "2px solid #E5E7EB",
                        background: selected ? "#F0FDF4" : "#fff",
                        textAlign: "left", transition: "all 0.15s",
                      }}
                    >
                      <div style={{
                        width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
                        border: selected ? `6px solid ${FOREST}` : "2px solid #D1D5DB",
                        background: selected ? "#fff" : "transparent",
                        transition: "all 0.15s",
                      }} />
                      <div>
                        <p style={{ fontWeight: 700, fontSize: 15, color: "#111827", margin: "0 0 2px" }}>{m.label}</p>
                        <p style={{ fontSize: 14, color: "#6B7280", margin: 0 }}>{m.native}</p>
                      </div>
                      {loc === "or" && (
                        <span style={{
                          marginLeft: "auto", fontSize: 11, fontWeight: 700,
                          background: "#FEF3C7", color: "#92400E",
                          padding: "2px 8px", borderRadius: 99,
                        }}>
                          Needs expert review
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}

            {/* ── Step 4: Review ── */}
            {step === 4 && form.orgType && (
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                {/* Summary */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  {[
                    { label: "Company",  value: form.name },
                    { label: "Industry", value: form.industry || "—" },
                    { label: "Org Type", value: ORG_META[form.orgType].label },
                    { label: "Language", value: `${LOCALE_META[form.locale].label} (${form.locale})` },
                    ...(form.orgType === "PRODUCER" ? [{ label: "SKU Limit", value: form.skuLimit }] : []),
                  ].map(({ label, value }) => (
                    <div key={label} style={{ padding: "10px 14px", background: "#F9FAFB", borderRadius: 6, border: "1px solid #E5E7EB" }}>
                      <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#9CA3AF", margin: 0 }}>{label}</p>
                      <p style={{ fontSize: 14, fontWeight: 600, color: "#111827", margin: "4px 0 0" }}>{value}</p>
                    </div>
                  ))}
                </div>

                {/* Feature flags */}
                {flags && (
                  <div>
                    <p style={{ fontWeight: 700, fontSize: 13, color: "#374151", margin: "0 0 8px" }}>Feature Flags</p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {Object.entries(flags).map(([flag, en]) => (
                        <FlagBadge key={flag} name={FLAG_LABELS[flag] ?? flag} enabled={en} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Approval thresholds */}
                {approvals && (
                  <div style={{ padding: "1rem", background: "#F9FAFB", borderRadius: 8, border: "1px solid #E5E7EB" }}>
                    <p style={{ fontWeight: 700, fontSize: 13, color: "#374151", margin: "0 0 8px" }}>Approval Thresholds — inventory:adjust</p>
                    <div style={{ display: "flex", gap: 16 }}>
                      {[
                        { level: "Auto-approve below", value: approvals.low,    color: "#059669" },
                        { level: "WM → RM above",       value: approvals.medium, color: "#D97706" },
                      ].map((t) => (
                        <div key={t.level} style={{ flex: 1, padding: "10px", background: "#fff", borderRadius: 6, border: "1px solid #E5E7EB", textAlign: "center" }}>
                          <p style={{ fontSize: 18, fontWeight: 800, color: t.color, margin: 0 }}>{t.value.toLocaleString()}</p>
                          <p style={{ fontSize: 11, color: "#9CA3AF", margin: "4px 0 0" }}>{t.level}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Error */}
            {error && (
              <div style={{ marginTop: 16, background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 6, padding: "10px 14px", fontSize: 13, color: "#DC2626" }}>
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div style={{ padding: "1.25rem 2rem", borderTop: "1px solid #F3F4F6", display: "flex", justifyContent: "space-between", gap: 12 }}>
            <button
              onClick={() => { setError(""); setStep((s) => Math.max(s - 1, 1)); }}
              disabled={step === 1}
              style={{
                padding: "10px 20px", background: "#F3F4F6", border: "1px solid #E5E7EB",
                borderRadius: 6, fontSize: 14, fontWeight: 600, color: "#374151",
                cursor: step === 1 ? "not-allowed" : "pointer", opacity: step === 1 ? 0.5 : 1,
              }}
            >
              ← Back
            </button>

            {step < TOTAL_STEPS ? (
              <button
                onClick={nextStep}
                style={{
                  padding: "10px 28px", background: FOREST, border: "none",
                  borderRadius: 6, fontSize: 14, fontWeight: 700, color: GOLD, cursor: "pointer",
                }}
              >
                Next →
              </button>
            ) : (
              <button
                onClick={launch}
                disabled={loading}
                style={{
                  padding: "10px 28px", background: loading ? "#9CA3AF" : "#059669", border: "none",
                  borderRadius: 6, fontSize: 14, fontWeight: 700, color: "#fff",
                  cursor: loading ? "not-allowed" : "pointer",
                }}
              >
                {loading ? "Launching…" : "Launch Tenant →"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
