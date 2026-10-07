"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { getSession } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { HELP_MANIFEST, isDocVisibleToRole } from "@/lib/help/manifest";

export default function HelpPage() {
  const { org } = useParams() as { org: string };
  const session = getSession();

  if (!session) {
    return <p className="p-8 text-gray-500">{t("help.restricted")}</p>;
  }

  const docs = HELP_MANIFEST.filter((doc) => isDocVisibleToRole(doc, session.role));

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("help.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{t("help.subtitle")}</p>
      </div>

      <div className="space-y-3">
        {docs.map((doc) => {
          const clickable = doc.status === "published";
          const href = doc.link ?? `/${org}/help/${doc.id}`;
          const card = (
            <div
              className={`flex items-start justify-between gap-4 rounded-lg border p-4 ${
                clickable
                  ? "border-gray-200 bg-white hover:border-[#0f2d1f] hover:shadow-sm transition-all"
                  : "border-gray-100 bg-gray-50"
              }`}
            >
              <div>
                <p className={`font-semibold ${clickable ? "text-gray-800" : "text-gray-400"}`}>
                  {t(doc.titleKey)}
                </p>
                <p className={`text-sm mt-1 ${clickable ? "text-gray-500" : "text-gray-400"}`}>
                  {t(doc.summaryKey)}
                </p>
              </div>
              {doc.status === "coming_soon" && (
                <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide text-gray-400 bg-gray-200 px-2 py-1 rounded">
                  {t("help.coming_soon")}
                </span>
              )}
            </div>
          );

          return clickable ? (
            <Link key={doc.id} href={href} className="block no-underline">
              {card}
            </Link>
          ) : (
            <div key={doc.id}>{card}</div>
          );
        })}
      </div>
    </div>
  );
}
