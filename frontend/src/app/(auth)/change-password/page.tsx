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
  const [isPendingSetup, setIsPendingSetup] = useState(false);
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
    // PENDING_SETUP users have no assigned position yet; they don't know (or can't
    // use) their current password because they couldn't fully log in before.
    setIsPendingSetup(session?.role === "PENDING_SETUP" || (session?.mustResetPassword === true && !session?.positions?.length));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
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
          // current_password omitted for PENDING_SETUP users — backend accepts null
          ...(isPendingSetup
            ? (currentPassword ? { current_password: currentPassword } : {})
            : { current_password: currentPassword }),
          new_password: newPassword,
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail ?? "Failed to update password.");
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
      setError("Network error — please try again.");
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
            <h2 className="text-lg font-bold text-white m-0">Password Updated</h2>
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
              Back to Sign in
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
          <h2 className="text-lg font-bold text-white m-0">Set Your Password</h2>
          <p className="text-xs text-emerald-300 mt-1 mb-0">
            Your account requires a password change before you can continue.
          </p>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="p-8 space-y-5">
          {/* Current password — hidden for PENDING_SETUP (optional for them) */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              {isPendingSetup
                ? t("change_password.current_label_optional")
                : "Current Password"}
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required={!isPendingSetup}   // not required for PENDING_SETUP
              autoFocus
              placeholder={isPendingSetup ? "Optional — leave blank if not known" : ""}
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              New Password <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              placeholder="Minimum 8 characters"
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
              Confirm New Password <span className="text-red-500">*</span>
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
            {loading ? "Updating…" : "Set New Password →"}
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
