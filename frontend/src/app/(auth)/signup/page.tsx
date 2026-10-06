"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatCurrency } from "@/lib/utils";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";

type BillingPeriod = "MONTHLY" | "ANNUAL";
type OrgType = "PRODUCER" | "RETAILER" | "HYBRID";

interface PriceOut {
  subtotal: string;
  vat_rate: string;
  vat_amount: string;
  total: string;
  currency: string;
}

interface PackageOut {
  tier: string;
  display_name: string | null;
  max_warehouses: number | null;
  max_users: number | null;
  sku_cap: number | null;
  feature_flags: Record<string, boolean>;
  prices: Partial<Record<BillingPeriod, PriceOut>>;
}

interface PackagesListOut {
  packages: PackageOut[];
  terms_version: string;
}

interface SignupOut {
  tenant_id: string;
  slug: string;
  company_name: string;
  admin_email: string;
  tier: string;
  billing_period: BillingPeriod;
}

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

const ORG_TYPES: OrgType[] = ["PRODUCER", "RETAILER", "HYBRID"];
const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$/;

const detailsSchema = z
  .object({
    company_name: z.string().trim().min(2, "signup.validation.company_name_required").max(255),
    slug: z.string().trim().optional(),
    organisation_type: z.enum(["PRODUCER", "RETAILER", "HYBRID"]),
    industry: z.string().trim().optional(),
    default_locale: z.enum(["en", "am", "or"]),
    admin_full_name: z.string().trim().min(1, "signup.validation.admin_name_required"),
    admin_email: z.string().trim().email("signup.validation.email_invalid"),
    admin_password: z.string().min(8, "signup.validation.password_min"),
    admin_password_confirm: z.string().min(8, "signup.validation.password_min"),
    phone: z.string().trim().optional(),
    accept_terms: z.boolean(),
  })
  .superRefine((data, ctx) => {
    if (data.admin_password !== data.admin_password_confirm) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["admin_password_confirm"],
        message: "signup.validation.password_mismatch",
      });
    }
    const slug = data.slug?.trim().toLowerCase();
    if (slug && !SLUG_RE.test(slug)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["slug"], message: "signup.validation.slug_invalid" });
    }
    if (!data.accept_terms) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["accept_terms"], message: "signup.validation.terms_required" });
    }
  });

type DetailsForm = z.infer<typeof detailsSchema>;

const STEP2_FIELDS: (keyof DetailsForm)[] = [
  "company_name", "slug", "organisation_type", "industry", "default_locale",
  "admin_full_name", "admin_email", "admin_password", "admin_password_confirm", "phone",
  "accept_terms",
];

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-red-600">{t(message)}</p>;
}

