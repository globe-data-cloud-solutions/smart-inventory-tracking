"use client";

import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, getLowStockProducts, getTotalStock } from "@/lib/demo-data";
import { t } from "@/lib/i18n";

export default function AnalyticsPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const low   = getLowStockProducts(tenant);
  const total = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
  const byWH  = tenant.warehouses
    .map((w) => ({ name: w.name, units: tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0) }))
    .sort((a, b) => b.units - a.units);
  const maxWH = byWH[0]?.units ?? 1;

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-6">{t("nav.analytics")}</h2>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Stock by location */}
        <div className="bg-white border border-gray-200 rounded p-5">
          <p className="text-sm font-bold text-gray-800 mb-4">{t("analytics.stock_by_location")}</p>
          {byWH.map((w) => (
            <div key={w.name} className="mb-2.5">
              <div className="flex justify-between mb-1">
                <span className="text-xs text-gray-700 truncate max-w-[70%]">{w.name}</span>
                <span className="text-xs font-semibold text-gray-900">{w.units.toLocaleString()}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded overflow-hidden">
                {/* bar width is runtime-computed — must use style */}
                {/* --bw: bar width is runtime-computed; --tenant-color from layout */}
                <div
                  className="h-full rounded bg-[var(--tenant-color)] w-[var(--bw)]"
                  style={{ "--bw": `${(w.units / maxWH) * 100}%` } as React.CSSProperties}
                />
              </div>
            </div>
          ))}
        </div>

        {/* Low stock alerts */}
        <div className="bg-white border border-gray-200 rounded p-5">
          <p className="text-sm font-bold text-gray-800 mb-4">
            {t("alerts.low_stock")}{" "}
            <span className="bg-red-100 text-red-600 text-xs px-2 py-0.5 rounded ml-1.5">{low.length}</span>
          </p>
          {low.length === 0 && (
            <p className="text-sm text-emerald-600 bg-green-50 px-3 py-3 rounded">
              ✓ {t("analytics.all_stocked")}
            </p>
          )}
          {low.map((p) => (
            <div key={p.id} className="flex justify-between py-2 border-b border-gray-100">
              <div>
                <p className="text-xs font-semibold text-gray-800 m-0">{p.name}</p>
                <p className="text-[11px] text-gray-400 m-0">{p.sku}</p>
              </div>
              <div className="text-right">
                <p className="text-xs font-bold text-red-600 m-0">{getTotalStock(p).toLocaleString()}</p>
                <p className="text-[11px] text-gray-400 m-0">{t("table.reorder_point")}: {p.reorderPoint}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Summary stats */}
      <div className="bg-white border border-gray-200 rounded p-5">
        <p className="text-sm font-bold text-gray-800 mb-4">{t("analytics.summary")}</p>
        <div className="grid grid-cols-4 gap-4 text-center">
          {[
            { label: t("dashboard.stat_units"),     value: total.toLocaleString() },
            { label: t("analytics.active_skus"),    value: tenant.products.length },
            { label: t("dashboard.stat_locations"), value: tenant.warehouses.length },
            { label: t("alerts.low_stock"),         value: low.length },
          ].map((s) => (
            <div key={s.label} className="p-4 bg-gray-50 rounded">
              <p className="text-2xl font-extrabold text-eth-forest m-0">{s.value}</p>
              <p className="text-xs text-gray-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
