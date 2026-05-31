"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG, getSession } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoProduct, type DemoWarehouse, type WarehouseType } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { AddProductPanel } from "@/components/features/inventory/AddProductPanel";
import { ReceiveStockPanel } from "@/components/features/inventory/ReceiveStockPanel";
import { IssueStockPanel } from "@/components/features/inventory/IssueStockPanel";
import { OpeningBalancePanel } from "@/components/features/inventory/OpeningBalancePanel";
import { BulkImportPanel } from "@/components/features/inventory/BulkImportPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useWarehouses } from "@/hooks/useWarehouses";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";

type ApiTransfer = {
  id: string; ref: string; product_id: string; product_name: string;
  from_warehouse_id: string; from_warehouse_name: string;
  to_warehouse_id: string; to_warehouse_name: string;
  quantity: number; status: string; created_at: string;
};

type ApiProduct = {
  id: string; sku: string; name: string; unit: string; pack_size: number;
  reorder_point?: number | null; category?: string | null;
  short_name?: string | null; description?: string | null;
  brand?: string | null; type_code?: string | null;
  packaging_type?: string | null; units_per_package?: number | null;
};

type InventoryStockItem = {
  product_id: string; product_name: string; product_sku: string;
  warehouse_id: string; warehouse_name: string; warehouse_type: string;
  current_stock: string; pending_out_qty: string;
  in_transit_out_qty: string; in_transit_in_qty: string;
  requested_qty: string; net_available: string;
};
type Filters      = { category: string[]; unit: string[]; status: string[] };
type ExpandedCell = { productId: string; productName: string; warehouseId: string; col: "reserved" | "inTransitOut" | "inTransitIn" };
type ModalRow     = { direction: "in" | "out" | "direct"; label: string; qty: number; date: string; ref?: string };

// GATEWAY MODE: use API values ONLY for all balance columns.
// NEVER mix Zustand store calculations with API balance values —
// they represent different data sources and will produce inconsistent totals.
// Use safeFloat() for every API numeric field; null/undefined → 0, not NaN.

// Null-safe float parser. parseFloat(null|undefined) returns NaN; this returns 0.
// Use for every balance field from the API — field may be absent in stale cached responses.
function safeFloat(val: unknown): number {
  const n = parseFloat(String(val ?? 0));
  return isNaN(n) ? 0 : n;
}

/* ── Column filter dropdown ─────────────────────────────────────────────────── */
function FilterDropdown({ options, selected, onChange, onClose }: {
  options: string[]; selected: string[];
  onChange: (v: string[]) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);
  const allSelected = selected.length === 0 || selected.length === options.length;
  function toggle(val: string) {
    if (selected.includes(val)) onChange(selected.filter((s) => s !== val));
    else onChange([...selected, val]);
  }
  return (
    <div ref={ref} className="absolute top-full left-0 z-50 mt-1 bg-white border border-gray-200 rounded-md shadow-xl min-w-[160px] py-1.5">
      <label className="flex items-center gap-2 px-3 py-1.5 cursor-pointer text-xs text-gray-700 border-b border-gray-100">
        <input type="checkbox" checked={allSelected} onChange={() => onChange(allSelected ? [] : [...options])} className="cursor-pointer" />
        <span className="font-semibold">{t("common.filter")} All</span>
      </label>
      {options.map((opt) => (
        <label key={opt} className="flex items-center gap-2 px-3 py-1.5 cursor-pointer text-xs text-gray-700 hover:bg-gray-50">
          <input type="checkbox" checked={selected.length === 0 || selected.includes(opt)} onChange={() => toggle(opt)} className="cursor-pointer" />
          {opt}
        </label>
      ))}
    </div>
  );
}

