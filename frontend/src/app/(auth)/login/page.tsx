"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { loginWithPassword } from "@/lib/demo-auth";
import { rawPost } from "@/lib/api";
import { t } from "@/lib/i18n";
import { PublicContactLink } from "@/components/features/auth/PublicContactLink";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [lockoutMessage, setLockoutMessage] = useState("");
  const [loading, setLoading]   = useState(false);
  const [emailNotVerified, setEmailNotVerified] = useState(false);
  const [resendSent, setResendSent] = useState(false);
  const [resending, setResending]   = useState(false);

  // Read URL params client-side only to avoid SSR/hydration mismatch.
  // useSearchParams() requires <Suspense> in Next.js 14; window.location is safer here.
  const [sessionExpired, setSessionExpired] = useState(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setSessionExpired(params.get("reason") === "session_expired");
    const prefill = params.get("email");
    if (prefill) setEmail(prefill);
  }, []);

  const handleResend = async () => {
    if (!email.trim()) return;
    setResending(true);
    try {
      await rawPost("/api/v1/auth/resend-verification", { email: email.trim() });
    } catch {
      // Always shows the same message regardless of outcome — never reveals account existence.
    } finally {
      setResending(false);
      setResendSent(true);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLockoutMessage("");
    setEmailNotVerified(false);
    setResendSent(false);
    setLoading(true);
    await new Promise((r) => setTimeout(r, 300));
    let session;
    try {
      session = await loginWithPassword(email, password);
    } catch (err) {
      if (err instanceof Error) {
        const status = (err as Error & { status?: number }).status;
        const code   = (err as Error & { code?: string }).code;
        if (code === "AUTH_NOT_CONFIGURED" || code === "AUTH_SERVICE_UNAVAILABLE") {
          setError(t("login.auth_unavailable"));
          setLoading(false);
          return;
        }
        if (status === 429) {
          setLockoutMessage(err.message);
          setLoading(false);
          return;
        }
        if (status === 403 && code === "EMAIL_NOT_VERIFIED") {
          setEmailNotVerified(true);
          setLoading(false);
          return;
        }
        if (status === 403) {
          setError(err.message);
          setLoading(false);
          return;
        }
      }
      // Unexpected error shape — fall through to the generic message below.
    }
    if (!session) {
      setError(t("login.invalid_credentials"));
      setLoading(false);
      return;
    }
    // Force password reset before proceeding
    if (session.mustResetPassword) {
      router.push(`/change-password?userId=${session.id}`);
      return;
    }
    // Terms re-acceptance comes after a forced password reset (the user logs
    // in again afterward, re-evaluating this flag fresh at that point).
    if (session.termsAcceptanceRequired) {
      router.push("/accept-terms");
      return;
    }
    // Return to the intended URL, or route to the user's org dashboard
    const params = new URLSearchParams(window.location.search);
    const from   = params.get("from");
    const dest   = from && (from.startsWith("/") && !from.startsWith("/login"))
      ? from
      : `/${session.orgSlug}/dashboard`;
    router.push(dest);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex">
      {/* ── Login form ── */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-2xl shadow-2xl p-8">
            <div className="mb-7">
              <h1 className="text-2xl font-bold text-gray-900">{t("login.title")}</h1>
              <p className="text-gray-500 text-sm mt-1">{t("login.subtitle")}</p>
            </div>

            {sessionExpired && (
              <div className="mb-5 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                {t("login.session_expired")}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">
                  {t("login.email_label")}
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  placeholder={t("login.email_placeholder")}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-200 outline-none transition"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">
                  {t("login.password_label")}
                </label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="off"
                  placeholder={t("login.password_placeholder")}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-200 outline-none transition"
                />
                <Link
                  href={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`}
                  className="mt-1.5 inline-block text-sm font-semibold text-brand-600 hover:text-brand-700"
                >
                  {t("login.forgot_link")}
                </Link>
              </div>

              {lockoutMessage ? (
                // Rate limit, not a credential error — amber, not red.
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                  {lockoutMessage}
                </div>
              ) : emailNotVerified ? (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 space-y-2">
                  <p>{t("login.email_not_verified")}</p>
                  {resendSent ? (
                    <p className="text-emerald-700">{t("verify_email.resend_sent")}</p>
                  ) : (
                    <button
                      type="button"
                      disabled={resending}
                      onClick={() => void handleResend()}
                      className="font-semibold underline disabled:opacity-60"
                    >
                      {t("verify_email.resend_btn")}
                    </button>
                  )}
                </div>
              ) : error && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-brand-600 py-3 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    {t("login.signing_in")}
                  </>
                ) : t("login.submit_btn")}
              </button>
            </form>

            <p className="text-center text-sm text-gray-500 mt-5">
              <Link href="/signup" className="font-semibold text-brand-600 hover:text-brand-700">
                {t("login.create_account")}
              </Link>
            </p>
          </div>

          <p className="text-center text-slate-400 text-xs mt-6">
            <Link href="/getting-started" className="underline hover:text-slate-300">
              {t("login.getting_started_link")}
            </Link>
            {" · "}
            <Link href="/terms" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-300">
              {t("legal.terms_title")}
            </Link>
            {" · "}
            <Link href="/privacy" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-300">
              {t("legal.privacy_title")}
            </Link>
            <PublicContactLink className="underline hover:text-slate-300" prefix=" · " />
          </p>
          <p className="text-center text-slate-400 text-xs mt-2">
            {t("login.footer_tagline")}
          </p>
        </div>
      </div>
    </div>
  );
}
