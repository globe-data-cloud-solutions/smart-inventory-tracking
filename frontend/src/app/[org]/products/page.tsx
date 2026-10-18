"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { useInventoryStore } from "@/lib/inventory-state";
import { AddProductPanel, type EditProductData } from "@/components/features/inventory/AddProductPanel";
import { ProductLabel } from "@/components/features/inventory/ProductLabel";
import { ProductImage } from "@/components/ui/ProductImage";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";
import { formatQty } from "@/lib/utils";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";

type ApiProduct = {
  id: string; sku: string; name: string; unit: string; pack_size: number;
  category?: string | null; is_discontinued?: boolean; is_controlled?: boolean;
  short_name?: string | null; description?: string | null; type_code?: string | null;
  brand?: string | null; packaging_type?: string | null; units_per_package?: number | null;
  reorder_point?: number | string | null; unit_price?: number | string | null; currency?: string | null;
  image_url?: string | null;
  batch_tracking?: boolean; expiry_tracking?: boolean; dispatch_strategy?: string | null;
};
type StockItem   = { product_id: string; current_stock: string; };
type Row        = {
  id: string; sku: string; name: string; category: string; unit: string; packSize: string;
  balance: number; batchTracking: boolean; isNew: boolean; isActive: boolean; is_discontinued: boolean;
  is_controlled: boolean; image_url?: string | null; editData: EditProductData;
};

