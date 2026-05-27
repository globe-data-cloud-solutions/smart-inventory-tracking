"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoTenant } from "@/lib/demo-data";
import { t } from "@/lib/i18n";

interface LotRecord {
  lot_number: string; product_id: string; product_name: string; product_sku: string;
  warehouse_id: string; warehouse_name: string; quantity: number;
  received_at: string; expiry_date: string | null; status: "ACTIVE" | "DEPLETED" | "EXPIRED";
}

const STATUS_CLASS: Record<string, string> = {
  ACTIVE:   "bg-green-100 text-green-800",
  DEPLETED: "bg-gray-100 text-gray-400",
  EXPIRED:  "bg-red-100 text-red-900",
};

function daysUntilExpiry(expiry: string | null): number | null {
  if (!expiry) return null;
  return Math.round((new Date(expiry).getTime() - Date.now()) / 86_400_000);
}

function buildTenantLots(tenant: DemoTenant): LotRecord[] {
  const results: LotRecord[] = [];
  const year = 2026; let seq = 1;
  for (const p of tenant.products.filter((p) => p.batchTracking)) {
    const lotNum = `LOT-${year}-${String(seq).padStart(3, "0")}`;
    const month  = String((seq % 4) + 1).padStart(2, "0");
    seq++;
    for (const [whId, qty] of Object.entries(p.stock)) {
      const wh = tenant.warehouses.find((w) => w.id === whId);
      if (!wh) continue;
      const expiry = `${year + 1}-${month}-01`;
      const expDays = daysUntilExpiry(expiry);
      const status: LotRecord["status"] = qty === 0 ? "DEPLETED"
        : expDays !== null && expDays < 0 ? "EXPIRED" : "ACTIVE";
      results.push({ lot_number: lotNum, product_id: p.id, product_name: p.name, product_sku: p.sku,
        warehouse_id: whId, warehouse_name: wh.name, quantity: qty,
        received_at: `${year}-${month}-01`, expiry_date: expiry, status });
    }
  }
  return results;
}

