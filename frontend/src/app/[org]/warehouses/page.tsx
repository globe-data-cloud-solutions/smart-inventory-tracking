"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

interface ApiStockRow {
  product_id: string;
  warehouse_id: string;
  warehouse_name: string;
  warehouse_type: string | null;
  current_stock: number;
}

function sortByHierarchy(warehouses: DemoWarehouse[]): DemoWarehouse[] {
  const result: DemoWarehouse[] = [];
  const placed = new Set<string>();
  function place(parentId: string | null) {
    for (const wh of warehouses) {
      if (wh.parentId === parentId && !placed.has(wh.id)) {
        result.push(wh); placed.add(wh.id); place(wh.id);
      }
    }
  }
  place(null);
  for (const wh of warehouses) { if (!placed.has(wh.id)) result.push(wh); }
  return result;
}

function getDepth(warehouseId: string, warehouses: DemoWarehouse[], visited = new Set<string>()): number {
  if (visited.has(warehouseId)) return 0;
  visited.add(warehouseId);
  const wh = warehouses.find((w) => w.id === warehouseId);
  if (!wh?.parentId) return 0;
  return 1 + getDepth(wh.parentId, warehouses, visited);
}

const TYPE_LABEL: Record<string, string> = { MWH: "MWH", RWH: "RWH", WH: "WH", SUB_WH: "SUB_WH" };
const TYPE_CLASS: Record<string, string> = {
  MWH:    "bg-amber-100 text-amber-800",
  RWH:    "bg-blue-100  text-blue-800",
  WH:     "bg-gray-100  text-gray-700",
  SUB_WH: "bg-violet-100 text-violet-800",
};
const DB_TYPE_MAP: Record<string, DemoWarehouse["type"]> = {
  FACTORY: "MWH", REGIONAL: "RWH", RETAIL: "WH", SUBCENTER: "SUB_WH",
};

interface GatewayWarehouseRow {
  id: string;
  name: string;
  type: DemoWarehouse["type"];
  units: number;
  skuCount: number;
}

export default function WarehousesPage() {
  const { org } = useParams() as { org: string };

  const { data: stockData = [] } = useQuery<ApiStockRow[]>({
    queryKey: ["analytics-stock", org],
    queryFn:  () => api.get<ApiStockRow[]>("/api/v1/inventory/analytics/stock"),
    staleTime: 30000,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const isGatewayMode = stockData.length > 0;

  // ── Gateway mode: build rows from real API data, keyed by UUID ────────────
  let gatewayRows: GatewayWarehouseRow[] = [];
  if (isGatewayMode) {
    const byId = new Map<string, { name: string; type: DemoWarehouse["type"]; units: number; skus: Set<string> }>();
    for (const row of stockData) {
      const entry = byId.get(row.warehouse_id) ?? {
        name:  row.warehouse_name,
        type:  DB_TYPE_MAP[row.warehouse_type ?? ""] ?? "WH",
        units: 0,
        skus:  new Set<string>(),
      };
      entry.units += Number(row.current_stock);
      if (Number(row.current_stock) > 0) entry.skus.add(row.product_id);
      byId.set(row.warehouse_id, entry);
    }
    // Sort: MWH first, then RWH, then WH, then SUB_WH, then alphabetical within each tier
    const tierOrder: Record<string, number> = { MWH: 0, RWH: 1, WH: 2, SUB_WH: 3 };
    gatewayRows = Array.from(byId.entries())
      .map(([id, v]) => ({ id, name: v.name, type: v.type, units: v.units, skuCount: v.skus.size }))
      .sort((a, b) => (tierOrder[a.type] ?? 4) - (tierOrder[b.type] ?? 4) || a.name.localeCompare(b.name));
  }

  // ── Demo mode: use tenant.warehouses with hierarchy sort ──────────────────
  const sorted = isGatewayMode ? [] : sortByHierarchy(tenant.warehouses);

  const warehouseCount = isGatewayMode ? gatewayRows.length : tenant.warehouses.length;

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("warehouses.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{tenant.name} · {warehouseCount} {t("warehouses.locations")}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant.color }} />
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-50 border-b-2 border-gray-200">
              {["warehouses.col_name","warehouses.col_location","table.type","warehouses.col_manager","table.total_units","table.skus"].map((key) => (
                <th key={key} className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">{t(key)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isGatewayMode ? (
              gatewayRows.map((row, idx) => {
                const typeClass = TYPE_CLASS[row.type] ?? "bg-gray-100 text-gray-500";
                return (
                  <tr key={row.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-4 py-2.5 font-semibold text-gray-800">{row.name}</td>
                    <td className="px-4 py-2.5 text-gray-500">—</td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                        {TYPE_LABEL[row.type] ?? row.type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-700">—</td>
                    <td className="px-4 py-2.5 font-bold text-gray-900">{row.units.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-gray-700">{row.skuCount}</td>
                  </tr>
                );
              })
            ) : (
              sorted.map((w, idx) => {
                const whUnits = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
                const whSKUs  = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
                const typeClass = TYPE_CLASS[w.type] ?? "bg-gray-100 text-gray-500";
                const manager   = tenant.users.find((u) => u.warehouseId === w.id);
                const depth     = getDepth(w.id, tenant.warehouses);
                return (
                  <tr key={w.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    {/* indent is dynamic (depth * 24px) — must use style for this one property */}
                    <td className="px-4 py-2.5 font-semibold text-gray-800" style={{ paddingLeft: `${16 + depth * 24}px` }}>
                      {depth > 0 && <span className="text-gray-300 mr-1.5 font-mono">{"↳".repeat(depth)}</span>}
                      {w.name}
                    </td>
                    <td className="px-4 py-2.5 text-gray-500">{w.location}</td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                        {t(`warehouse_type.${w.type}`)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-700">{manager?.name ?? "—"}</td>
                    <td className="px-4 py-2.5 font-bold text-gray-900">{whUnits.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-gray-700">{whSKUs}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
