"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { rawPost } from "@/lib/api";
import { t } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";

type State = "verifying" | "verified" | "invalid" | "no-token";

export default function VerifyEmailPage() {
  const [state, setState] = useState<State>("verifying");
  const [resendEmail, setResendEmail] = useState("");
  const [resendSent, setResendSent] = useState(false);
  const [resending, setResending] = useState(false);
  const calledRef = useRef(false);

  useEffect(() => {
    if (calledRef.current) return;
    calledRef.current = true;

    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) {
      setState("no-token");
      return;
    }

    rawPost<{ verified: boolean }>("/api/v1/auth/verify-email", { token })
      .then(() => setState("verified"))
      .catch(() => setState("invalid"));
  }, []);

  async function handleResend() {
    if (!resendEmail.trim()) return;
    setResending(true);
    try {
      await rawPost("/api/v1/auth/resend-verification", { email: resendEmail.trim() });
    } catch {
      // Always shows the same message regardless of outcome — never reveals account existence.
    } finally {
      setResending(false);
      setResendSent(true);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md w-full">
        <div className="flex items-start justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{t("verify_email.title")}</h1>
          <AuthLangSwitcher />
        </div>

        {state === "verifying" && <p className="text-gray-500 text-sm">{t("verify_email.verifying")}</p>}

        {state === "verified" && (
          <div>
            <p className="text-emerald-700 font-semibold mb-1">{t("verify_email.verified_title")}</p>
            <p className="text-gray-500 text-sm mb-6">{t("verify_email.verified_body")}</p>
            <Link
              href="/login"
              className="block w-full text-center rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
            >
              {t("verify_email.go_to_login_btn")}
            </Link>
          </div>
        )}

        {(state === "invalid" || state === "no-token") && (
          <div>
            <p className="text-red-700 font-semibold mb-1">{t("verify_email.invalid_title")}</p>
            <p className="text-gray-500 text-sm mb-5">{t("verify_email.invalid_body")}</p>

            {resendSent ? (
              <p className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
                {t("verify_email.resend_sent")}
              </p>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">{t("verify_email.resend_label")}</label>
                  <input
                    type="email"
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                  />
                </div>
                <button
                  type="button"
                  disabled={resending || !resendEmail.trim()}
                  onClick={() => void handleResend()}
                  className="w-full rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
                >
                  {t("verify_email.resend_btn")}
                </button>
              </div>
            )}

            <Link href="/login" className="block mt-5 text-center text-sm font-semibold text-gray-500 hover:text-gray-700">
              {t("verify_email.back_to_login")}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
