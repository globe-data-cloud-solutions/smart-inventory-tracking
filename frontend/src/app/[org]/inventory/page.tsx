"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG, getSession } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoProduct } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { AddProductPanel } from "@/components/features/inventory/AddProductPanel";
import { ReceiveStockPanel } from "@/components/features/inventory/ReceiveStockPanel";
import { IssueStockPanel } from "@/components/features/inventory/IssueStockPanel";
import { OpeningBalancePanel } from "@/components/features/inventory/OpeningBalancePanel";
import { BulkImportPanel } from "@/components/features/inventory/BulkImportPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type ApiProduct = {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; created_at: string;
  category?: string; on_hand?: number; reorder_point?: number; warehouse_id?: string | null;
};
type Filters      = { category: string[]; unit: string[]; status: string[] };
type ExpandedCell = { productId: string; productName: string; warehouseId: string; col: "received" | "issued" | "transit" };
type ModalRow     = { direction: "in" | "out" | "direct"; label: string; qty: number; date: string; ref?: string };

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
  received: { title: t("inventory.modal.received"), headerCls: "bg-emerald-600", hdBg: "bg-green-50",  totalCls: "text-emerald-600", totalLabel: t("inventory.modal.total_received") },
  issued:   { title: t("inventory.modal.issued"),   headerCls: "bg-red-600",     hdBg: "bg-red-50",    totalCls: "text-red-600",     totalLabel: t("inventory.modal.total_issued") },
  transit:  { title: t("inventory.modal.transit"),  headerCls: "bg-amber-800",   hdBg: "bg-amber-50",  totalCls: "text-amber-800",   totalLabel: t("inventory.modal.total_transit") },
};

