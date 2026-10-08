"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSession, logout } from "@/lib/demo-auth";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

interface TermsAcceptanceOut {
  accepted_version: string | null;
  accepted_at: string | null;
  accepted_by_email: string | null;
  current_version: string;
}

export default function AcceptTermsPage() {
  const router = useRouter();
  const [info, setInfo]       = useState<TermsAcceptanceOut | null>(null);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    const session = getSession();
    if (!session) { router.replace("/login"); return; }
    if (!session.termsAcceptanceRequired) {
      router.replace(`/${session.orgSlug}/dashboard`);
      return;
    }
    (async () => {
      try {
        const data = await api.get<TermsAcceptanceOut>("/api/v1/tenants/me/terms-acceptance");
        setInfo(data);
      } catch {
        setError(t("accept_terms.load_error"));
      } finally {
        setLoading(false);
      }
    })();
  }, [router]);

  function clearTermsFlag() {
    try {
      const raw = window.localStorage.getItem("smart_demo_session");
      if (raw) {
        const session = JSON.parse(raw) as Record<string, unknown>;
        session.termsAcceptanceRequired = false;
        window.localStorage.setItem("smart_demo_session", JSON.stringify(session));
      }
    } catch { /* ignore */ }
  }

  async function handleAccept() {
    setError("");
    setAccepting(true);
    try {
      await api.post<TermsAcceptanceOut>("/api/v1/tenants/me/terms-acceptance", {});
      clearTermsFlag();
      const session = getSession();
      router.push(session ? `/${session.orgSlug}/dashboard` : "/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("accept_terms.generic_error"));
    } finally {
      setAccepting(false);
    }
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <div className="min-h-screen bg-[#0f2d1f] flex items-center justify-center p-8">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
        <div className="bg-[#1B4332] px-8 py-5">
          <h2 className="text-lg font-bold text-white m-0">{t("accept_terms.page_title")}</h2>
          <p className="text-xs text-emerald-300 mt-1 mb-0">{t("accept_terms.page_subtitle")}</p>
        </div>

        <div className="p-8 space-y-5">
          {loading ? (
            <p className="text-sm text-gray-500">{t("common.loading")}</p>
          ) : (
            <>
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 space-y-1">
                <p className="m-0">
                  {t("accept_terms.current_version_label")}: <strong>{info?.current_version}</strong>
                </p>
                <p className="m-0">
                  {info?.accepted_version
                    ? `${t("accept_terms.previously_accepted_label")}: ${info.accepted_version}`
                    : t("accept_terms.no_prior_acceptance")}
                </p>
              </div>

              <p className="text-sm text-gray-600">
                <Link href="/terms" target="_blank" rel="noopener noreferrer" className="font-semibold text-brand-600 hover:text-brand-700 underline">
                  {t("legal.terms_title")}
                </Link>
                {" · "}
                <Link href="/privacy" target="_blank" rel="noopener noreferrer" className="font-semibold text-brand-600 hover:text-brand-700 underline">
                  {t("legal.privacy_title")}
                </Link>
              </p>

              {error && (
                <div className="bg-red-50 border border-red-200 rounded-md px-3.5 py-2.5 text-sm text-red-600">
                  {error}
                </div>
              )}

              <button
                type="button"
                disabled={accepting}
                onClick={() => void handleAccept()}
                className="w-full py-2.5 bg-emerald-700 text-white text-sm font-bold rounded-md hover:bg-emerald-800 disabled:opacity-50 transition-colors"
              >
                {accepting ? t("accept_terms.accepting") : t("accept_terms.accept_btn")}
              </button>

              <button
                type="button"
                onClick={handleLogout}
                className="w-full py-2.5 bg-transparent text-gray-500 text-sm font-semibold rounded-md hover:bg-gray-50 transition-colors"
              >
                {t("layout.sign_out")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
