"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { rawPost } from "@/lib/api";
import { t } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submittedRef = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const prefill = params.get("email");
    if (prefill) setEmail(prefill);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submittedRef.current || !email.trim()) return;
    submittedRef.current = true;
    setSubmitting(true);
    setRateLimited(false);
    try {
      await rawPost<{ sent: boolean }>("/api/v1/auth/forgot-password", { email: email.trim() });
      setSent(true);
    } catch (err) {
      const status = (err as Error & { status?: number }).status;
      if (status === 429) {
        setRateLimited(true);
        submittedRef.current = false;
      } else {
        // Always shows the same message regardless of outcome — never reveals account existence.
        setSent(true);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md w-full">
        <div className="flex items-start justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{t("forgot_password.title")}</h1>
          <AuthLangSwitcher />
        </div>

        {sent ? (
          <div>
            <p className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
              {t("forgot_password.sent")}
            </p>
            <Link href="/login" className="block mt-5 text-center text-sm font-semibold text-gray-500 hover:text-gray-700">
              {t("forgot_password.back_to_login")}
            </Link>
          </div>
        ) : (
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
            <p className="text-gray-500 text-sm mb-2">{t("forgot_password.subtitle")}</p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("forgot_password.email_label")}</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
              />
            </div>

            {rateLimited && (
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                {t("common.rate_limited")}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting || !email.trim()}
              className="w-full rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
            >
              {submitting ? t("forgot_password.submitting") : t("forgot_password.submit_btn")}
            </button>

            <Link href="/login" className="block mt-2 text-center text-sm font-semibold text-gray-500 hover:text-gray-700">
              {t("forgot_password.back_to_login")}
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}