function TransactionDetailModal({ col, productName, rows, onClose }: {
  col: "received" | "issued" | "transit";
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
                    {col === "transit" ? t("table.location") : col === "issued" ? t("inventory.modal.dest_type") : t("inventory.modal.source")}
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
function ExpandCell({ qty, cls, prefix, icon, onClick }: {
  qty: number; cls: string; prefix?: string; icon?: string; onClick: () => void;
}) {
  if (qty <= 0) return <span className="text-gray-200">—</span>;
  return (
    <button onClick={onClick} title={t("inventory.expand_hint")}
      className={`font-bold text-xs px-2.5 py-0.5 rounded border cursor-pointer inline-flex items-center gap-1 ${cls}`}>
      {icon && <span>{icon}</span>}
      {prefix}{qty.toLocaleString()}
    </button>
  );
}

/* ── Main page ───────────────────────────────────────────────────────────────── */
export default function InventoryPage() {
  const { org }       = useParams() as { org: string };
  const user          = getSession();
  const canAddProduct = usePermission("product:create");
  const store         = useInventoryStore();

  const {
    getOnHand, getAvailable,
    getReceivedTotal, getIssuedTotal, getInTransitTotal,
    getReceiveAdjs, getIssueAdjs,
    getOutboundReserved, getOutboundInTransit,
    getInboundInTransit, getInboundJustReceived, getInboundPartial,
  } = store;

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);

  const [selectedWH, setSelectedWH] = useState<string>(user?.warehouseId ?? "");
  const whId = selectedWH || user?.warehouseId || "";
  const [filters, setFilters] = useState<Filters>({ category: [], unit: [], status: [] });
  const [expandedCell, setExpandedCell] = useState<ExpandedCell | null>(null);

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!tenant && !!user && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  if (!user || org === SA_ORG_SLUG)
    return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;
  if (!tenant)
    return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const userWarehouse = tenant.warehouses.find((w) => w.id === user.warehouseId);
  const isMWH = userWarehouse?.type === "MWH" || ["TA", "SA"].includes(user.role);

  const tenantProductIds = new Set(tenant.products.map((p) => p.id));
  const mergedProducts: DemoProduct[] = [
    ...tenant.products,
    ...apiProducts.filter((p) => !tenantProductIds.has(p.id)).map((p) => ({
      id:           p.id, sku: p.sku, name: p.name,
      category:     p.category ?? p.type_code, unit: p.unit,
      batchTracking: false, reorderPoint: p.reorder_point ?? 0,
      stock: (p.on_hand && p.warehouse_id) ? { [p.warehouse_id]: p.on_hand } as Record<string, number> : {} as Record<string, number>,
    })),
  ];

  let modalRows: ModalRow[] = [];
  if (expandedCell) {
    const { productId, warehouseId, col } = expandedCell;
    if (col === "received") {
      modalRows = [
        ...getReceiveAdjs(productId, warehouseId).map((a) => ({ direction: "direct" as const, label: t("inventory.modal.direct_receive"), qty: a.qty, date: a.createdAt })),
        ...getInboundJustReceived(productId, warehouseId).map((txn) => ({ direction: "in" as const, label: txn.fromWarehouseName, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref })),
      ].sort((a, b) => a.date.localeCompare(b.date));
    } else if (col === "issued") {
      modalRows = [
        ...getIssueAdjs(productId, warehouseId).map((a) => ({ direction: "out" as const, label: t("inventory.modal.issued_out"), qty: a.qty, date: a.createdAt })),
        ...getOutboundReserved(productId, warehouseId).map((txn) => ({ direction: "out" as const, label: `To: ${txn.toWarehouseName}`, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref })),
      ].sort((a, b) => a.date.localeCompare(b.date));
    } else {
      const inbound  = getInboundInTransit(productId, warehouseId).map((txn) => ({ direction: "in"  as const, label: `From: ${txn.fromWarehouseName}`, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref }));
      const partial  = getInboundPartial(productId, warehouseId).map((txn) => {
        const rcvd = txn.receivedQuantity ?? 0; const rem = txn.quantity - rcvd;
        return { direction: "in" as const, label: `From: ${txn.fromWarehouseName} (partial — ${rcvd.toLocaleString()} of ${txn.quantity.toLocaleString()} received, ${rem.toLocaleString()} remaining)`, qty: rem, date: txn.issuedDate, ref: txn.ref };
      });
      const outbound = getOutboundInTransit(productId, warehouseId).map((txn) => ({ direction: "out" as const, label: `To: ${txn.toWarehouseName}`, qty: txn.quantity, date: txn.issuedDate, ref: txn.ref }));
      modalRows = [...inbound, ...partial, ...outbound].sort((a, b) => a.date.localeCompare(b.date));
    }
  }

  const allProducts = whId
    ? mergedProducts.filter((p) => { const base = p.stock[whId] ?? 0; return getOnHand(p.id, whId, base) > 0 || getInTransitTotal(p.id, whId) > 0; })
    : mergedProducts;

  const mainTableIds = new Set(allProducts.map((p) => p.id));
  const zeroStockNewProducts = apiProducts.filter((p) => !tenantProductIds.has(p.id) && !mainTableIds.has(p.id));

  const categoryOptions = Array.from(new Set(allProducts.map((p) => p.category)));
  const unitOptions     = Array.from(new Set(allProducts.map((p) => p.unit)));
  const statusOptions   = [t("dashboard.in_stock"), t("alerts.low_stock")];

  function rowMatchesFilters(p: DemoProduct): boolean {
    const base = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((a, b) => a + b, 0);
    const available = whId ? getAvailable(p.id, whId, base) : base;
    const status = available < p.reorderPoint ? t("alerts.low_stock") : t("dashboard.in_stock");
    if (filters.category.length > 0 && !filters.category.includes(p.category)) return false;
    if (filters.unit.length     > 0 && !filters.unit.includes(p.unit))         return false;
    if (filters.status.length   > 0 && !filters.status.includes(status))       return false;
    return true;
  }

  const visibleProducts = allProducts.filter(rowMatchesFilters);
  const totalStockAll   = visibleProducts.reduce((a, p) => {
    const base = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((x, y) => x + y, 0);
    return a + (whId ? getOnHand(p.id, whId, base) : base);
  }, 0);
  const activeFiltersCount = Object.values(filters).filter(
    (f) => f.length > 0 && f.length < (f === filters.category ? categoryOptions.length : f === filters.unit ? unitOptions.length : 2)
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
            {tenant.name} · {whId ? (tenant.warehouses.find((w) => w.id === whId)?.name ?? t("inventory.warehouse")) : t("inventory.all_locations")} · {visibleProducts.length} {t("table.skus")}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {isMWH && <OpeningBalancePanel products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />}
          {isMWH && <BulkImportPanel     products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />}
          <ReceiveStockPanel products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />
          <IssueStockPanel   products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />
          {canAddProduct && (
            <AddProductPanel
              apiBase="/api/v1/products"
              categories={Array.from(new Set(mergedProducts.map((p) => p.category).filter(Boolean)))}
            />
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
              {tenant.warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}

        {activeFiltersCount > 0 && (
          <div className="flex gap-1.5 flex-wrap items-center">
            {(["category", "unit", "status"] as (keyof Filters)[]).map((field) =>
              filters[field].length > 0 && filters[field].length < (field === "category" ? categoryOptions.length : field === "unit" ? unitOptions.length : 2) ? (
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
        {/* uses --tenant-color from [org]/layout.tsx */}
        <div className="h-[3px] bg-[var(--tenant-color)]" />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                <PlainHeader label={t("table.sku")} />
                <PlainHeader label={t("table.product")} />
                <FilterHeader label={t("inventory.category")} field="category" options={categoryOptions} filters={filters} setFilters={setFilters} />
                <FilterHeader label={t("inventory.unit")}     field="unit"     options={unitOptions}     filters={filters} setFilters={setFilters} />
                <PlainHeader label={whId ? t("inventory.on_hand") : t("dashboard.stat_units")} align="right" />
                {showWarehouseColumns && <PlainHeader label={t("inventory.received")}   align="right" />}
                {showWarehouseColumns && <PlainHeader label={t("inventory.issued")}     align="right" />}
                {showWarehouseColumns && <PlainHeader label={t("inventory.in_transit")} align="right" />}
                {showWarehouseColumns && <PlainHeader label={t("inventory.available")}  align="right" />}
                <PlainHeader label={t("table.reorder_point")} align="right" />
                <FilterHeader label={t("table.status")} field="status" options={statusOptions} filters={filters} setFilters={setFilters} />
              </tr>
            </thead>
            <tbody>
              {visibleProducts.map((p, idx) => {
                const base      = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((a, b) => a + b, 0);
                const onHand    = whId ? getOnHand(p.id, whId, base)    : base;
                const received  = whId ? getReceivedTotal(p.id, whId)  : 0;
                const issued    = whId ? getIssuedTotal(p.id, whId)    : 0;
                const inTransit = whId ? getInTransitTotal(p.id, whId) : 0;
                const available = whId ? getAvailable(p.id, whId, base) : base;
                const isLow     = available < p.reorderPoint;

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
                        <ExpandCell qty={received} cls="text-emerald-600 bg-green-50 border-emerald-200" prefix="+"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "received" })} />
                      </td>
                    )}
                    {showWarehouseColumns && (
                      <td className="px-3.5 py-2.5 text-right">
                        <ExpandCell qty={issued} cls="text-red-600 bg-red-50 border-red-200" prefix="−"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "issued" })} />
                      </td>
                    )}
                    {showWarehouseColumns && (
                      <td className="px-3.5 py-2.5 text-right">
                        <ExpandCell qty={inTransit} cls="text-amber-800 bg-amber-50 border-amber-200" icon="⏳"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "transit" })} />
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
                      <span className={`inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-0.5 rounded border ${isLow ? "bg-red-50 text-red-600 border-red-200" : "bg-green-50 text-emerald-600 border-emerald-200"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${isLow ? "bg-red-600" : "bg-emerald-600"}`} />
                        {isLow ? t("alerts.low_stock") : t("dashboard.in_stock")}
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
                  <td className="px-3.5 py-2.5 text-xs"><span className="bg-gray-100 px-2 py-0.5 rounded font-semibold text-gray-700">{p.type_code}</span></td>
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
          <strong className="text-emerald-600">{t("inventory.received")}</strong> — {t("inventory.legend.received")} ·{" "}
          <strong className="text-red-600">{t("inventory.issued")}</strong> — {t("inventory.legend.issued")} ·{" "}
          <strong className="text-amber-800">{t("inventory.in_transit")} ⏳</strong> — {t("inventory.legend.transit")} ·{" "}
          <strong className="text-blue-700">{t("inventory.available")}</strong> — {t("inventory.legend.available")}
        </p>
      )}
    </div>
  );
}
