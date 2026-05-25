"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { useInventoryStore } from "@/lib/inventory-state";
import { AddProductPanel } from "@/components/features/inventory/AddProductPanel";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type ApiProduct = { id: string; sku: string; name: string; unit: string; pack_size: number; };
type StockItem   = { product_id: string; current_stock: string; };
type Row        = { id: string; sku: string; name: string; category: string; unit: string; packSize: string; balance: number; batchTracking: boolean; isNew: boolean; isActive: boolean; };

export default function ProductsPage() {
  const { org }  = useParams() as { org: string };
  const canAdd    = usePermission("product:create");
  // Subscribe to issues, receives, and transfers so the total re-renders on any mutation.
  // getOnHand is a stable function reference — subscribing to the maps is what drives reactivity.
  const issues    = useInventoryStore((s) => s.issues);
  const receives  = useInventoryStore((s) => s.receives);
  const transfers = useInventoryStore((s) => s.transfers);
  const getOnHand = useInventoryStore((s) => s.getOnHand);

  // Suppress unused-variable warning — these subscriptions exist for reactivity only.
  void issues; void receives; void transfers;

  const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!tenant && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  const { data: inventoryStock = [] } = useQuery<StockItem[]>({
    queryKey: ["inventory-stock", org],
    queryFn:  () => api.get<StockItem[]>("/api/v1/inventory/analytics/stock"),
    enabled:  isGatewayMode && !!tenant && org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 30000,
  });

  // Sum current_stock across all warehouses per product for the tenant-wide balance.
  // CLAUDE.md §27: never filter by the viewing user's warehouse on the Products page.
  const productBalanceMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of inventoryStock) {
      map.set(item.product_id, (map.get(item.product_id) ?? 0) + parseFloat(item.current_stock));
    }
    return map;
  }, [inventoryStock]);

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;
  if (!tenant)             return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  // In gateway mode: show only real API products with real balances from inventory analytics.
  // In BFF mode: show demo products with Zustand-adjusted balances + any new API products.
  const demoRows: Row[] = isGatewayMode ? [] : tenant.products.map((p) => ({
    id: p.id, sku: p.sku, name: p.name, category: p.category, unit: p.unit, packSize: "—",
    // Sum getOnHand across every warehouse — identical for all users regardless of their
    // warehouse_id (CLAUDE.md §27: never filter by the viewing user's warehouse).
    balance: tenant.warehouses.reduce((total, wh) => total + getOnHand(p.id, wh.id, p.stock[wh.id] ?? 0), 0),
    batchTracking: p.batchTracking, isNew: false, isActive: true,
  }));

  const apiRows: Row[] = apiProducts.map((p) => ({
    id: p.id, sku: p.sku, name: p.name, category: "—", unit: p.unit, packSize: String(p.pack_size),
    balance: isGatewayMode ? (productBalanceMap.get(p.id) ?? 0) : 0,
    batchTracking: false, isNew: !isGatewayMode, isActive: true,
  }));

  const all   = isGatewayMode ? apiRows : [...demoRows, ...apiRows];
  const total = all.length;

  const COLS = ["table.sku","products.col_name","products.col_category","inventory.unit","products.col_pack_size","products.col_balance","products.col_batch","products.col_status"];

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("nav.products")}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {tenant.name} · {total} {t("table.skus")}
            {!isGatewayMode && apiProducts.length > 0 && (
              <span className="ml-2 text-[11px] font-bold bg-green-100 text-green-800 px-1.5 py-0.5 rounded-full">
                {apiProducts.length} new
              </span>
            )}
          </p>
        </div>
        {canAdd && <AddProductPanel apiBase="/api/v1/products" />}
      </div>

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant.color }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {COLS.map((key) => (
                  <th key={key} className="px-4 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide">{t(key)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {all.map((p, idx) => (
                <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-gray-400">
                    {p.sku}
                    {p.isNew && <span className="ml-1.5 text-[10px] font-bold bg-green-100 text-green-800 px-1 py-0.5 rounded">NEW</span>}
                  </td>
                  <td className="px-4 py-2.5 font-semibold text-gray-800">{p.name}</td>
                  <td className="px-4 py-2.5 text-gray-500">{p.category}</td>
                  <td className="px-4 py-2.5 text-gray-500">{p.unit}</td>
                  <td className="px-4 py-2.5 text-gray-500">{p.packSize}</td>
                  <td className={`px-4 py-2.5 text-right font-bold ${p.balance > 0 ? "text-gray-900" : "text-gray-400"}`}>
                    {p.balance > 0 ? p.balance.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${p.batchTracking ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-500"}`}>
                      {p.batchTracking ? t("dispatch.yes") : t("dispatch.no")}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${p.isActive ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-500"}`}>
                      {p.isActive ? t("products.status_active") : t("products.status_inactive")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="mt-3 text-xs text-gray-400">
        <strong className="text-gray-700">{t("products.balance_label")}</strong> — {t("products.balance_note")}
      </p>
    </div>
  );
}