export default function ProductsPage() {
  const { org }  = useParams() as { org: string };
  const tenantName = useTenantName(org);
  const session   = getSession();
  const canAdd    = usePermission("product:create");
  const canEditProducts = usePermission("product:update");
  const [editingProduct, setEditingProduct] = useState<Row | null>(null);
  const writeGuard = useWriteGuard();
  const writeGp = guardProps(writeGuard);
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

  const [showDiscontinued, setShowDiscontinued] = useState(false);
  const canDiscontinue = usePermission("product:discontinue");
  const [actionError, setActionError] = useState<string | null>(null);
  const qcProducts = useQueryClient();

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org, showDiscontinued],
    queryFn:  () => api.get<ApiProduct[]>(`/api/v1/products${showDiscontinued ? "?active_only=false" : ""}`),
    enabled:  org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  const { data: inventoryStock = [] } = useQuery<StockItem[]>({
    queryKey: ["inventory-stock", org],
    queryFn:  () => api.get<StockItem[]>("/api/v1/inventory/analytics/stock"),
    enabled:  isGatewayMode && org !== SA_ORG_SLUG,
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

  async function handleDiscontinue(productId: string, isCurrentlyDiscontinued: boolean) {
    setActionError(null);
    const action = isCurrentlyDiscontinued ? "reactivate" : "discontinue";
    try {
      await api.post(`/api/v1/products/${productId}/${action}`, {});
      void qcProducts.invalidateQueries({ queryKey: ["products", org] });
    } catch (err) {
      const e = err as { status?: number; code?: string; locations?: { warehouse: string; on_hand: number }[] };
      if (e.code === "PRODUCT_HAS_STOCK") {
        const locs = (e.locations ?? []).map((l) => `${l.warehouse}: ${l.on_hand} units`).join(", ");
        setActionError(t("product.discontinue_has_stock").replace("{locations}", locs));
      } else if (e.code === "PRODUCT_HAS_PENDING_TRANSACTIONS") {
        setActionError(t("product.discontinue_has_pending"));
      } else {
        setActionError(t("common.error"));
      }
    }
  }

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  // In demo mode without a matching demo tenant, there is nothing to show
  if (!tenant && !isGatewayMode) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  // In gateway mode: show only real API products with real balances from inventory analytics.
  // In BFF mode: show demo products with Zustand-adjusted balances + any new API products.
  const demoRows: Row[] = (isGatewayMode || !tenant) ? [] : tenant.products.map((p) => ({
    id: p.id, sku: p.sku, name: p.name, category: p.category, unit: p.unit, packSize: "—",
    // Sum getOnHand across every warehouse — identical for all users regardless of their
    // warehouse_id (CLAUDE.md §27: never filter by the viewing user's warehouse).
    balance: tenant.warehouses.reduce((total, wh) => total + getOnHand(p.id, wh.id, p.stock[wh.id] ?? 0), 0),
    batchTracking: p.batchTracking, isNew: false, isActive: true, is_discontinued: p.is_discontinued ?? false,
    is_controlled: false,
    editData: {
      sku: p.sku, name: p.name, category: p.category, unit: p.unit,
    },
  }));

  const apiRows: Row[] = apiProducts.map((p) => ({
    id: p.id, sku: p.sku, name: p.name, category: p.category ?? "—", unit: p.unit, packSize: String(p.pack_size),
    balance: isGatewayMode ? (productBalanceMap.get(p.id) ?? 0) : 0,
    batchTracking: p.batch_tracking ?? false, isNew: !isGatewayMode, isActive: true, is_discontinued: p.is_discontinued ?? false,
    is_controlled: p.is_controlled ?? false,
    image_url: p.image_url ?? null,
    editData: {
      sku: p.sku, name: p.name, short_name: p.short_name, description: p.description,
      category: p.category, type_code: p.type_code, brand: p.brand, unit: p.unit,
      packaging_type: p.packaging_type, units_per_package: p.units_per_package,
      reorder_point: p.reorder_point, unit_price: p.unit_price, currency: p.currency,
      batch_tracking: p.batch_tracking ?? false, expiry_tracking: p.expiry_tracking ?? false,
      dispatch_strategy: p.dispatch_strategy ?? null,
    },
  }));

  const allBase   = isGatewayMode ? apiRows : [...demoRows, ...apiRows];

  // TA/SA may edit any product; other roles may only edit products that have
  // no active Design-B approval override configured.
  const canEditProduct = (row: Row): boolean =>
    canEditProducts && (session?.role === "TA" || session?.role === "SA" || !row.is_controlled);

  // Discontinue/reactivate share the same controlled-product gate as Edit (CLAUDE.md
  // Design-B overrides) — backend POST /{id}/discontinue and /reactivate enforce this too.
  const canDiscontinueProduct = (row: Row): boolean =>
    canDiscontinue && (session?.role === "TA" || session?.role === "SA" || !row.is_controlled);

  // Sort: active first (alphabetically), discontinued at bottom (alphabetically).
  const displayProducts = useMemo(() => {
    return [...allBase].sort((a, b) => {
      if (a.is_discontinued !== b.is_discontinued) {
        return a.is_discontinued ? 1 : -1;
      }
      return a.name.localeCompare(b.name);
    });
  }, [allBase]);

  const total = allBase.length;

  const COLS = ["table.sku","products.col_name","products.col_category","inventory.unit","products.col_pack_size","products.col_balance","products.col_batch","products.col_status","table.actions"];

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("nav.products")}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {tenantName ?? org} · {total} {t("table.skus")}
            {!isGatewayMode && tenant && apiProducts.length > 0 && (
              <span className="ml-2 text-[11px] font-bold bg-green-100 text-green-800 px-1.5 py-0.5 rounded-full">
                {apiProducts.length} {t("products.new_count_suffix")}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {isGatewayMode && (
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={showDiscontinued}
                onChange={(e) => setShowDiscontinued(e.target.checked)}
                className="cursor-pointer"
              />
              {t("product.show_discontinued")}
            </label>
          )}
          {canAdd && <AddProductPanel apiBase="/api/v1/products" />}
        </div>
      </div>

      {actionError && (
        <div className="mb-3 bg-red-50 border border-red-200 rounded px-4 py-2.5 text-sm text-red-600">
          {actionError}
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
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
              {displayProducts.length === 0 && (
                <tr>
                  <td colSpan={COLS.length} className="px-4 py-10 text-center text-sm text-gray-400">
                    {t("common.no_data")}
                  </td>
                </tr>
              )}
              {displayProducts.map((p, idx) => (
                <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"} ${p.is_discontinued ? "opacity-60" : ""}`}>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-gray-400">
                    {p.sku}
                    {p.isNew && <span className="ml-1.5 text-[10px] font-bold bg-green-100 text-green-800 px-1 py-0.5 rounded">{t("inventory.new_badge")}</span>}
                  </td>
                  <td className="px-4 py-2.5 font-semibold text-gray-800">
                    <div className="flex items-center gap-2">
                      <ProductImage image_url={p.image_url} product_name={p.name} size="sm" />
                      <div>
                        <ProductLabel name={p.name} isControlled={p.is_controlled} />
                        {p.is_discontinued && (
                          <span className="ml-1.5 text-[10px] font-bold bg-gray-200 text-gray-500 px-1 py-0.5 rounded">
                            {t("product.discontinued_badge")}
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-gray-500">{p.category}</td>
                  <td className="px-4 py-2.5 text-gray-500">{p.unit}</td>
                  <td className="px-4 py-2.5 text-gray-500">{p.packSize}</td>
                  <td className={`px-4 py-2.5 text-right font-bold ${p.balance > 0 ? "text-gray-900" : "text-gray-400"}`}>
                    {p.balance > 0 ? formatQty(p.balance) : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${p.batchTracking ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-500"}`}>
                      {p.batchTracking ? t("dispatch.yes") : t("dispatch.no")}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${p.isActive && !p.is_discontinued ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-500"}`}>
                      {p.is_discontinued ? t("product.discontinued") : p.isActive ? t("products.status_active") : t("products.status_inactive")}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {isGatewayMode && canEditProducts && (
                      canEditProduct(p) ? (
                        <button
                          onClick={() => setEditingProduct(p)}
                          {...writeGp}
                          className="text-xs cursor-pointer border-0 bg-transparent underline text-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {t("product.edit")}
                        </button>
                      ) : (
                        <span
                          title={t("product.controlled_tooltip")}
                          className="text-xs text-gray-300 cursor-not-allowed"
                        >
                          {t("product.edit")}
                        </span>
                      )
                    )}
                    {canDiscontinue && isGatewayMode && (
                      canDiscontinueProduct(p) ? (
                        <button
                          onClick={() => void handleDiscontinue(p.id, p.is_discontinued ?? false)}
                          {...writeGp}
                          className={`ml-2 text-xs cursor-pointer border-0 bg-transparent underline disabled:opacity-40 disabled:cursor-not-allowed ${p.is_discontinued ? "text-emerald-600" : "text-red-500"}`}
                        >
                          {p.is_discontinued ? t("product.reactivate") : t("product.discontinue")}
                        </button>
                      ) : (
                        <span
                          title={t("product.controlled_tooltip")}
                          className="ml-2 text-xs text-gray-300 cursor-not-allowed"
                        >
                          {p.is_discontinued ? t("product.reactivate") : t("product.discontinue")}
                        </span>
                      )
                    )}
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

      {editingProduct && (
        <AddProductPanel
          apiBase="/api/v1/products"
          mode="edit"
          productId={editingProduct.id}
          initialData={editingProduct.editData}
          onHandBalance={editingProduct.balance}
          onClose={() => setEditingProduct(null)}
        />
      )}
    </div>
  );
}
