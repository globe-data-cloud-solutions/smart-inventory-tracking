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

/* ── Types ─────────────────────────────────────────────────────────────────── */
type ApiProduct = {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; created_at: string;
};
type Filters = { category: string[]; unit: string[]; status: string[] };
type ExpandedCell = {
  productId: string;
  productName: string;
  warehouseId: string;
  col: "received" | "issued" | "transit";
};
type ModalRow = {
  direction: "in" | "out" | "direct";
  label: string;
  qty: number;
  date: string;
  ref?: string;
};

/* ── Column filter dropdown ─────────────────────────────────────────────────── */
function FilterDropdown({
  options, selected, onChange, onClose,
}: {
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
    <div ref={ref} style={{
      position: "absolute", top: "100%", left: 0, zIndex: 50, marginTop: 4,
      background: "#fff", border: "1px solid #E5E7EB", borderRadius: 6,
      boxShadow: "0 8px 24px rgba(0,0,0,0.12)", minWidth: 160, padding: "6px 0",
    }}>
      <label style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", cursor: "pointer", fontSize: 12, color: "#374151", borderBottom: "1px solid #F3F4F6" }}>
        <input type="checkbox" checked={allSelected} onChange={() => onChange(allSelected ? [] : [...options])} style={{ cursor: "pointer" }} />
        <span style={{ fontWeight: 600 }}>All</span>
      </label>
      {options.map((opt) => (
        <label key={opt} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", cursor: "pointer", fontSize: 12, color: "#374151" }}>
          <input type="checkbox" checked={selected.length === 0 || selected.includes(opt)} onChange={() => toggle(opt)} style={{ cursor: "pointer" }} />
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
    <th style={{ padding: "10px 14px", textAlign: align, fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap", position: "relative", userSelect: "none" }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        <span style={{ color: active ? "#1B4332" : "#6B7280" }}>{label}</span>
        <span style={{ fontSize: 9, color: active ? "#1B4332" : "#9CA3AF", background: active ? "#DCFCE7" : "transparent", padding: active ? "1px 4px" : "0", borderRadius: 3, fontWeight: 900 }}>
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
    <th style={{ padding: "10px 14px", textAlign: align, fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
      {label}
    </th>
  );
}

/* ── Transaction detail modal (Received / Issued / In Transit) ──────────────── */
const COL_META = {
  received: { title: "Received Details",  bg: "#059669", hdr: "#F0FDF4", totalLabel: "Total Received" },
  issued:   { title: "Issued / Reserved", bg: "#DC2626", hdr: "#FEF2F2", totalLabel: "Total Issued / Reserved" },
  transit:  { title: "In Transit Details",bg: "#92400E", hdr: "#FEF3C7", totalLabel: "Total In Transit" },
};

function TransactionDetailModal({
  col, productName, rows, onClose,
}: {
  col: "received" | "issued" | "transit";
  productName: string;
  rows: ModalRow[];
  onClose: () => void;
}) {
  const meta = COL_META[col];
  const total = rows.reduce((s, r) => s + r.qty, 0);

  function arrow(dir: ModalRow["direction"]) {
    if (dir === "in")     return <span style={{ color: "#059669", fontWeight: 900, fontSize: 14 }}>←</span>;
    if (dir === "out")    return <span style={{ color: "#DC2626", fontWeight: 900, fontSize: 14 }}>→</span>;
    return <span style={{ color: "#059669", fontWeight: 900, fontSize: 14 }}>+</span>;
  }

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 200 }} />
      <div style={{
        position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
        background: "#fff", borderRadius: 10, zIndex: 201, width: 520,
        boxShadow: "0 12px 40px rgba(0,0,0,0.2)", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: "1rem 1.25rem", background: meta.bg, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 15, color: "#fff", margin: 0 }}>{meta.title}</p>
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.8)", margin: "2px 0 0" }}>{productName}</p>
          </div>
          <button onClick={onClose} style={{ background: "rgba(255,255,255,0.15)", border: "none", cursor: "pointer", color: "#fff", fontSize: 16, width: 28, height: 28, borderRadius: 4 }}>✕</button>
        </div>

        {/* Table */}
        <div style={{ padding: "0.75rem", maxHeight: 400, overflowY: "auto" }}>
          {rows.length === 0 ? (
            <p style={{ textAlign: "center", color: "#9CA3AF", fontSize: 13, padding: "1.5rem 0" }}>No items to display.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: meta.hdr, borderBottom: "2px solid #E5E7EB" }}>
                  <th style={{ padding: "7px 10px", width: 24 }}></th>
                  <th style={{ padding: "7px 10px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    {col === "transit" ? "Warehouse" : col === "issued" ? "Destination / Type" : "Source"}
                  </th>
                  <th style={{ padding: "7px 10px", textAlign: "right", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>Qty</th>
                  <th style={{ padding: "7px 10px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>Date</th>
                  <th style={{ padding: "7px 10px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>Ref</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "8px 10px", textAlign: "center" }}>{arrow(r.direction)}</td>
                    <td style={{ padding: "8px 10px", fontWeight: 600, color: "#1F2937" }}>{r.label}</td>
                    <td style={{ padding: "8px 10px", textAlign: "right", fontWeight: 700, color: r.direction === "in" || r.direction === "direct" ? "#059669" : "#DC2626" }}>
                      {r.direction === "out" ? `−${r.qty.toLocaleString()}` : `+${r.qty.toLocaleString()}`}
                    </td>
                    <td style={{ padding: "8px 10px", color: "#6B7280", fontSize: 12 }}>
                      {new Date(r.date).toLocaleDateString()} {new Date(r.date).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{r.ref ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: meta.hdr, borderTop: "2px solid #E5E7EB" }}>
                  <td colSpan={2} style={{ padding: "8px 10px", fontWeight: 700, color: "#374151", fontSize: 12 }}>{meta.totalLabel}</td>
                  <td style={{ padding: "8px 10px", textAlign: "right", fontWeight: 800, color: meta.bg }}>{total.toLocaleString()}</td>
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
function ExpandCell({
  qty, color, bg, border, prefix, icon, onClick,
}: {
  qty: number; color: string; bg: string; border: string;
  prefix?: string; icon?: string; onClick: () => void;
}) {
  if (qty <= 0) return <span style={{ color: "#E5E7EB" }}>—</span>;
  return (
    <button
      onClick={onClick}
      title="Click to expand"
      style={{
        fontWeight: 700, fontSize: 12, color, background: bg,
        border: `1px solid ${border}`, borderRadius: 4,
        padding: "3px 10px", cursor: "pointer",
        display: "inline-flex", alignItems: "center", gap: 4,
      }}
    >
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

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);

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
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view inventory.</p>;
  if (!tenant)
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const userWarehouse = tenant.warehouses.find((w) => w.id === user.warehouseId);
  const isMWH = userWarehouse?.type === "MWH" || ["TA", "SA"].includes(user.role);

  // Merge API-created products into the DemoProduct shape so every panel's dropdown
  // includes products added via AddProductPanel this session. Static demo products
  // take precedence; API products not already in the demo catalog are appended.
  const tenantProductIds = new Set(tenant.products.map((p) => p.id));
  const mergedProducts: DemoProduct[] = [
    ...tenant.products,
    ...apiProducts
      .filter((p) => !tenantProductIds.has(p.id))
      .map((p) => ({
        id:            p.id,
        sku:           p.sku,
        name:          p.name,
        category:      p.type_code,
        unit:          p.unit,
        batchTracking: false,
        reorderPoint:  0,
        stock:         {} as Record<string, number>,
      })),
  ];

  // ── Build modal rows when a cell is expanded ──────────────────────────────
  let modalRows: ModalRow[] = [];
  if (expandedCell) {
    const { productId, warehouseId, col } = expandedCell;
    if (col === "received") {
      // Use getInboundJustReceived (RECEIVED status only) — COMPLETED transfers
      // are dropped from the column; their stock is already settled into On Hand.
      modalRows = [
        ...getReceiveAdjs(productId, warehouseId).map((a) => ({
          direction: "direct" as const, label: "Direct Receive", qty: a.qty, date: a.createdAt,
        })),
        ...getInboundJustReceived(productId, warehouseId).map((t) => ({
          direction: "in" as const, label: t.fromWarehouseName, qty: t.quantity, date: t.issuedDate, ref: t.ref,
        })),
      ].sort((a, b) => a.date.localeCompare(b.date));
    } else if (col === "issued") {
      modalRows = [
        ...getIssueAdjs(productId, warehouseId).map((a) => ({
          direction: "out" as const, label: "Issued Out", qty: a.qty, date: a.createdAt,
        })),
        ...getOutboundReserved(productId, warehouseId).map((t) => ({
          direction: "out" as const, label: `To: ${t.toWarehouseName}`, qty: t.quantity, date: t.issuedDate, ref: t.ref,
        })),
      ].sort((a, b) => a.date.localeCompare(b.date));
    } else {
      // transit — inbound full (← green), inbound partial remaining (← amber), outbound (→ red)
      const inbound = getInboundInTransit(productId, warehouseId).map((t) => ({
        direction: "in" as const, label: `From: ${t.fromWarehouseName}`, qty: t.quantity, date: t.issuedDate, ref: t.ref,
      }));
      const partial = getInboundPartial(productId, warehouseId).map((t) => {
        const rcvd = t.receivedQuantity ?? 0;
        const rem  = t.quantity - rcvd;
        return {
          direction: "in" as const,
          label: `From: ${t.fromWarehouseName} (partial — ${rcvd.toLocaleString()} of ${t.quantity.toLocaleString()} received, ${rem.toLocaleString()} remaining)`,
          qty: rem,
          date: t.issuedDate,
          ref: t.ref,
        };
      });
      const outbound = getOutboundInTransit(productId, warehouseId).map((t) => ({
        direction: "out" as const, label: `To: ${t.toWarehouseName}`, qty: t.quantity, date: t.issuedDate, ref: t.ref,
      }));
      modalRows = [...inbound, ...partial, ...outbound].sort((a, b) => a.date.localeCompare(b.date));
    }
  }

  // Products to display
  const allProducts = whId
    ? tenant.products.filter((p) => {
        const base = p.stock[whId] ?? 0;
        const onH  = getOnHand(p.id, whId, base);
        const transit = getInTransitTotal(p.id, whId);
        return onH > 0 || transit > 0;
      })
    : tenant.products;

  const categoryOptions = Array.from(new Set(allProducts.map((p) => p.category)));
  const unitOptions     = Array.from(new Set(allProducts.map((p) => p.unit)));
  const statusOptions   = ["In Stock", "Low Stock"];

  function rowMatchesFilters(p: DemoProduct): boolean {
    const base      = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((a, b) => a + b, 0);
    const available = whId ? getAvailable(p.id, whId, base) : base;
    const isLow     = available < p.reorderPoint;
    const status    = isLow ? "Low Stock" : "In Stock";
    if (filters.category.length > 0 && !filters.category.includes(p.category)) return false;
    if (filters.unit.length     > 0 && !filters.unit.includes(p.unit))         return false;
    if (filters.status.length   > 0 && !filters.status.includes(status))       return false;
    return true;
  }

  const visibleProducts = allProducts.filter(rowMatchesFilters);

  const totalStockAll = visibleProducts.reduce((a, p) => {
    const base = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((x, y) => x + y, 0);
    return a + (whId ? getOnHand(p.id, whId, base) : base);
  }, 0);

  const activeFiltersCount = Object.values(filters).filter(
    (f) => f.length > 0 && f.length < (f === filters.category ? categoryOptions.length : f === filters.unit ? unitOptions.length : 2)
  ).length;

  const showWarehouseColumns = !!whId;

  return (
    <div style={{ padding: "2rem" }}>
      {/* Transaction detail modal */}
      {expandedCell && (
        <TransactionDetailModal
          col={expandedCell.col}
          productName={expandedCell.productName}
          rows={modalRows}
          onClose={() => setExpandedCell(null)}
        />
      )}

      {/* Header */}
      <div style={{ marginBottom: "1.25rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>Inventory</h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
            {tenant.name} · {whId ? (tenant.warehouses.find((w) => w.id === whId)?.name ?? "Warehouse") : "All locations"} · {visibleProducts.length} SKUs
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isMWH && <OpeningBalancePanel products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />}
          {isMWH && <BulkImportPanel     products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />}
          <ReceiveStockPanel products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />
          <IssueStockPanel   products={mergedProducts} warehouses={tenant.warehouses} orgSlug={org} />
          {canAddProduct && <AddProductPanel apiBase="/api/v1/products" />}
        </div>
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: "1rem", flexWrap: "wrap" }}>
        {!user.warehouseId && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em" }}>Warehouse</label>
            <select
              value={selectedWH}
              onChange={(e) => setSelectedWH(e.target.value)}
              style={{ padding: "6px 10px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", cursor: "pointer" }}
            >
              <option value="">All locations</option>
              {tenant.warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </div>
        )}

        {activeFiltersCount > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {(["category", "unit", "status"] as (keyof Filters)[]).map((field) =>
              filters[field].length > 0 && filters[field].length < (field === "category" ? categoryOptions.length : field === "unit" ? unitOptions.length : 2) ? (
                <span key={field} style={{ fontSize: 11, fontWeight: 700, background: "#DCFCE7", color: "#166534", padding: "2px 10px", borderRadius: 99, display: "flex", alignItems: "center", gap: 5 }}>
                  {field}: {filters[field].join(", ")}
                  <button onClick={() => setFilters({ ...filters, [field]: [] })} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#166534", padding: 0 }}>✕</button>
                </span>
              ) : null
            )}
            <button onClick={() => setFilters({ category: [], unit: [], status: [] })} style={{ fontSize: 11, color: "#6B7280", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
              Clear all
            </button>
          </div>
        )}

        <div style={{ marginLeft: "auto", fontSize: 12, color: "#6B7280" }}>
          {visibleProducts.length} of {allProducts.length} products · {totalStockAll.toLocaleString()} total units
        </div>
      </div>

      {/* Table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 6, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                <PlainHeader label="SKU" />
                <PlainHeader label="Product" />
                <FilterHeader label="Category" field="category" options={categoryOptions} filters={filters} setFilters={setFilters} />
                <FilterHeader label="Unit"     field="unit"     options={unitOptions}     filters={filters} setFilters={setFilters} />
                <PlainHeader label={whId ? "On Hand" : "Total Stock"} align="right" />
                {showWarehouseColumns && <PlainHeader label="Received"   align="right" />}
                {showWarehouseColumns && <PlainHeader label="Issued"     align="right" />}
                {showWarehouseColumns && <PlainHeader label="In Transit" align="right" />}
                {showWarehouseColumns && <PlainHeader label="Available"  align="right" />}
                <PlainHeader label="Reorder Pt" align="right" />
                <FilterHeader label="Status" field="status" options={statusOptions} filters={filters} setFilters={setFilters} align="left" />
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
                  <tr key={p.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    {/* SKU */}
                    <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF", whiteSpace: "nowrap" }}>{p.sku}</td>

                    {/* Product */}
                    <td style={{ padding: "10px 14px", fontWeight: 600, color: "#1F2937", whiteSpace: "nowrap" }}>
                      {p.name}
                      {p.batchTracking && (
                        <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 700, background: "#EDE9FE", color: "#5B21B6", padding: "1px 5px", borderRadius: 3 }}>BATCH</span>
                      )}
                    </td>

                    {/* Category */}
                    <td style={{ padding: "10px 14px", color: "#6B7280", fontSize: 12 }}>
                      <span style={{ background: "#F3F4F6", padding: "2px 8px", borderRadius: 4, fontWeight: 600, color: "#374151" }}>{p.category}</span>
                    </td>

                    {/* Unit */}
                    <td style={{ padding: "10px 14px", color: "#9CA3AF", fontSize: 12 }}>{p.unit}</td>

                    {/* On Hand */}
                    <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 700, color: onHand > 0 ? "#111827" : "#9CA3AF" }}>
                      {onHand.toLocaleString()}
                    </td>

                    {/* Received — expandable */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right" }}>
                        <ExpandCell
                          qty={received} color="#059669" bg="#F0FDF4" border="#BBF7D0" prefix="+"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "received" })}
                        />
                      </td>
                    )}

                    {/* Issued — expandable (direct issues + outbound reserved transfers) */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right" }}>
                        <ExpandCell
                          qty={issued} color="#DC2626" bg="#FEF2F2" border="#FECACA" prefix="−"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "issued" })}
                        />
                      </td>
                    )}

                    {/* In Transit — expandable (outbound IN_TRANSIT + inbound IN_TRANSIT) */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right" }}>
                        <ExpandCell
                          qty={inTransit} color="#92400E" bg="#FEF3C7" border="#FDE68A" icon="⏳"
                          onClick={() => setExpandedCell({ productId: p.id, productName: p.name, warehouseId: whId, col: "transit" })}
                        />
                      </td>
                    )}

                    {/* Available */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 700 }}>
                        <span style={{
                          display: "inline-block",
                          background: available > p.reorderPoint ? "#EFF6FF" : "#FEF2F2",
                          color:      available > p.reorderPoint ? "#1D4ED8" : "#DC2626",
                          padding: "2px 8px", borderRadius: 4, fontSize: 12, fontWeight: 700,
                        }}>
                          {available.toLocaleString()}
                        </span>
                      </td>
                    )}

                    {/* Reorder Point */}
                    <td style={{ padding: "10px 14px", textAlign: "right", color: "#9CA3AF", fontSize: 12 }}>
                      {p.reorderPoint.toLocaleString()}
                    </td>

                    {/* Status */}
                    <td style={{ padding: "10px 14px" }}>
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 3,
                        background: isLow ? "#FEF2F2" : "#F0FDF4",
                        color:      isLow ? "#DC2626"  : "#059669",
                        border:     `1px solid ${isLow ? "#FECACA" : "#BBF7D0"}`,
                      }}>
                        <span style={{ width: 6, height: 6, borderRadius: "50%", background: isLow ? "#DC2626" : "#059669" }} />
                        {isLow ? "Low Stock" : "In Stock"}
                      </span>
                    </td>
                  </tr>
                );
              })}

              {/* API (new) products */}
              {apiProducts.map((p, idx) => (
                <tr key={p.id} style={{ background: idx % 2 === 0 ? "#FAFFFE" : "#F0FDF4", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>
                    {p.sku}
                    <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 700, background: "#DCFCE7", color: "#166534", padding: "1px 5px", borderRadius: 3 }}>NEW</span>
                  </td>
                  <td style={{ padding: "10px 14px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                  <td style={{ padding: "10px 14px", color: "#6B7280", fontSize: 12 }}>
                    <span style={{ background: "#F3F4F6", padding: "2px 8px", borderRadius: 4, fontWeight: 600, color: "#374151" }}>{p.type_code}</span>
                  </td>
                  <td style={{ padding: "10px 14px", color: "#9CA3AF", fontSize: 12 }}>{p.unit}</td>
                  <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 700, color: "#9CA3AF" }}>0</td>
                  {showWarehouseColumns && <td style={{ padding: "10px 14px", textAlign: "right", color: "#E5E7EB" }}>—</td>}
                  {showWarehouseColumns && <td style={{ padding: "10px 14px", textAlign: "right", color: "#E5E7EB" }}>—</td>}
                  {showWarehouseColumns && <td style={{ padding: "10px 14px", textAlign: "right", color: "#E5E7EB" }}>—</td>}
                  {showWarehouseColumns && <td style={{ padding: "10px 14px", textAlign: "right", color: "#E5E7EB" }}>—</td>}
                  <td style={{ padding: "10px 14px", textAlign: "right", color: "#9CA3AF", fontSize: 12 }}>—</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 3, background: "#FEF9C3", color: "#854D0E", border: "1px solid #FDE68A" }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#854D0E" }} />
                      No Stock
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {visibleProducts.length === 0 && apiProducts.length === 0 && (
            <p style={{ padding: "2rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>
              No products match the current filters.{" "}
              <button onClick={() => setFilters({ category: [], unit: [], status: [] })} style={{ background: "none", border: "none", cursor: "pointer", color: "#1B4332", fontWeight: 700, textDecoration: "underline" }}>
                Clear filters
              </button>
            </p>
          )}
        </div>
      </div>

      {/* Column legend */}
      {showWarehouseColumns && (
        <p style={{ marginTop: "0.75rem", fontSize: 12, color: "#9CA3AF" }}>
          <strong style={{ color: "#059669" }}>Received</strong> — stock in this session (click ↗ to expand) ·{" "}
          <strong style={{ color: "#DC2626" }}>Issued</strong> — direct issues + reserved outbound transfers (click to expand) ·{" "}
          <strong style={{ color: "#92400E" }}>In Transit ⏳</strong> — ← inbound / → outbound currently moving (click to expand) ·{" "}
          <strong style={{ color: "#1D4ED8" }}>Available</strong> — On Hand minus issues and reservations
        </p>
      )}
    </div>
  );
}