function FilterHeader({ label, field, options, filters, setFilters, align = "left" }: {
  label: string; field: keyof Filters; options: string[];
  filters: Filters; setFilters: (f: Filters) => void; align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const active = filters[field].length > 0 && filters[field].length < options.length;
  return (
    <th className={`px-3.5 py-2.5 text-${align} text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap relative select-none`}>
      <div className="inline-flex items-center gap-1 cursor-pointer" onClick={() => setOpen((o) => !o)}>
        <span className={active ? "text-eth-forest" : "text-gray-500"}>{label}</span>
        <span className={`text-[9px] font-black rounded px-1 ${active ? "bg-green-100 text-eth-forest" : "text-gray-400"}`}>
          {active ? `${filters[field].length}✓` : "▾"}
        </span>
      </div>
      {open && (
        <FilterDropdown options={options} selected={filters[field]}
          onChange={(v) => setFilters({ ...filters, [field]: v })}
          onClose={() => setOpen(false)} />
      )}
    </th>
  );
}

function PlainHeader({ label, align = "left" }: { label: string; align?: "left" | "right" }) {
  return (
    <th className={`px-3.5 py-2.5 text-${align} text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap`}>
      {label}
    </th>
  );
}

/* ── Transaction detail modal ───────────────────────────────────────────────── */
const COL_META = {
  reserved:    { title: t("inventory.modal.reserved"),      headerCls: "bg-amber-600",  hdBg: "bg-amber-50",  totalCls: "text-amber-700",  totalLabel: t("inventory.modal.total_reserved") },
  inTransitOut:{ title: t("inventory.modal.in_transit_out"), headerCls: "bg-red-600",    hdBg: "bg-red-50",    totalCls: "text-red-600",    totalLabel: t("inventory.modal.total_in_transit_out") },
  inTransitIn: { title: t("inventory.modal.in_transit_in"),  headerCls: "bg-blue-600",   hdBg: "bg-blue-50",   totalCls: "text-blue-600",   totalLabel: t("inventory.modal.total_in_transit_in") },
};

function TransactionDetailModal({ col, productName, rows, onClose }: {
  col: "reserved" | "inTransitOut" | "inTransitIn";
  productName: string;
  rows: ModalRow[];
  onClose: () => void;
}) {
  const meta  = COL_META[col];
  const total = rows.reduce((s, r) => s + r.qty, 0);

  function arrow(dir: ModalRow["direction"]) {
    if (dir === "in")  return <span className="text-emerald-600 font-black text-base">←</span>;
    if (dir === "out") return <span className="text-red-600    font-black text-base">→</span>;
    return <span className="text-emerald-600 font-black text-base">+</span>;
  }

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 bg-black/40 z-[200]" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg z-[201] w-[520px] shadow-2xl overflow-hidden">
        <div className={`px-5 py-4 ${meta.headerCls} flex items-center justify-between`}>
          <div>
            <p className="font-bold text-[15px] text-white m-0">{meta.title}</p>
            <p className="text-xs text-white/80 mt-0.5">{productName}</p>
          </div>
          <button onClick={onClose} className="bg-white/15 border-0 cursor-pointer text-white text-base w-7 h-7 rounded flex items-center justify-center">✕</button>
        </div>
        <div className="p-3 max-h-[400px] overflow-y-auto">
          {rows.length === 0 ? (
            <p className="text-center text-gray-400 text-sm py-6">{t("common.no_data")}</p>
          ) : (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className={`${meta.hdBg} border-b-2 border-gray-200`}>
                  <th className="w-6 px-2.5 py-1.5" />
                  <th className="px-2.5 py-1.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide">
                    {col === "inTransitIn" ? t("table.location") : col === "reserved" ? t("inventory.modal.dest_type") : t("table.location")}
                  </th>
                  <th className="px-2.5 py-1.5 text-right text-[11px] font-bold text-gray-500 uppercase tracking-wide">{t("lots.quantity")}</th>
                  <th className="px-2.5 py-1.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide">{t("common.date")}</th>
                  <th className="px-2.5 py-1.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide">Ref</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={`border-b border-gray-100 ${i % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-2.5 py-2 text-center">{arrow(r.direction)}</td>
                    <td className="px-2.5 py-2 font-semibold text-gray-800">{r.label}</td>
                    <td className={`px-2.5 py-2 text-right font-bold ${r.direction === "in" || r.direction === "direct" ? "text-emerald-600" : "text-red-600"}`}>
                      {r.direction === "out" ? `−${r.qty.toLocaleString()}` : `+${r.qty.toLocaleString()}`}
                    </td>
                    <td className="px-2.5 py-2 text-gray-500 text-xs">
                      {new Date(r.date).toLocaleDateString()} {new Date(r.date).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="px-2.5 py-2 font-mono text-[11px] text-gray-400">{r.ref ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className={`${meta.hdBg} border-t-2 border-gray-200`}>
                  <td colSpan={2} className="px-2.5 py-2 font-bold text-gray-700 text-xs">{meta.totalLabel}</td>
                  <td className={`px-2.5 py-2 text-right font-extrabold ${meta.totalCls}`}>{total.toLocaleString()}</td>
                  <td colSpan={2} />
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

/* ── Expandable cell button ─────────────────────────────────────────────────── */
function ExpandCell({ qty, cls, prefix, icon, tooltip, onClick }: {
  qty: number; cls: string; prefix?: string; icon?: string; tooltip?: string; onClick: () => void;
}) {
  if (qty <= 0) return <span className="text-gray-200">—</span>;
  return (
    <button onClick={onClick} title={tooltip ?? t("inventory.expand_hint")}
      className={`font-bold text-xs px-2.5 py-0.5 rounded border cursor-pointer inline-flex items-center gap-1 ${cls}`}>
      {icon && <span>{icon}</span>}
      {prefix}{qty.toLocaleString()}
    </button>
  );
}

/* ── Main page ───────────────────────────────────────────────────────────────── */
export default function InventoryPage() {
  const { org }       = useParams() as { org: string };
  const tenantName    = useTenantName(org);
  const user          = getSession();
  const canAddProduct = usePermission("product:create");
  // Subscribe to the specific maps that addIssue/addReceive mutate.
  // Each call spreads a new object reference into issues/receives, which guarantees
  // Zustand fires these selectors and triggers a re-render without a page reload.
  const issues         = useInventoryStore((s) => s.issues);
  const receives       = useInventoryStore((s) => s.receives);
  const storeTransfers = useInventoryStore((s) => s.transfers);
  const {
    getOnHand, getAvailable,
    getReservedTotal, getInTransitOutTotal, getInTransitInTotal,
    getOutboundReserved, getOutboundInTransit,
    getInboundInTransit, getInboundPartial,
    addTransfer, getTransferEntry, updateTransferStatus,
  } = useInventoryStore();

  const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  const { warehouses: orgNodeWarehouses } = useWarehouses();

  const [selectedWH, setSelectedWH] = useState<string>(user?.warehouseId ?? "");
  const whId = selectedWH || user?.warehouseId || "";
  const [filters, setFilters] = useState<Filters>({ category: [], unit: [], status: [] });
  const [expandedCell, setExpandedCell] = useState<ExpandedCell | null>(null);

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!user && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  // Fetch active transfers so the balance columns reflect in-transit state for
  // transfers the current user hasn't personally created or transitioned this session.
  const { data: apiTransfers = [] } = useQuery<ApiTransfer[]>({
    queryKey: ["transfers", org],
    queryFn:  () => api.get<ApiTransfer[]>("/api/v1/inventory/transfers"),
    enabled:  !!user && org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 15000,
  });

  const { data: inventoryStock = [] } = useQuery<InventoryStockItem[]>({
    queryKey: ["inventory-stock", org],
    queryFn:  () => api.get<InventoryStockItem[]>("/api/v1/inventory/analytics/stock"),
    enabled:  isGatewayMode && !!user && org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 30000,
  });

  const stockByKey = useMemo(() => {
    const map = new Map<string, InventoryStockItem>();
    for (const item of inventoryStock) {
      map.set(`${item.product_id}:${item.warehouse_id}`, item);
    }
    return map;
  }, [inventoryStock]);

  const gatewayWarehouses = useMemo((): DemoWarehouse[] => {
    const seen = new Map<string, DemoWarehouse>();
    for (const item of inventoryStock) {
      if (!seen.has(item.warehouse_id)) {
        seen.set(item.warehouse_id, {
          id: item.warehouse_id, name: item.warehouse_name,
          type: (item.warehouse_type as WarehouseType) ?? "WH",
          parentId: null,
        });
      }
    }
    return Array.from(seen.values());
  }, [inventoryStock]);

  // Re-sync selectedWH once any warehouse list has loaded.
  // Org node warehouses (from useWarehouses) are preferred because they exist even
  // before any stock has been received. Analytics-based list is the fallback.
  const effectiveWhList = isGatewayMode
    ? (orgNodeWarehouses.length > 0 ? orgNodeWarehouses : gatewayWarehouses)
    : [];
  useEffect(() => {
    if (!isGatewayMode || effectiveWhList.length === 0) return;
    const realWhId = getSession()?.warehouseId;
    if (realWhId && effectiveWhList.some((w) => w.id === realWhId)) {
      setSelectedWH((prev) => (prev === realWhId ? prev : realWhId));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveWhList.length]);

  const syncedRef = useRef(new Set<string>());
  useEffect(() => {
    const TERMINAL = new Set(["COMPLETED", "CANCELLED", "REJECTED"]);
    for (const t of apiTransfers) {
      if (!t.product_id) continue;
      const apiStatus = t.status as import("@/lib/inventory-state").TransferStatus;
      const existing  = getTransferEntry(t.id);
      if (existing) {
        // BUG B+C fix: propagate status changes from the API into Zustand so that
        // in-transit and cleared columns reflect the latest state even when the
        // transition was performed in a different page/tab.
        if (existing.status !== apiStatus) {
          updateTransferStatus(t.id, apiStatus);
        }
        continue;
      }
      if (TERMINAL.has(t.status))      continue;
      if (syncedRef.current.has(t.id)) continue;
      syncedRef.current.add(t.id);
      // Resolve names: API JOIN may return null when warehouse only exists in
      // organization_node. Fall back to displayWarehouses lookup, then raw UUID.
      const resolveWHName = (id: string, name: string | null | undefined) =>
        name || displayWarehouses.find((w) => w.id === id)?.name || id;
      addTransfer({
        id:                t.id,
        ref:               t.ref,
        productId:         t.product_id,
        fromWarehouseId:   t.from_warehouse_id,
        fromWarehouseName: resolveWHName(t.from_warehouse_id, t.from_warehouse_name),
        toWarehouseId:     t.to_warehouse_id,
        toWarehouseName:   resolveWHName(t.to_warehouse_id, t.to_warehouse_name),
        quantity:          t.quantity,
        issuedDate:        t.created_at,
        status:            apiStatus,
      });
    }
  }, [apiTransfers, addTransfer, getTransferEntry, updateTransferStatus]);

  if (org === SA_ORG_SLUG)
    return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  if (!user || (!tenant && !isGatewayMode))
    return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const userWarehouse = tenant?.warehouses?.find((w) => w.id === user.warehouseId);
  const isMWH = isGatewayMode
    ? ["TA", "SA", "NM", "LM", "RM"].includes(user.role)
    : (userWarehouse?.type === "MWH" || ["TA", "SA"].includes(user.role));

  // In gateway mode: org node warehouses are the source of truth (exist before any stock).
  // Falls back to analytics-derived list if org nodes haven't loaded yet.
  // In BFF/demo mode: use demo tenant warehouses.
  const displayWarehouses: DemoWarehouse[] = isGatewayMode
    ? (orgNodeWarehouses.length > 0 ? orgNodeWarehouses : gatewayWarehouses)
    : (tenant?.warehouses ?? []);

  const tenantProductIds = new Set((tenant?.products ?? []).map((p) => p.id));
  const mergedProducts: DemoProduct[] = isGatewayMode
    ? apiProducts.map((p) => ({
        id: p.id, sku: p.sku, name: p.name,
        category: p.category ?? "—",
        unit: p.unit,
        batchTracking: false,
        reorderPoint: p.reorder_point != null ? safeFloat(p.reorder_point) : 0,
        stock: {} as Record<string, number>,
        shortName: p.short_name ?? undefined,
        description: p.description ?? undefined,
        brand: p.brand ?? undefined,
        typeCode: p.type_code ?? undefined,
        packagingType: p.packaging_type ?? undefined,
        unitsPerPackage: p.units_per_package ?? undefined,
      }))
    : [
        ...(tenant?.products ?? []),
        ...apiProducts.filter((p) => !tenantProductIds.has(p.id)).map((p) => ({
          id: p.id, sku: p.sku, name: p.name,
          category: p.category ?? "—",
          unit: p.unit,
          batchTracking: false,
          reorderPoint: p.reorder_point != null ? safeFloat(p.reorder_point) : 0,
          stock: {} as Record<string, number>,
        })),
      ];

  // Single source of truth for API stock in gateway mode.
  // Returns null in demo mode (isGatewayMode=false) or when the product has no
  // stock row for the currently-selected warehouse — callers fall back to Zustand
  // or demo seed values respectively.
  const getStock = (productId: string): InventoryStockItem | null => {
    if (!isGatewayMode || !whId) return null;
    return stockByKey.get(`${productId}:${whId}`) ?? null;
  };

  // Effective on-hand: use real API balance in gateway mode, Zustand-adjusted demo balance in BFF mode.
  function effectiveOnHand(productId: string, warehouseId: string, demoBase: number): number {
    if (isGatewayMode) {
      if (warehouseId) {
        return safeFloat(stockByKey.get(`${productId}:${warehouseId}`)?.current_stock);
      }
      return Array.from(stockByKey.entries())
        .filter(([k]) => k.startsWith(`${productId}:`))
        .reduce((sum, [, item]) => sum + safeFloat(item.current_stock), 0);
    }
    return warehouseId ? getOnHand(productId, warehouseId, demoBase) : demoBase;
  }

  let modalRows: ModalRow[] = [];
  if (expandedCell) {
    const { productId, warehouseId, col } = expandedCell;
    if (col === "reserved") {
      modalRows = getOutboundReserved(productId, warehouseId)
        .map((txn) => ({ direction: "out" as const, label: `To: ${txn.toWarehouseName}`, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref }))
        .sort((a, b) => a.date.localeCompare(b.date));
    } else if (col === "inTransitOut") {
      modalRows = getOutboundInTransit(productId, warehouseId)
        .map((txn) => ({ direction: "out" as const, label: `To: ${txn.toWarehouseName}`, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref }))
        .sort((a, b) => a.date.localeCompare(b.date));
    } else {
      const inbound = getInboundInTransit(productId, warehouseId).map((txn) => ({ direction: "in" as const, label: `From: ${txn.fromWarehouseName}`, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref }));
      const partial = getInboundPartial(productId, warehouseId).map((txn) => {
        const rcvd = txn.receivedQuantity ?? 0; const rem = txn.quantity - rcvd;
        return { direction: "in" as const, label: `From: ${txn.fromWarehouseName} (partial — ${rcvd.toLocaleString()} of ${txn.quantity.toLocaleString()} received, ${rem.toLocaleString()} remaining)`, qty: rem, date: txn.issuedDate, ref: txn.ref };
      });
      modalRows = [...inbound, ...partial].sort((a, b) => a.date.localeCompare(b.date));
    }
  }

  const allProducts = whId
    ? mergedProducts.filter((p) => {
        if (isGatewayMode) {
          // Show ALL products per CLAUDE.md §27 — zero-balance items get Out of Stock badge
          // and sort to the bottom. Filtering by stockByKey would hide products whose balance
          // dropped to zero after being issued, violating the rule.
          return true;
        }
        const base = p.stock[whId] ?? 0;
        return (whId in p.stock) ||
               getOnHand(p.id, whId, base) > 0 ||
               getReservedTotal(p.id, whId) > 0 ||
               getInTransitOutTotal(p.id, whId) > 0 ||
               getInTransitInTotal(p.id, whId) > 0 ||
               (issues[`${org}:${whId}:${p.id}`] ?? 0) > 0 ||
               (receives[`${org}:${whId}:${p.id}`] ?? 0) > 0;
      })
    : mergedProducts;

  const mainTableIds = new Set(allProducts.map((p) => p.id));
  // In gateway mode: all products come from the API — no separate "zero stock new" section.
  const zeroStockNewProducts = isGatewayMode
    ? []
    : apiProducts.filter((p) => !tenantProductIds.has(p.id) && !mainTableIds.has(p.id));

  const categoryOptions = Array.from(new Set(allProducts.map((p) => p.category)));
  const unitOptions     = Array.from(new Set(allProducts.map((p) => p.unit)));
  const statusOptions   = [t("dashboard.in_stock"), t("alerts.low_stock"), t("inventory.no_stock")];

  function rowMatchesFilters(p: DemoProduct): boolean {
    const demoBase = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((a, b) => a + b, 0);
    const onHand   = effectiveOnHand(p.id, whId, demoBase);
    const status   = onHand === 0
      ? t("inventory.no_stock")
      : onHand <= p.reorderPoint
        ? t("alerts.low_stock")
        : t("dashboard.in_stock");
    if (filters.category.length > 0 && !filters.category.includes(p.category)) return false;
    if (filters.unit.length     > 0 && !filters.unit.includes(p.unit))         return false;
    if (filters.status.length   > 0 && !filters.status.includes(status))       return false;
    return true;
  }

  // Out of Stock products sort to the bottom; In Stock and Low Stock keep their relative order.
  const visibleProducts = allProducts
    .filter(rowMatchesFilters)
    .sort((a, b) => {
      const aDemoBase = whId ? (a.stock[whId] ?? 0) : Object.values(a.stock).reduce((x, y) => x + y, 0);
      const bDemoBase = whId ? (b.stock[whId] ?? 0) : Object.values(b.stock).reduce((x, y) => x + y, 0);
      const aOnHand   = effectiveOnHand(a.id, whId, aDemoBase);
      const bOnHand   = effectiveOnHand(b.id, whId, bDemoBase);
      if (aOnHand === 0 && bOnHand !== 0) return 1;
      if (bOnHand === 0 && aOnHand !== 0) return -1;
      return 0;
    });
  const totalStockAll = visibleProducts.reduce((acc, p) => {
    const demoBase = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((x, y) => x + y, 0);
    return acc + effectiveOnHand(p.id, whId, demoBase);
  }, 0);
  const activeFiltersCount = Object.values(filters).filter(
    (f) => f.length > 0 && f.length < (f === filters.category ? categoryOptions.length : f === filters.unit ? unitOptions.length : statusOptions.length)
  ).length;
  const showWarehouseColumns = !!whId;

  return (
    <div className="p-8">
      {expandedCell && (
        <TransactionDetailModal col={expandedCell.col} productName={expandedCell.productName} rows={modalRows} onClose={() => setExpandedCell(null)} />
      )}

      {/* Header */}
      <div className="mb-5 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("nav.inventory")}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {tenantName ?? org} · {whId ? (displayWarehouses.find((w) => w.id === whId)?.name ?? t("inventory.warehouse")) : t("inventory.all_locations")} · {visibleProducts.length} {t("table.skus")}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {isMWH && <OpeningBalancePanel products={mergedProducts} warehouses={displayWarehouses} orgSlug={org} />}
          {isMWH && <BulkImportPanel     products={mergedProducts} warehouses={displayWarehouses} orgSlug={org} />}
          <ReceiveStockPanel products={mergedProducts} orgSlug={org} />
          <IssueStockPanel   products={mergedProducts} orgSlug={org} />
          {canAddProduct && (
            <AddProductPanel apiBase="/api/v1/products" />
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {!user.warehouseId && (
          <div className="flex items-center gap-2">
            <label className="text-xs font-bold text-gray-700 uppercase tracking-wide">{t("table.location")}</label>
            <select
              value={selectedWH}
              onChange={(e) => setSelectedWH(e.target.value)}
              className="px-2.5 py-1.5 text-sm border border-gray-300 rounded-md outline-none cursor-pointer"
            >
              <option value="">{t("inventory.all_locations")}</option>
              {displayWarehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}

        {activeFiltersCount > 0 && (
          <div className="flex gap-1.5 flex-wrap items-center">
            {(["category", "unit", "status"] as (keyof Filters)[]).map((field) =>
              filters[field].length > 0 && filters[field].length < (field === "category" ? categoryOptions.length : field === "unit" ? unitOptions.length : statusOptions.length) ? (
                <span key={field} className="text-[11px] font-bold bg-green-100 text-green-800 px-2.5 py-0.5 rounded-full flex items-center gap-1">
                  {field}: {filters[field].join(", ")}
                  <button onClick={() => setFilters({ ...filters, [field]: [] })} className="bg-transparent border-0 cursor-pointer text-[11px] text-green-800 p-0">✕</button>
                </span>
              ) : null
            )}
            <button onClick={() => setFilters({ category: [], unit: [], status: [] })} className="text-xs text-gray-500 bg-transparent border-0 cursor-pointer underline">
              {t("audit.clear_filters")}
            </button>
          </div>
        )}

        <div className="ml-auto text-xs text-gray-500">
          {visibleProducts.length} / {allProducts.length} {t("table.products")} · {totalStockAll.toLocaleString()} {t("inventory.total_units")}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-md overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                <PlainHeader label={t("table.sku")} />
                <PlainHeader label={t("table.product")} />
                <FilterHeader label={t("inventory.category")} field="category" options={categoryOptions} filters={filters} setFilters={setFilters} />
                <FilterHeader label={t("inventory.unit")}     field="unit"     options={unitOptions}     filters={filters} setFilters={setFilters} />
                <PlainHeader label={whId ? t("inventory.on_hand") : t("dashboard.stat_units")} align="right" />
                {showWarehouseColumns && <PlainHeader label={t("inventory.reserved")}      align="right" />}
                {showWarehouseColumns && <PlainHeader label={t("inventory.in_transit_out")} align="right" />}
                {showWarehouseColumns && <PlainHeader label={t("inventory.in_transit_in")}  align="right" />}
                {showWarehouseColumns && <PlainHeader label={t("inventory.available")}  align="right" />}
                <PlainHeader label={t("table.reorder_point")} align="right" />
                <FilterHeader label={t("table.status")} field="status" options={statusOptions} filters={filters} setFilters={setFilters} />
              </tr>
            </thead>
            <tbody>
              {visibleProducts.map((p, idx) => {
                const demoBase  = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((a, b) => a + b, 0);
                const stockItem = getStock(p.id);   // null in demo mode → Zustand fallback
                const onHand       = effectiveOnHand(p.id, whId, demoBase);
                const reserved     = whId ? (stockItem ? safeFloat(stockItem.pending_out_qty)     : getReservedTotal(p.id, whId))     : 0;
                const inTransitOut = whId ? (stockItem ? safeFloat(stockItem.in_transit_out_qty) : getInTransitOutTotal(p.id, whId)) : 0;
                const inTransitIn  = whId ? (stockItem ? safeFloat(stockItem.in_transit_in_qty)  : getInTransitInTotal(p.id, whId))  : 0;
                const available    = whId ? (stockItem ? safeFloat(stockItem.net_available)       : getAvailable(p.id, whId, demoBase)) : demoBase;
                const stockStatus  = onHand === 0 ? "out" : onHand <= p.reorderPoint ? "low" : "in";

                return (
                  <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-3.5 py-2.5 font-mono text-[11px] text-gray-400 whitespace-nowrap">{p.sku}</td>
                    <td className="px-3.5 py-2.5 font-semibold text-gray-800 whitespace-nowrap">
                      {p.name}
                      {p.batchTracking && (
                        <span className="ml-1.5 text-[10px] font-bold bg-violet-100 text-violet-800 px-1 py-0.5 rounded">BATCH</span>
                      )}
                    </td>
                    <td className="px-3.5 py-2.5 text-xs">
                      <span className="bg-gray-100 px-2 py-0.5 rounded font-semibold text-gray-700">{p.category}</span>
                    </td>
                    <td className="px-3.5 py-2.5 text-gray-400 text-xs">{p.unit}</td>
                    <td className={`px-3.5 py-2.5 text-right font-bold ${onHand > 0 ? "text-gray-900" : "text-gray-400"}`}>
                      {onHand.toLocaleString()}
                    </td>
                    {showWarehouseColumns && (
                      <td className="px-3.5 py-2.5 text-right">
                        <ExpandCell qty={reserved} cls="text-amber-700 bg-amber-50 border-amber-200" icon="⊘"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "reserved" })} />
                      </td>
                    )}
                    {showWarehouseColumns && (
                      <td className="px-3.5 py-2.5 text-right">
                        <ExpandCell qty={inTransitOut} cls="text-red-600 bg-red-50 border-red-200" icon="→"
                          tooltip={t("inventory.tooltip.in_transit_out")}
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "inTransitOut" })} />
                      </td>
                    )}
                    {showWarehouseColumns && (
                      <td className="px-3.5 py-2.5 text-right">
                        <ExpandCell qty={inTransitIn} cls="text-blue-600 bg-blue-50 border-blue-200" icon="←"
                          tooltip={t("inventory.tooltip.in_transit_in")}
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "inTransitIn" })} />
                      </td>
                    )}
                    {showWarehouseColumns && (
                      <td className="px-3.5 py-2.5 text-right font-bold">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-bold ${available > p.reorderPoint ? "bg-blue-50 text-blue-700" : "bg-red-50 text-red-600"}`}>
                          {available.toLocaleString()}
                        </span>
                      </td>
                    )}
                    <td className="px-3.5 py-2.5 text-right text-gray-400 text-xs">{p.reorderPoint.toLocaleString()}</td>
                    <td className="px-3.5 py-2.5">
                      <span className={`inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-0.5 rounded border ${
                        stockStatus === "out" ? "bg-red-50 text-red-700 border-red-200" :
                        stockStatus === "low" ? "bg-amber-50 text-amber-700 border-amber-200" :
                        "bg-green-50 text-emerald-600 border-emerald-200"
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          stockStatus === "out" ? "bg-red-600" :
                          stockStatus === "low" ? "bg-amber-600" :
                          "bg-emerald-600"
                        }`} />
                        {stockStatus === "out" ? t("inventory.no_stock") :
                         stockStatus === "low" ? t("alerts.low_stock") :
                         t("dashboard.in_stock")}
                      </span>
                    </td>
                  </tr>
                );
              })}

              {zeroStockNewProducts.map((p, idx) => (
                <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-emerald-50/30" : "bg-green-50"}`}>
                  <td className="px-3.5 py-2.5 font-mono text-[11px] text-gray-400">
                    {p.sku}
                    <span className="ml-1.5 text-[10px] font-bold bg-green-100 text-green-800 px-1 py-0.5 rounded">NEW</span>
                  </td>
                  <td className="px-3.5 py-2.5 font-semibold text-gray-800">{p.name}</td>
                  <td className="px-3.5 py-2.5 text-xs"><span className="bg-gray-100 px-2 py-0.5 rounded font-semibold text-gray-700">—</span></td>
                  <td className="px-3.5 py-2.5 text-gray-400 text-xs">{p.unit}</td>
                  <td className="px-3.5 py-2.5 text-right font-bold text-gray-400">0</td>
                  {showWarehouseColumns && <td className="px-3.5 py-2.5 text-right text-gray-200">—</td>}
                  {showWarehouseColumns && <td className="px-3.5 py-2.5 text-right text-gray-200">—</td>}
                  {showWarehouseColumns && <td className="px-3.5 py-2.5 text-right text-gray-200">—</td>}
                  {showWarehouseColumns && <td className="px-3.5 py-2.5 text-right text-gray-200">—</td>}
                  <td className="px-3.5 py-2.5 text-right text-gray-400 text-xs">—</td>
                  <td className="px-3.5 py-2.5">
                    <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-0.5 rounded border bg-yellow-50 text-yellow-800 border-yellow-200">
                      <span className="w-1.5 h-1.5 rounded-full bg-yellow-700" />
                      {t("inventory.no_stock")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {visibleProducts.length === 0 && apiProducts.length === 0 && (
            <p className="p-8 text-center text-gray-400 text-sm">
              {t("inventory.no_match")}{" "}
              <button onClick={() => setFilters({ category: [], unit: [], status: [] })} className="bg-transparent border-0 cursor-pointer text-eth-forest font-bold underline">
                {t("audit.clear_filters")}
              </button>
            </p>
          )}
        </div>
      </div>

      {showWarehouseColumns && (
        <p className="mt-3 text-xs text-gray-400">
          <strong className="text-amber-700">{t("inventory.reserved")} ⊘</strong> — {t("inventory.legend.reserved")} ·{" "}
          <strong className="text-red-600">{t("inventory.in_transit_out")} →</strong> — {t("inventory.legend.in_transit_out")} ·{" "}
          <strong className="text-blue-600">{t("inventory.in_transit_in")} ←</strong> — {t("inventory.legend.in_transit_in")} ·{" "}
          <strong className="text-blue-700">{t("inventory.available")}</strong> — {t("inventory.legend.available")}
        </p>
      )}
    </div>
  );
}
