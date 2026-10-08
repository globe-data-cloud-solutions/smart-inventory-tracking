"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { rawPost } from "@/lib/api";
import { t } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";

type State = "form" | "no-token" | "success" | "invalid" | "rate-limited";

export default function ResetPasswordPage() {
  const [state, setState] = useState<State>("form");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [validationError, setValidationError] = useState("");
  const [tooShort, setTooShort] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submittedRef = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tok = params.get("token");
    if (!tok) {
      setState("no-token");
      return;
    }
    setToken(tok);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setValidationError("");
    setTooShort(false);

    if (newPassword.length < 8) {
      setValidationError(t("reset_password.password_too_short"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setValidationError(t("reset_password.passwords_mismatch"));
      return;
    }
    if (submittedRef.current) return;
    submittedRef.current = true;
    setSubmitting(true);
    try {
      await rawPost<{ reset: boolean }>("/api/v1/auth/reset-password", { token, new_password: newPassword });
      setState("success");
    } catch (err) {
      const status = (err as Error & { status?: number }).status;
      if (status === 422) {
        setTooShort(true);
      } else if (status === 429) {
        setState("rate-limited");
      } else {
        setState("invalid");
      }
      submittedRef.current = false;
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md w-full">
        <div className="flex items-start justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{t("reset_password.title")}</h1>
          <AuthLangSwitcher />
        </div>

        {state === "no-token" && (
          <div>
            <p className="text-red-700 font-semibold mb-1">{t("reset_password.invalid_title")}</p>
            <p className="text-gray-500 text-sm mb-5">{t("reset_password.invalid_body")}</p>
            <Link
              href="/forgot-password"
              className="block w-full text-center rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
            >
              {t("reset_password.request_new_btn")}
            </Link>
          </div>
        )}

        {state === "invalid" && (
          <div>
            <p className="text-red-700 font-semibold mb-1">{t("reset_password.invalid_title")}</p>
            <p className="text-gray-500 text-sm mb-5">{t("reset_password.invalid_body")}</p>
            <Link
              href="/forgot-password"
              className="block w-full text-center rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
            >
              {t("reset_password.request_new_btn")}
            </Link>
          </div>
        )}

        {state === "success" && (
          <div>
            <p className="text-emerald-700 font-semibold mb-1">{t("reset_password.success_title")}</p>
            <p className="text-gray-500 text-sm mb-6">{t("reset_password.success_body")}</p>
            <Link
              href="/login"
              className="block w-full text-center rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
            >
              {t("reset_password.go_to_login_btn")}
            </Link>
          </div>
        )}

        {(state === "form" || state === "rate-limited") && (
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("reset_password.new_label")}</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("reset_password.confirm_label")}</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
              />
            </div>

            {validationError && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {validationError}
              </div>
            )}
            {tooShort && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {t("reset_password.password_too_short")}
              </div>
            )}
            {state === "rate-limited" && (
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                {t("common.rate_limited")}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
            >
              {submitting ? t("reset_password.submitting") : t("reset_password.submit_btn")}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
