"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { t } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";
import { DocumentRenderer } from "@/components/features/help/DocumentRenderer";
import { PublicContactLink } from "@/components/features/auth/PublicContactLink";

/**
 * Public /getting-started page (CLAUDE.md §15 S12) — no session required,
 * same shell as /terms and /privacy (LegalDocPage.tsx). Renders the synced
 * copy of docs/GETTING_STARTED.md served from frontend/public/help/.
 */
export default function GettingStartedPage() {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/help/getting-started.md")
      .then((res) => {
        if (!res.ok) throw new Error("fetch failed");
        return res.text();
      })
      .then((text) => { if (!cancelled) setMarkdown(text); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-4 md:p-8 print:bg-white print:p-0 print:min-h-0">
      <div className="bg-white rounded-2xl shadow-2xl p-6 md:p-8 max-w-3xl w-full print:shadow-none print:rounded-none print:max-w-none print:p-0">
        <div className="flex items-start justify-between gap-4 mb-4 print:hidden">
          <h1 className="text-2xl font-bold text-gray-900">{t("getting_started.title")}</h1>
          <AuthLangSwitcher />
        </div>

        {error && <p className="text-sm text-red-600">{t("common.error")}</p>}
        {!error && markdown === null && <p className="text-sm text-gray-500">{t("common.loading")}</p>}
        {!error && markdown !== null && <DocumentRenderer markdown={markdown} />}

        <div className="flex flex-wrap gap-3 mt-6 print:hidden">
          <button
            type="button"
            onClick={() => window.print()}
            className="px-4 py-2 text-sm font-semibold text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            {t("getting_started.print_btn")}
          </button>
          <Link
            href="/signup"
            className="px-4 py-2 text-sm font-semibold text-white bg-brand-600 rounded-lg hover:bg-brand-700 transition-colors no-underline"
          >
            {t("getting_started.cta_create_account")}
          </Link>
          <PublicContactLink className="px-4 py-2 text-sm font-semibold text-gray-700 underline self-center" />
        </div>
      </div>
    </div>
  );
}
