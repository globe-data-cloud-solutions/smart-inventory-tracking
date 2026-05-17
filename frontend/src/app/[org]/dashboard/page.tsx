"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { getSession } from "@/lib/demo-auth";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import {
  DEMO_TENANTS,
  getLowStockProducts,
  getTotalStock,
  type DemoProduct,
} from "@/lib/demo-data";
import { t } from "@/lib/i18n";

/* ── Summary card ─────────────────────────────────────────────────────────── */
function SummaryCard({ title, subtitle, rows }: {
  title: string;
  subtitle: string;
  rows: { label: string; value: string | number; warn?: boolean }[];
}) {
  return (
    <div className="bg-white border border-gray-200 rounded overflow-hidden mb-6">
      {/* brand accent strip — uses --tenant-color injected by [org]/layout.tsx */}
      <div className="h-1 bg-[var(--tenant-color)]" />
      <div className="px-6 py-4 bg-[#0f2d1f] flex items-center justify-between">
        <div>
          <p className="font-bold text-base text-white m-0">{title}</p>
          <p className="text-xs text-emerald-300 mt-0.5">{subtitle}</p>
        </div>
        {/* inline: multi-stop 3-color gradient — Tailwind only supports 2-stop direction gradients */}
        <div
          className="h-1.5 w-[28%] rounded"
          style={{ background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)" }}
        />
      </div>
      {/* stat columns — count is runtime data; Tailwind JIT cannot build classes from template literals */}
      <div className="grid" style={{ gridTemplateColumns: `repeat(${rows.length},1fr)` }}>
        {rows.map((r, i) => (
          <div
            key={i}
            className={[
              "px-6 py-5 text-center",
              i < rows.length - 1 ? "border-r border-gray-100" : "",
              r.warn ? "bg-red-50" : "bg-white",
            ].join(" ")}
          >
            <p className={`text-3xl font-extrabold m-0 ${r.warn ? "text-red-600" : "text-eth-forest"}`}>
              {typeof r.value === "number" ? r.value.toLocaleString() : r.value}
            </p>
            <p className="text-xs text-gray-500 mt-1 font-medium">{r.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Inventory table ──────────────────────────────────────────────────────── */
function InventoryTable({ products, getQty, title, subtitle }: {
  products: DemoProduct[];
  getQty: (p: DemoProduct) => number;
  title: string;
  subtitle: string;
}) {
  const categories = Array.from(new Set(products.map((p) => p.category)));
  return (
    <div className="flex flex-col gap-5">
      {categories.map((cat) => {
        const items = products.filter((p) => p.category === cat);
        const total = items.reduce((a, p) => a + getQty(p), 0);
        return (
          <div key={cat} className="bg-white border border-gray-200 rounded overflow-hidden">
            {/* uses --tenant-color injected by [org]/layout.tsx */}
            <div className="h-[3px] bg-[var(--tenant-color)]" />
            <div className="px-5 py-3 bg-gray-50 border-b-2 border-gray-200 flex items-center justify-between">
              <span className="text-sm font-bold text-gray-800">
                {title}{" "}
                <span className="text-gray-400 font-normal">· {subtitle} · {cat}</span>
              </span>
              <span className="text-xs font-bold text-gray-500 bg-gray-200 px-2 py-0.5 rounded">
                {items.length} {t("table.skus")}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    {[
                      { key: "table.sku",           align: "text-left"  },
                      { key: "table.product",        align: "text-left"  },
                      { key: "table.stock",          align: "text-right" },
                      { key: "table.reorder_point",  align: "text-right" },
                      { key: "table.status",         align: "text-left"  },
                    ].map((h) => (
                      <th
                        key={h.key}
                        className={`px-4 py-2.5 ${h.align} text-xs font-bold text-gray-500 uppercase tracking-wide`}
                      >
                        {t(h.key)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((p, idx) => {
                    const qty = getQty(p);
                    const isLow = qty < p.reorderPoint;
                    return (
                      <tr
                        key={p.id}
                        className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}
                      >
                        <td className="px-4 py-2.5 font-mono text-xs text-gray-400">{p.sku}</td>
                        <td className="px-4 py-2.5 font-semibold text-gray-800">{p.name}</td>
                        <td className="px-4 py-2.5 text-right font-bold text-gray-900">{qty.toLocaleString()}</td>
                        <td className="px-4 py-2.5 text-right text-gray-400">{p.reorderPoint.toLocaleString()}</td>
                        <td className="px-4 py-2.5">
                          <span
                            className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-0.5 rounded border ${
                              isLow
                                ? "bg-red-50 text-red-600 border-red-200"
                                : "bg-green-50 text-emerald-600 border-emerald-200"
                            }`}
                          >
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${isLow ? "bg-red-600" : "bg-emerald-600"}`}
                            />
                            {isLow ? t("alerts.low_stock") : t("dashboard.in_stock")}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="bg-gray-100 border-t-2 border-gray-200">
                    <td colSpan={2} className="px-4 py-2.5 text-xs font-semibold text-gray-500">
                      {items.length} {t("table.products")}
                    </td>
                    <td className="px-4 py-2.5 text-right font-extrabold text-eth-forest text-sm">
                      {total.toLocaleString()}
                    </td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────────── */
export default function OrgDashboard() {
  const { org } = useParams() as { org: string };
  const user = getSession();
  if (!user) return null;

  // ── SA home (/admin/dashboard)
  if (org === SA_ORG_SLUG) {
    const totalLoc   = DEMO_TENANTS.reduce((a, t) => a + t.warehouses.length, 0);
    const totalSKUs  = DEMO_TENANTS.reduce((a, t) => a + t.products.length, 0);
    const totalUnits = DEMO_TENANTS.reduce(
      (a, ten) => a + ten.products.reduce((b, p) => b + getTotalStock(p), 0), 0
    );
    return (
      <div className="p-8">
        <SummaryCard
          title={t("dashboard.platform_overview")}
          subtitle={t("dashboard.sa_subtitle")}
          rows={[
            { label: t("dashboard.stat_tenants"),    value: DEMO_TENANTS.length },
            { label: t("dashboard.stat_locations"),  value: totalLoc },
            { label: t("table.skus"),                value: totalSKUs },
            { label: t("dashboard.stat_units"),      value: totalUnits },
            { label: t("dashboard.stat_users"),      value: DEMO_TENANTS.reduce((a, ten) => a + ten.users.length, 0) + 1 },
          ]}
        />
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-[#0f2d1f] m-0">{t("dashboard.tenants_heading")}</h3>
          <Link
            href="/onboard"
            className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded no-underline"
          >
            {t("wizard.onboard_btn")}
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-6">
          {DEMO_TENANTS.map((ten) => {
            const low   = getLowStockProducts(ten);
            const units = ten.products.reduce((a, p) => a + getTotalStock(p), 0);
            return (
              <Link key={ten.id} href={`/${ten.slug}/dashboard`} className="no-underline" style={{ "--tc": ten.color } as React.CSSProperties}>
                <div className="bg-white border border-gray-200 rounded overflow-hidden">
                  {/* tenant header — color is per-tenant, must be dynamic */}
                  <div className="px-5 py-4 flex items-center gap-3 bg-[var(--tc)]">
                    <span className="text-3xl">{ten.logo}</span>
                    <div>
                      <p className="font-bold text-base text-white m-0">{ten.name}</p>
                      <p className="text-xs text-white/75 m-0">{ten.industry}</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-4 p-3.5 gap-2 text-center">
                    {[
                      { l: t("dashboard.stat_locations"), v: ten.warehouses.length },
                      { l: t("table.skus"),               v: ten.products.length },
                      { l: t("dashboard.stat_units"),     v: units.toLocaleString() },
                      { l: t("alerts.low_stock"),         v: low.length, w: low.length > 0 },
                    ].map((s) => (
                      <div key={s.l}>
                        <p className={`text-xl font-extrabold m-0 ${s.w ? "text-red-600" : "text-gray-900"}`}>{s.v}</p>
                        <p className="text-xs text-gray-400 m-0">{s.l}</p>
                      </div>
                    ))}
                  </div>
                  <div className="px-5 py-2.5 border-t border-gray-100 bg-gray-50">
                    {/* tenant slug link — color is per-tenant */}
                    <span className="text-xs font-bold text-[var(--tc)]">
                      /{ten.slug}/dashboard →
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Tenant dashboard (/{slug}/dashboard)
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) {
    return (
      <p className="p-8 text-gray-500">
        {t("common.no_data")}: {org}
      </p>
    );
  }

  const lowStock   = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);

  // WM/NM — single warehouse view
  if (user.warehouseId) {
    const wh         = tenant.warehouses.find((w) => w.id === user.warehouseId);
    const myProducts = tenant.products.filter((p) => (p.stock[user.warehouseId!] ?? 0) > 0);
    const myUnits    = myProducts.reduce((a, p) => a + (p.stock[user.warehouseId!] ?? 0), 0);
    const myLow      = myProducts.filter((p) => (p.stock[user.warehouseId!] ?? 0) < p.reorderPoint);
    return (
      <div className="p-8">
        <SummaryCard
          title={wh?.name ?? t("dashboard.my_warehouse")}
          subtitle={`${wh?.location ?? ""} · ${user.role} access`}
          rows={[
            { label: t("dashboard.stat_units"),          value: myUnits },
            { label: t("dashboard.stat_skus_with_stock"),value: myProducts.length },
            { label: t("dashboard.in_stock"),            value: myProducts.length - myLow.length },
            { label: t("alerts.low_stock"),              value: myLow.length, warn: myLow.length > 0 },
          ]}
        />
        <InventoryTable
          products={myProducts}
          getQty={(p) => p.stock[user.warehouseId!] ?? 0}
          title={wh?.name ?? t("dashboard.my_warehouse")}
          subtitle={user.role}
        />
      </div>
    );
  }

  // TA / SA viewing a tenant
  return (
    <div className="p-8">
      <SummaryCard
        title={tenant.name}
        subtitle={`${tenant.industry} · ${user.role === "SA" ? t("dashboard.sa_viewing") : t("dashboard.tenant_admin")}`}
        rows={[
          { label: t("dashboard.stat_locations"), value: tenant.warehouses.length },
          { label: t("table.skus"),               value: tenant.products.length },
          { label: t("dashboard.stat_units"),     value: totalUnits },
          { label: t("alerts.low_stock"),         value: lowStock.length, warn: lowStock.length > 0 },
        ]}
      />

      {/* Warehouse summary */}
      <div className="bg-white border border-gray-200 rounded overflow-hidden mb-6">
        {/* uses --tenant-color from [org]/layout.tsx */}
        <div className="h-[3px] bg-[var(--tenant-color)]" />
        <div className="px-5 py-3 bg-gray-50 border-b-2 border-gray-200">
          <span className="text-sm font-bold text-gray-800">{t("dashboard.inventory_by_location")}</span>
        </div>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              {[
                "table.location",
                "table.type",
                "table.skus",
                "table.total_units",
                "alerts.low_stock",
              ].map((key) => (
                <th
                  key={key}
                  className="px-4 py-2.5 bg-gray-50 text-left text-xs font-bold text-gray-500 uppercase tracking-wide border-b border-gray-200"
                >
                  {t(key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tenant.warehouses.map((w, idx) => {
              const whUnits = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
              const whSKUs  = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
              const whLow   = tenant.products.filter(
                (p) => (p.stock[w.id] ?? 0) > 0 && (p.stock[w.id] ?? 0) < p.reorderPoint
              ).length;
              const typeClasses: Record<string, string> = {
                MWH:    "bg-amber-100 text-amber-800",
                RWH:    "bg-blue-100 text-blue-800",
                WH:     "bg-gray-100 text-gray-700",
                SUB_WH: "bg-violet-100 text-violet-800",
              };
              const typeClass = typeClasses[w.type] ?? "bg-gray-100 text-gray-500";
              return (
                <tr
                  key={w.id}
                  className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}
                >
                  <td className="px-4 py-2.5 font-semibold text-gray-800">
                    {w.parentId && (
                      <span className="text-gray-300 mr-1">↳</span>
                    )}
                    {w.name}
                    <p className="m-0 text-xs text-gray-400 font-normal">{w.location}</p>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                      {t(`warehouse_type.${w.type}`)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">{whSKUs}</td>
                  <td className="px-4 py-2.5 font-bold text-gray-900">{whUnits.toLocaleString()}</td>
                  <td className="px-4 py-2.5">
                    {whLow > 0 ? (
                      <span className="text-xs font-bold bg-red-50 text-red-600 border border-red-200 px-2 py-0.5 rounded">
                        {whLow} {t("dashboard.low_badge")}
                      </span>
                    ) : (
                      <span className="text-xs font-bold bg-green-50 text-emerald-600 border border-emerald-200 px-2 py-0.5 rounded">
                        {t("dashboard.ok_badge")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <InventoryTable
        products={tenant.products}
        getQty={getTotalStock}
        title={`${tenant.name} — ${t("dashboard.full_inventory")}`}
        subtitle={t("dashboard.all_locations")}
      />
    </div>
  );
}