export default function LotsPage() {
  const { org } = useParams() as { org: string };
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "ACTIVE" | "DEPLETED" | "EXPIRED">("ALL");

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("lots.title")}</h2>
      <p className="text-sm text-gray-500 mt-1 mb-6">{org} · {t("lots.subtitle")}</p>
      <div className="bg-white border border-gray-200 rounded-md p-12 text-center">
        <p className="text-gray-700 font-semibold mb-2">No Lot Records Found</p>
        <p className="text-sm text-gray-400">{t("lots.enable_batch_hint")}</p>
      </div>
    </div>
  );

  const tenantLots = buildTenantLots(tenant);

  if (tenantLots.length === 0) {
    return (
      <div className="p-8">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("lots.title")}</h2>
        <p className="text-sm text-gray-500 mt-1 mb-6">{tenant.name} · {t("lots.no_batch_products")}</p>
        <div className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-400 text-sm">
          {t("lots.enable_batch_hint")}
        </div>
      </div>
    );
  }

  const counts = {
    ACTIVE:   tenantLots.filter((l) => l.status === "ACTIVE").length,
    DEPLETED: tenantLots.filter((l) => l.status === "DEPLETED").length,
    EXPIRED:  tenantLots.filter((l) => l.status === "EXPIRED").length,
  };

  const filtered = tenantLots.filter((l) => {
    const q = search.toLowerCase();
    const matchSearch = !search.trim() || l.lot_number.toLowerCase().includes(q) ||
      l.product_sku.toLowerCase().includes(q) || l.product_name.toLowerCase().includes(q);
    return matchSearch && (statusFilter === "ALL" || l.status === statusFilter);
  });

  const uniqueLots = Array.from(new Set(filtered.map((l) => l.lot_number)));

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("lots.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{tenant.name} · {t("lots.subtitle")}</p>
      </div>

      {/* Search + filter */}
      <div className="flex gap-3 mb-6 flex-wrap items-center">
        <div className="relative flex-1 min-w-[240px]">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
          <input
            type="text" value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("lots.search_placeholder")}
            className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-md outline-none"
          />
        </div>
        <div className="flex gap-1.5">
          {(["ALL", "ACTIVE", "DEPLETED", "EXPIRED"] as const).map((s) => {
            const count = s === "ALL" ? tenantLots.length : counts[s];
            const cls   = s !== "ALL" ? (STATUS_CLASS[s] ?? "bg-gray-100 text-gray-700") : "bg-gray-100 text-gray-700";
            const active = statusFilter === s;
            return (
              <button key={s} onClick={() => setStatusFilter(s)}
                className={`text-xs font-bold px-3 py-1 rounded-full cursor-pointer border-2 transition-all ${
                  active ? `${cls} border-[#0f2d1f]` : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                }`}
              >
                {s} ({count})
              </button>
            );
          })}
        </div>
      </div>

      {uniqueLots.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-400 text-sm">
          {t("lots.no_results")}
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {uniqueLots.map((lotNum) => {
            const rows    = filtered.filter((l) => l.lot_number === lotNum);
            const first   = rows[0]!;
            const total   = rows.reduce((a, r) => a + r.quantity, 0);
            const expDays = daysUntilExpiry(first.expiry_date);
            const expSoon = expDays !== null && expDays >= 0 && expDays <= 30;
            const expired = expDays !== null && expDays < 0;
            const stClass = STATUS_CLASS[first.status] ?? "bg-gray-100 text-gray-600";

            return (
              <div key={lotNum} className="bg-white border border-gray-200 rounded-md overflow-hidden">
                <div className="px-5 py-3.5 bg-gray-50 border-b-2 border-gray-200 flex items-center justify-between flex-wrap gap-2.5">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-bold text-gray-800">{lotNum}</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${stClass}`}>{first.status}</span>
                    {expSoon && (
                      <span className="text-xs font-bold bg-amber-100 text-amber-800 px-2 py-0.5 rounded">
                        ⚠ {t("lots.expires_in")} {expDays}d
                      </span>
                    )}
                    {expired && (
                      <span className="text-xs font-bold bg-red-100 text-red-900 px-2 py-0.5 rounded">
                        {t("lots.expired")} {Math.abs(expDays!)}d {t("lots.ago")}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-5 text-xs text-gray-500 flex-wrap">
                    <span><strong className="text-gray-800">{first.product_name}</strong> · {first.product_sku}</span>
                    <span>{t("lots.total")}: <strong className="text-eth-forest">{total.toLocaleString()}</strong> {t("lots.units")}</span>
                    {first.expiry_date && (
                      <span>{t("lots.expiry")}: <strong className={expired ? "text-red-600" : "text-gray-700"}>{first.expiry_date}</strong></span>
                    )}
                    <span>{t("lots.received")}: {first.received_at}</span>
                  </div>
                </div>

                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-gray-50">
                      {["lots.warehouse_col","warehouse_type.MWH","lots.quantity","lots.pct_of_lot"].map((key) => (
                        <th key={key} className="px-3.5 py-2 text-left text-[11px] font-bold text-gray-400 uppercase tracking-wide">
                          {t(key)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => {
                      const wh  = tenant.warehouses.find((w) => w.id === r.warehouse_id);
                      const pct = total > 0 ? Math.round((r.quantity / total) * 100) : 0;
                      return (
                        <tr key={i} className="border-t border-gray-100">
                          <td className="px-3.5 py-2 font-semibold text-gray-800">{r.warehouse_name}</td>
                          <td className="px-3.5 py-2">
                            <span className="text-xs font-bold bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">{wh?.type ?? "WH"}</span>
                          </td>
                          <td className={`px-3.5 py-2 font-bold ${r.quantity > 0 ? "text-eth-forest" : "text-gray-400"}`}>
                            {r.quantity.toLocaleString()}
                          </td>
                          <td className="px-3.5 py-2">
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-1.5 bg-gray-100 rounded overflow-hidden max-w-[80px]">
                                {/* bar width is runtime-computed */}
                                <div className="h-full rounded" style={{ width: `${pct}%`, background: tenant.color }} />
                              </div>
                              <span className="text-xs text-gray-500">{pct}%</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
