"use client";

import { useState, Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSession, logout } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";

const API_BASE =
  process.env.NEXT_PUBLIC_AUTH_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "";

function ChangePasswordForm() {
  const router = useRouter();

  // Read URL params and session client-side only (avoids SSR/hydration mismatch)
  const [userId,         setUserId]         = useState("");
  // isPendingSetup: true only for role=PENDING_SETUP (non-TA user with no position).
  // Controls post-change action: logout + "contact admin" vs redirect to login.
  const [isPendingSetup, setIsPendingSetup] = useState(false);
  // isMustReset: true for any user with mustResetPassword=true (PENDING_SETUP + TA).
  // Controls whether current_password is optional in the form and request body.
  const [isMustReset,    setIsMustReset]    = useState(false);
  const [done,           setDone]           = useState(false);     // success + no-position state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword,     setNewPassword]     = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error,    setError]   = useState("");
  const [loading,  setLoading] = useState(false);

  useEffect(() => {
    const params  = new URLSearchParams(window.location.search);
    const uid     = params.get("userId") ?? getSession()?.id ?? "";
    const session = getSession();
    setUserId(uid);
    // PENDING_SETUP: non-TA user awaiting position assignment — needs admin action after reset.
    // TA users (role="TA") are the tenant admin; they don't need a position and should
    // be redirected to login (not shown "contact admin") after changing their password.
    setIsPendingSetup(session?.role === "PENDING_SETUP");
    setIsMustReset(session?.mustResetPassword === true);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword.length < 8) {
      setError(t("change_password.password_too_short"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("change_password.passwords_mismatch"));
      return;
    }
    setLoading(true);
    try {
      const jwt = getSession()?.jwtToken ?? "";
      const res = await fetch(`${API_BASE}/api/v1/auth/password/${userId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(jwt ? { "Authorization": `Bearer ${jwt}` } : {}),
        },
        body: JSON.stringify({
          user_id:          userId,
          // current_password optional for any must_reset user (PENDING_SETUP + TA)
          ...(isMustReset
            ? (currentPassword ? { current_password: currentPassword } : {})
            : { current_password: currentPassword }),
          new_password: newPassword,
        }),
      });
      if (!res.ok) {
        if (res.status === 401) {
          setError(t("change_password.wrong_current"));
          return;
        }
        if (res.status === 403) {
          // Stale/mismatched session — the bearer JWT's sub no longer matches
          // this user_id. Show why, then send them to sign in again.
          setError(t("change_password.session_mismatch"));
          logout();
          router.push("/login");
          return;
        }
        const body = (await res.json().catch(() => ({}))) as {
          detail?: string | { code?: string; message?: string };
        };
        const det = body.detail;
        const detMessage =
          typeof det === "string" ? det : (typeof det === "object" && det !== null ? det.message : undefined);
        setError(detMessage ?? t("change_password.generic_error"));
        return;
      }

      // Clear mustResetPassword from stored session
      try {
        const raw = localStorage.getItem("smart_demo_session");
        if (raw) {
          const session = JSON.parse(raw) as Record<string, unknown>;
          session.mustResetPassword = false;
          localStorage.setItem("smart_demo_session", JSON.stringify(session));
        }
      } catch { /* ignore */ }

      if (isPendingSetup) {
        // PENDING_SETUP: user has no position yet — show contact-admin message
        // instead of redirecting to login (where they'd just loop back here).
        logout();
        setDone(true);
      } else {
        // Normal must_reset path: redirect to login so they authenticate fresh.
        router.push("/login");
      }
    } catch {
      setError(t("change_password.network_error"));
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "w-full px-3 py-2.5 text-sm border border-gray-300 rounded-md outline-none bg-white focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600";

  // ── Success screen for PENDING_SETUP users ────────────────────────────────
  if (done) {
    return (
      <div className="min-h-screen bg-[#0f2d1f] flex items-center justify-center p-8">
        <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
          <div className="bg-[#1B4332] px-8 py-5">
            <h2 className="text-lg font-bold text-white m-0">{t("change_password.success_title")}</h2>
          </div>
          <div className="p-8 space-y-5">
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-4 text-sm text-emerald-800">
              {t("change_password.contact_admin")}
            </div>
            <button
              type="button"
              onClick={() => router.push("/login")}
              className="w-full py-2.5 bg-emerald-700 text-white text-sm font-bold rounded-md hover:bg-emerald-800 transition-colors"
            >
              {t("change_password.back_to_signin")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0f2d1f] flex items-center justify-center p-8">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
        <div className="bg-[#1B4332] px-8 py-5">
          <h2 className="text-lg font-bold text-white m-0">{t("change_password.page_title")}</h2>
          <p className="text-xs text-emerald-300 mt-1 mb-0">
            {t("change_password.page_subtitle")}
          </p>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="p-8 space-y-5">
          {/* Current password optional for any must_reset user (PENDING_SETUP + TA) */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              {isMustReset
                ? t("change_password.current_label_optional")
                : t("change_password.current_label")}
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required={!isMustReset}
              autoFocus
              placeholder={isMustReset ? t("change_password.current_placeholder_optional") : ""}
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              {t("change_password.new_label")} <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              placeholder={t("change_password.new_placeholder")}
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              {t("change_password.confirm_label")} <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className={inputClass}
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-md px-3.5 py-2.5 text-sm text-red-600">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-emerald-700 text-white text-sm font-bold rounded-md hover:bg-emerald-800 disabled:opacity-50 transition-colors"
          >
            {loading ? t("change_password.submitting") : t("change_password.submit_btn")}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ChangePasswordPage() {
  return (
    <Suspense>
      <ChangePasswordForm />
    </Suspense>
  );
}
