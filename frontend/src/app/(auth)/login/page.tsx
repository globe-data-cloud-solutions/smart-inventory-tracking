"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { loginWithPassword } from "@/lib/demo-auth";
import { SA_USER } from "@/lib/demo-data";
import { rawPost } from "@/lib/api";
import { t } from "@/lib/i18n";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [lockoutMessage, setLockoutMessage] = useState("");
  const [loading, setLoading]   = useState(false);
  // Show password by default so users can see SA credentials without clicking
  const [showPwd, setShowPwd]   = useState(true);
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
        if (code === "AUTH_NOT_CONFIGURED") {
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

  const fillCredentials = (em: string, pw: string) => {
    setEmail(em);
    setPassword(pw);
    setError("");
    setLockoutMessage("");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex">
      {/* ── Left panel: SA quick access ── */}
      {/* Quick Access panel is for local development only.
          Remove before production deployment.
          Credentials are for the SA system account only. */}
      <div className="hidden lg:flex lg:w-96 bg-white/5 border-r border-white/10 flex-col p-8 overflow-y-auto h-screen">
        <h2 className="text-white font-bold text-lg mb-1">{t("login.quick_access")}</h2>

        <div className="mb-6">
          <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold mb-2">
            {t("login.system_admin_heading")}
          </p>
          {/* Clicking anywhere on the card except the eye icon fills both fields */}
          <div
            role="button"
            tabIndex={0}
            onClick={() => fillCredentials(SA_USER.email, SA_USER.password)}
            onKeyDown={(e) => e.key === "Enter" && fillCredentials(SA_USER.email, SA_USER.password)}
            className="w-full text-left p-3 rounded-lg bg-brand-600/30 border border-brand-500/40 hover:bg-brand-600/50 transition-colors group cursor-pointer"
          >
            <div className="flex items-center justify-between">
              <p className="text-white text-sm font-medium group-hover:text-brand-200">{SA_USER.name}</p>
              <span className="text-xs bg-brand-500 text-white rounded px-1.5 py-0.5">SA</span>
            </div>
            <p className="text-slate-400 text-xs font-mono mt-0.5">{SA_USER.email}</p>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-xs text-gray-400">{t("login.password")}:</span>
              <span className="text-xs font-mono text-slate-300">
                {showPwd ? SA_USER.password : "••••••••"}
              </span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setShowPwd((v) => !v); }}
                className="text-gray-400 hover:text-gray-200 transition-colors leading-none"
                aria-label={showPwd ? "Hide password" : "Show password"}
              >
                {showPwd ? "👁" : "👁‍🗨"}
              </button>
            </div>
            <p className="text-xs text-brand-300 group-hover:text-brand-100 mt-2 font-medium">
              {t("login.click_to_fill")} →
            </p>
          </div>
        </div>

        <div className="mt-auto border-t border-white/10 pt-4">
          <p className="text-xs text-slate-500">
            {t("login.personnel_hint")}
          </p>
        </div>
      </div>

      {/* ── Right panel: login form ── */}
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

            {/* Mobile credentials hint */}
            <div className="mt-6 p-4 rounded-lg bg-brand-50 border border-brand-100 lg:hidden">
              <p className="text-xs font-semibold text-brand-700 mb-2">{t("login.mobile_system_admin")}</p>
              <p className="text-xs font-mono text-brand-800">{SA_USER.email}</p>
              <p className="text-xs font-mono text-brand-800">{SA_USER.password}</p>
            </div>
          </div>

          <p className="text-center text-slate-400 text-xs mt-6">
            <Link href="/terms" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-300">
              {t("legal.terms_title")}
            </Link>
            {" · "}
            <Link href="/privacy" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-300">
              {t("legal.privacy_title")}
            </Link>
          </p>
          <p className="text-center text-slate-400 text-xs mt-2">
            {t("login.footer_tagline")}
          </p>
        </div>
      </div>
    </div>
  );
}
