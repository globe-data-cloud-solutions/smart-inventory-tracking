"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, getTotalStock } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { useInventoryStore } from "@/lib/inventory-state";
import { AddProductPanel } from "@/components/features/inventory/AddProductPanel";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type ApiProduct = { id: string; sku: string; name: string; type_code: string; unit: string; pack_size: number; created_at: string; };
type Row        = { id: string; sku: string; name: string; category: string; unit: string; packSize: string; balance: number; batchTracking: boolean; isNew: boolean; isActive: boolean; };

export default function ProductsPage() {
  const { org }  = useParams() as { org: string };
  const canAdd            = usePermission("product:create");
  const adjustments       = useInventoryStore((s) => s.adjustments);
  const currentTenantSlug = useInventoryStore((s) => s.currentTenantSlug);

  // Net adjustment for a product across ALL warehouses (receives − issues for this session).
  // Transfers are excluded: moving stock between locations does not change the tenant-wide total.
  function getAdjTotal(productId: string): number {
    const adjs = adjustments.filter(
      (a) => a.tenantSlug === currentTenantSlug && a.productId === productId
    );
    const receives = adjs.filter((a) => a.type === "RECEIVE").reduce((n, a) => n + a.qty, 0);
    const issues   = adjs.filter((a) => a.type === "ISSUE").reduce((n, a) => n + a.qty, 0);
    return receives - issues;
  }

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!tenant && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;
  if (!tenant)             return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const demoRows: Row[] = tenant.products.map((p) => ({
    id: p.id, sku: p.sku, name: p.name, category: p.category, unit: p.unit, packSize: "—",
    balance: getTotalStock(p) + getAdjTotal(p.id),
    batchTracking: p.batchTracking, isNew: false, isActive: true,
  }));

  const apiRows: Row[] = apiProducts.map((p) => ({
    id: p.id, sku: p.sku, name: p.name, category: p.type_code, unit: p.unit, packSize: String(p.pack_size),
    balance: 0, batchTracking: false, isNew: true, isActive: true,
  }));

  const all   = [...demoRows, ...apiRows];
  const total = all.length;

  const COLS = ["table.sku","products.col_name","products.col_category","inventory.unit","products.col_pack_size","products.col_balance","products.col_batch","products.col_status"];

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("nav.products")}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {tenant.name} · {total} {t("table.skus")}
            {apiProducts.length > 0 && (
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
