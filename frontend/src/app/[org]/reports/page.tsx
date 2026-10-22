"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";

export default function ReportsPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const REPORTS = [
    { titleKey: "report.inventory_valuation", desc: t("report.inv_valuation_desc"), icon: "📊", href: `/${org}/reports/valuation` },
    { titleKey: "report.stock_movement",      desc: t("report.stock_movement_desc"), icon: "🔄", href: `/${org}/reports/stock-movement` },
    { titleKey: "report.expiry_alerts",       desc: t("report.expiry_alerts_desc"),  icon: "⚠️", href: `/${org}/reports/expiry` },
    { titleKey: "report.low_stock",           desc: t("report.low_stock_desc"),      icon: "📉", href: `/${org}/analytics` },
    { titleKey: "report.lot_trace",           desc: t("report.lot_trace_desc"),      icon: "🔍", href: `/${org}/inventory` },
    { titleKey: "report.dispatch_summary",    desc: t("report.dispatch_desc"),       icon: "🚚", href: `/${org}/reports/dispatch` },
  ];

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-1">{t("report.page_title")}</h2>
      <p className="text-sm text-gray-500 mb-6">{t("report.subtitle")}</p>
      <div className="grid grid-cols-2 gap-4">
        {REPORTS.map((r) => (
          <Link
            key={r.titleKey}
            href={r.href}
            className="no-underline bg-white border border-gray-200 rounded p-5 flex items-start gap-3 hover:shadow-md hover:border-eth-forest transition-all"
          >
            <span className="text-3xl leading-none shrink-0">{r.icon}</span>
            <div>
              <p className="font-bold text-sm text-gray-800 m-0">{t(r.titleKey)}</p>
              <p className="text-xs text-gray-500 mt-1">{r.desc}</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