export default function SignupPage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [period, setPeriod] = useState<BillingPeriod>("MONTHLY");
  const [tier, setTier] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SignupOut | null>(null);

  const {
    data: catalog,
    isLoading: loadingCatalog,
    isError: catalogError,
    refetch: refetchCatalog,
  } = useQuery<PackagesListOut>({
    queryKey: ["public-packages"],
    queryFn: () => api.get<PackagesListOut>("/api/v1/tenants/public/packages"),
    enabled: IS_GATEWAY_MODE,
    staleTime: 0,
  });

  const form = useForm<DetailsForm>({
    resolver: zodResolver(detailsSchema),
    defaultValues: {
      company_name: "",
      slug: "",
      organisation_type: "PRODUCER",
      industry: "",
      default_locale: "en",
      admin_full_name: "",
      admin_email: "",
      admin_password: "",
      admin_password_confirm: "",
      phone: "",
      accept_terms: false,
    },
  });

  if (!IS_GATEWAY_MODE) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-8">
        <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md text-center">
          <p className="text-gray-700">{t("signup.unavailable")}</p>
          <Link href="/login" className="mt-4 inline-block text-sm font-semibold text-brand-600 hover:text-brand-700">
            {t("verify_email.back_to_login")}
          </Link>
        </div>
      </div>
    );
  }

  const selectedPackage = catalog?.packages.find((p) => p.tier === tier) ?? null;
  const selectedPrice = selectedPackage?.prices[period] ?? null;

  async function goToStep2() {
    if (!tier || !selectedPrice) return;
    setStep(2);
  }

  async function goToStep3() {
    const valid = await form.trigger(STEP2_FIELDS);
    if (!valid) return;
    setStep(3);
  }

  async function onSubmit() {
    if (!tier || !catalog) return;
    const values = form.getValues();
    setSubmitting(true);
    setSubmitError(null);
    try {
      const data = await api.post<SignupOut>("/api/v1/tenants/public/signup", {
        company_name: values.company_name,
        slug: values.slug ? values.slug.trim().toLowerCase() : undefined,
        organisation_type: values.organisation_type,
        industry: values.industry || undefined,
        default_locale: values.default_locale,
        tier,
        billing_period: period,
        admin_full_name: values.admin_full_name,
        admin_email: values.admin_email,
        admin_password: values.admin_password,
        phone: values.phone || undefined,
        accept_terms: true,
        terms_version: catalog.terms_version,
      });
      setResult(data);
    } catch (err) {
      const e = err as Error & { status?: number; code?: string };
      if (e.code === "TERMS_VERSION_MISMATCH") {
        await refetchCatalog();
        form.setValue("accept_terms", false);
        setStep(2);
      }
      const key = e.code ? `signup.error.${e.code}` : "";
      const translated = key ? t(key) : "";
      setSubmitError(translated && translated !== key ? translated : e.message || t("signup.error.NETWORK"));
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-8">
        <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md w-full text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">{t("signup.success_title")}</h1>
          <p className="text-gray-600 mb-1">{t("signup.sign_in_with").replace("{email}", result.admin_email)}</p>
          <p className="text-sm text-gray-500 mb-6">{t("signup.verification_note")}</p>
          <button
            type="button"
            onClick={() => router.push(`/login?email=${encodeURIComponent(result.admin_email)}`)}
            className="w-full rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
          >
            {t("signup.go_to_sign_in_btn")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-4 md:p-8">
      <div className="bg-white rounded-2xl shadow-2xl p-6 md:p-8 max-w-3xl w-full">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{t("signup.title")}</h1>
            <p className="text-gray-500 text-sm mt-1">{t("signup.subtitle")}</p>
          </div>
          <AuthLangSwitcher />
        </div>

        <p className="text-xs font-semibold text-gray-400 mb-6">{t("signup.step_of").replace("{n}", String(step))}</p>

        {/* ── Step 1: package selection ── */}
        {step === 1 && (
          <div>
            <h2 className="text-lg font-semibold text-gray-800 mb-4">{t("signup.step1_title")}</h2>

            <div className="flex gap-0.5 bg-gray-100 rounded p-0.5 w-fit mb-6">
              {(["MONTHLY", "ANNUAL"] as BillingPeriod[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPeriod(p)}
                  className={`text-sm font-semibold px-4 py-1.5 rounded transition-colors ${
                    period === p ? "bg-brand-600 text-white" : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  {p === "MONTHLY" ? t("signup.monthly") : t("signup.annual")}
                </button>
              ))}
            </div>

            {loadingCatalog && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
            {catalogError && <p className="text-red-500 text-sm">{t("common.error")}</p>}

            {catalog && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {catalog.packages.map((pkg) => {
                  const price = pkg.prices[period];
                  const monthly = pkg.prices.MONTHLY;
                  const annual = pkg.prices.ANNUAL;
                  const savings =
                    period === "ANNUAL" && monthly && annual && Number(monthly.total) * 12 > Number(annual.total)
                      ? Number(monthly.total) * 12 - Number(annual.total)
                      : null;
                  const isSelected = tier === pkg.tier;
                  return (
                    <div
                      key={pkg.tier}
                      data-testid={`package-card-${pkg.tier}`}
                      className={`rounded-lg border-2 p-4 flex flex-col ${
                        isSelected ? "border-brand-600 bg-brand-50" : "border-gray-200"
                      }`}
                    >
                      <h3 className="font-bold text-gray-900">{pkg.display_name ?? pkg.tier}</h3>
                      {price ? (
                        <p className="text-2xl font-bold text-gray-900 mt-2">
                          {formatCurrency(price.total, price.currency)}
                          <span className="text-xs font-normal text-gray-400 ml-1">
                            {period === "MONTHLY" ? t("signup.per_month") : t("signup.per_year")}
                          </span>
                        </p>
                      ) : (
                        <p className="text-sm text-gray-400 mt-2">{t("common.unknown")}</p>
                      )}
                      {savings !== null && (
                        <p className="text-xs text-emerald-600 font-semibold mt-1">
                          {t("signup.annual_savings").replace("{amount}", formatCurrency(savings, annual?.currency ?? "ETB"))}
                        </p>
                      )}
                      <ul className="text-xs text-gray-500 mt-3 space-y-1 flex-1">
                        <li>{t("tenant_admin.plan.max_warehouses")}: {pkg.max_warehouses ?? t("tenant_admin.plan.unlimited")}</li>
                        <li>{t("tenant_admin.plan.max_users")}: {pkg.max_users ?? t("tenant_admin.plan.unlimited")}</li>
                        <li>{t("tenant_admin.plan.sku_cap")}: {pkg.sku_cap ?? t("tenant_admin.plan.unlimited")}</li>
                        {FEATURE_FLAG_CODES.filter((c) => pkg.feature_flags[c]).map((c) => (
                          <li key={c}>✓ {t(`tenant_admin.features.flag.${c}`)}</li>
                        ))}
                      </ul>
                      <button
                        type="button"
                        disabled={!price}
                        onClick={() => setTier(pkg.tier)}
                        className={`mt-4 w-full rounded-lg py-2 text-sm font-semibold transition-colors disabled:opacity-40 ${
                          isSelected ? "bg-brand-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                        }`}
                      >
                        {isSelected ? t("signup.selected_package_btn") : t("signup.select_package_btn")}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="flex justify-between items-center mt-6">
              <Link href="/login" className="text-sm font-semibold text-gray-500 hover:text-gray-700">
                {t("signup.back_to_login")}
              </Link>
              <button
                type="button"
                disabled={!tier || !selectedPrice}
                onClick={() => void goToStep2()}
                className="rounded-lg bg-brand-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-40 transition-colors"
              >
                {t("signup.continue_btn")}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: details form ── */}
        {step === 2 && (
          <form onSubmit={(e) => { e.preventDefault(); void goToStep3(); }} className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-800 mb-2">{t("signup.step2_title")}</h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.company_name_label")}</label>
                <input
                  {...form.register("company_name")}
                  placeholder={t("signup.company_name_placeholder")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
                <FieldError message={form.formState.errors.company_name?.message} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("wizard.org_type_label")}</label>
                <select
                  {...form.register("organisation_type")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                >
                  {ORG_TYPES.map((ot) => (
                    <option key={ot} value={ot}>{t(`wizard.org_types.${ot}`)}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.industry_label")}</label>
                <input
                  {...form.register("industry")}
                  placeholder={t("signup.industry_placeholder")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.language_label")}</label>
                <select
                  {...form.register("default_locale")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                >
                  <option value="en">{t("lang.en")}</option>
                  <option value="am">{t("lang.am")}</option>
                  <option value="or">{t("lang.or")}</option>
                </select>
              </div>

              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.slug_label")}</label>
                <div className="flex items-center gap-1">
                  <span className="text-sm text-gray-400">{t("signup.slug_preview_prefix")}</span>
                  <input
                    {...form.register("slug")}
                    placeholder={t("signup.slug_placeholder")}
                    className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                  />
                </div>
                <p className="mt-1 text-xs text-gray-400">{t("signup.slug_hint")}</p>
                <FieldError message={form.formState.errors.slug?.message} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.admin_name_label")}</label>
                <input
                  {...form.register("admin_full_name")}
                  placeholder={t("signup.admin_name_placeholder")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
                <FieldError message={form.formState.errors.admin_full_name?.message} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.admin_email_label")}</label>
                <input
                  type="email"
                  {...form.register("admin_email")}
                  placeholder={t("signup.admin_email_placeholder")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
                <FieldError message={form.formState.errors.admin_email?.message} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.password_label")}</label>
                <input
                  type="password"
                  {...form.register("admin_password")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
                <p className="mt-1 text-xs text-gray-400">{t("signup.password_hint")}</p>
                <FieldError message={form.formState.errors.admin_password?.message} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.password_confirm_label")}</label>
                <input
                  type="password"
                  {...form.register("admin_password_confirm")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
                <FieldError message={form.formState.errors.admin_password_confirm?.message} />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t("signup.phone_label")}</label>
                <input
                  {...form.register("phone")}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
              </div>
            </div>

            <label className="flex items-start gap-2 text-sm text-gray-700 pt-2">
              <input type="checkbox" {...form.register("accept_terms")} className="mt-0.5" />
              <span>
                {t("signup.accept_terms").replace("{v}", catalog?.terms_version ?? "")}{" "}
                <span className="text-gray-400">{t("signup.terms_no_page_yet")}</span>
              </span>
            </label>
            <FieldError message={form.formState.errors.accept_terms?.message} />

            <div className="flex justify-between items-center pt-2">
              <button type="button" onClick={() => setStep(1)} className="text-sm font-semibold text-gray-500 hover:text-gray-700">
                {t("signup.back_btn")}
              </button>
              <button
                type="submit"
                className="rounded-lg bg-brand-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
              >
                {t("signup.continue_btn")}
              </button>
            </div>
          </form>
        )}

        {/* ── Step 3: summary ── */}
        {step === 3 && selectedPackage && selectedPrice && (
          <div>
            <h2 className="text-lg font-semibold text-gray-800 mb-4">{t("signup.summary_title")}</h2>

            <div className="rounded-lg bg-gray-50 border border-gray-200 p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">{t("signup.summary_package_label")}</span>
                <span className="font-semibold text-gray-800">{selectedPackage.display_name ?? selectedPackage.tier}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">{t("signup.summary_period_label")}</span>
                <span className="font-semibold text-gray-800">{period === "MONTHLY" ? t("signup.monthly") : t("signup.annual")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">{t("signup.summary_price_label")}</span>
                <span className="font-semibold text-gray-800">{formatCurrency(selectedPrice.total, selectedPrice.currency)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">{t("signup.summary_company_label")}</span>
                <span className="font-semibold text-gray-800">{form.getValues("company_name")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">{t("signup.summary_email_label")}</span>
                <span className="font-semibold text-gray-800">{form.getValues("admin_email")}</span>
              </div>
            </div>

            {submitError && (
              <p className="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{submitError}</p>
            )}

            <div className="flex justify-between items-center mt-6">
              <button type="button" onClick={() => setStep(2)} className="text-sm font-semibold text-gray-500 hover:text-gray-700">
                {t("signup.back_btn")}
              </button>
              <button
                type="button"
                disabled={submitting}
                onClick={() => void onSubmit()}
                className="rounded-lg bg-brand-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
              >
                {submitting ? t("signup.submitting_btn") : t("signup.submit_btn")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
