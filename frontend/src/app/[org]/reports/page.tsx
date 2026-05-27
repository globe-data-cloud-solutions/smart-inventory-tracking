"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { t } from "@/lib/i18n";

export default function ReportsPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const REPORTS = [
    { key: "report:inventory_valuation", desc: t("report.inv_valuation_desc"), icon: "📊", href: `/${org}/analytics` },
    { key: "report:stock_movement",      desc: t("report.stock_movement_desc"), icon: "🔄", href: `/${org}/transfers` },
    { key: "report:expiry_alerts",       desc: t("report.expiry_alerts_desc"),  icon: "⚠️", href: `/${org}/inventory` },
    { key: "report:low_stock",           desc: t("report.low_stock_desc"),      icon: "📉", href: `/${org}/analytics` },
    { key: "report:lot_trace",           desc: t("report.lot_trace_desc"),      icon: "🔍", href: `/${org}/inventory` },
    { key: "report:dispatch_summary",    desc: t("report.dispatch_desc"),       icon: "🚚", href: `/${org}/transfers` },
  ];

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-6">{t("nav.reports")}</h2>
      <div className="grid grid-cols-2 gap-4">
        {REPORTS.map((r) => (
          <Link
            key={r.key}
            href={r.href}
            className="no-underline bg-white border border-gray-200 rounded p-5 flex items-start gap-3 hover:shadow-md hover:border-eth-forest transition-all"
          >
            <span className="text-3xl leading-none shrink-0">{r.icon}</span>
            <div>
              <p className="font-bold text-sm text-gray-800 m-0">{t(r.key)}</p>
              <p className="text-xs text-gray-500 mt-1">{r.desc}</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
