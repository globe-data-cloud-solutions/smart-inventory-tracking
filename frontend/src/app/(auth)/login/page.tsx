"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { login, loginWithDevEmail } from "@/lib/demo-auth";
import { SA_USER } from "@/lib/demo-data";
import { t } from "@/lib/i18n";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  // Show password by default so users can see SA credentials without clicking
  const [showPwd, setShowPwd]   = useState(true);

  // Read URL params client-side only to avoid SSR/hydration mismatch.
  // useSearchParams() requires <Suspense> in Next.js 14; window.location is safer here.
  const [sessionExpired, setSessionExpired] = useState(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setSessionExpired(params.get("reason") === "session_expired");
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    await new Promise((r) => setTimeout(r, 300));
    let session = login(email, password);
    if (!session) {
      // Fallback: try backend dev_email for API-created users (ENVIRONMENT=local only)
      session = await loginWithDevEmail(email, password);
    }
    if (!session) {
      setError("Invalid email or password.");
      setLoading(false);
      return;
    }
    // Force password reset before proceeding
    if (session.mustResetPassword) {
      router.push(`/change-password?userId=${session.id}`);
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
            System Administrator
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
            To add tenant accounts, sign in as SA and use Settings → Personnel.
          </p>
        </div>
      </div>

      {/* ── Right panel: login form ── */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="bg-white rounded-2xl shadow-2xl p-8">
            <div className="mb-7">
              <h1 className="text-2xl font-bold text-gray-900">Sign in</h1>
              <p className="text-gray-500 text-sm mt-1">Access your inventory dashboard</p>
            </div>

            {sessionExpired && (
              <div className="mb-5 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                Your session has expired. Please sign in again to continue.
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  placeholder="you@company.com"
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-200 outline-none transition"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="off"
                  placeholder="enter your password"
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-200 outline-none transition"
                />
              </div>

              {error && (
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
                    Signing in…
                  </>
                ) : "Sign in →"}
              </button>
            </form>

            {/* Mobile credentials hint */}
            <div className="mt-6 p-4 rounded-lg bg-brand-50 border border-brand-100 lg:hidden">
              <p className="text-xs font-semibold text-brand-700 mb-2">System Admin</p>
              <p className="text-xs font-mono text-brand-800">{SA_USER.email}</p>
              <p className="text-xs font-mono text-brand-800">{SA_USER.password}</p>
            </div>
          </div>

          <p className="text-center text-slate-400 text-xs mt-6">
            SMART Inventory Tracker · RBAC + ABAC · 3 languages
          </p>
        </div>
      </div>
    </div>
  );
}
