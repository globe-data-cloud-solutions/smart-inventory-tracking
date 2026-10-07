"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getSession } from "@/lib/demo-auth";
import { t, getCurrentLocale } from "@/lib/i18n";
import { getHelpDoc, isDocVisibleToRole } from "@/lib/help/manifest";
import { DocumentRenderer } from "@/components/features/help/DocumentRenderer";

export default function HelpDocPage() {
  const { org, docId } = useParams() as { org: string; docId: string };
  const session = getSession();
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const doc = getHelpDoc(docId);
  const allowed = !!session && !!doc && doc.status === "published" && !!doc.file && isDocVisibleToRole(doc, session.role);

  useEffect(() => {
    if (!allowed || !doc?.file) return;
    let cancelled = false;
    fetch(`/help/${doc.file}`)
      .then((res) => {
        if (!res.ok) throw new Error("fetch failed");
        return res.text();
      })
      .then((text) => { if (!cancelled) setMarkdown(text); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [allowed, doc?.file]);

  if (!session) {
    return <p className="p-8 text-gray-500">{t("help.restricted")}</p>;
  }
  if (!doc || !allowed) {
    return <p className="p-8 text-gray-500">{t("help.not_found")}</p>;
  }

  const locale = getCurrentLocale();

  return (
    <div className="p-8 max-w-3xl">
      <Link href={`/${org}/help`} className="text-sm font-semibold text-brand-600 hover:text-brand-700 no-underline">
        ← {t("help.back_to_help")}
      </Link>

      <div className="flex items-start justify-between gap-4 mt-4 mb-2">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t(doc.titleKey)}</h2>
        <button
          type="button"
          onClick={() => window.print()}
          className="shrink-0 px-3 py-1.5 text-xs font-semibold text-gray-600 border border-gray-300 rounded hover:bg-gray-50"
        >
          {t("help.print_btn")}
        </button>
      </div>

      {(doc.version || doc.updated) && (
        <p className="text-xs text-gray-400 mb-4">
          {doc.version && t("help.version_label").replace("{v}", doc.version)}
          {doc.version && doc.updated && " · "}
          {doc.updated && t("help.updated_label").replace("{d}", doc.updated)}
        </p>
      )}

      {locale === "am" && (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-4">
          {t("help.english_only_notice")}
        </p>
      )}

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        {error && <p className="text-sm text-red-600">{t("common.error")}</p>}
        {!error && markdown === null && <p className="text-sm text-gray-500">{t("common.loading")}</p>}
        {!error && markdown !== null && <DocumentRenderer markdown={markdown} />}
      </div>
    </div>
  );
}
