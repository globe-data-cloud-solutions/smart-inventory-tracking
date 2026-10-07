"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";
import { DocumentRenderer } from "@/components/features/help/DocumentRenderer";

interface PackagesListOut {
  terms_version: string;
}

const FALLBACK_VERSION = "2026-10";

/**
 * Shared shell for the public /terms and /privacy pages (CLAUDE.md §15 S12).
 * No session required. Content is a DRAFT outline only — see the LEGAL TEXT
 * RULE: no invented clauses, every section just says "[To be supplied]"
 * until real, lawyer-reviewed text is supplied.
 */
export function LegalDocPage({ kind }: { kind: "terms" | "privacy" }) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const { data: catalog } = useQuery<PackagesListOut>({
    queryKey: ["public-packages-terms-version"],
    queryFn: () => api.get<PackagesListOut>("/api/v1/tenants/public/packages"),
    enabled: IS_GATEWAY_MODE,
    staleTime: 60_000,
  });

  const version = catalog?.terms_version ?? FALLBACK_VERSION;

  useEffect(() => {
    let cancelled = false;
    setMarkdown(null);
    setError(false);
    fetch(`/legal/${kind}-${version}.md`)
      .then((res) => {
        if (!res.ok) throw new Error("fetch failed");
        return res.text();
      })
      .then((text) => { if (!cancelled) setMarkdown(text); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [kind, version]);

  const titleKey = kind === "terms" ? "legal.terms_title" : "legal.privacy_title";

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-4 md:p-8">
      <div className="bg-white rounded-2xl shadow-2xl p-6 md:p-8 max-w-3xl w-full">
        <div className="flex items-start justify-between mb-4">
          <h1 className="text-2xl font-bold text-gray-900">{t(titleKey)}</h1>
          <AuthLangSwitcher />
        </div>

        <p className="text-sm font-semibold text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-6">
          {t("legal.draft_banner")}
        </p>

        {error && <p className="text-sm text-red-600">{t("common.error")}</p>}
        {!error && markdown === null && <p className="text-sm text-gray-500">{t("common.loading")}</p>}
        {!error && markdown !== null && <DocumentRenderer markdown={markdown} />}
      </div>
    </div>
  );
}
