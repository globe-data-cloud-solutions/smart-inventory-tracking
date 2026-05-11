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
import { useInventoryStore, type PendingTransfer } from "@/lib/inventory-state";
import { api } from "@/lib/api";

/* ── Types ─────────────────────────────────────────────────────────────────── */
type ApiProduct = {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; created_at: string;
};

type Filters = { category: string[]; unit: string[]; status: string[] };

/* ── Column filter dropdown ─────────────────────────────────────────────────── */
function FilterDropdown({
  options, selected, onChange, onClose,
}: {
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
  onClose: () => void;
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

  function toggleAll() {
    onChange(allSelected ? [] : [...options]);
  }

  return (
    <div ref={ref} style={{
      position: "absolute", top: "100%", left: 0, zIndex: 50, marginTop: 4,
      background: "#fff", border: "1px solid #E5E7EB", borderRadius: 6,
      boxShadow: "0 8px 24px rgba(0,0,0,0.12)", minWidth: 160, padding: "6px 0",
    }}>
      <label style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", cursor: "pointer", fontSize: 12, color: "#374151", borderBottom: "1px solid #F3F4F6" }}>
        <input type="checkbox" checked={allSelected} onChange={toggleAll} style={{ cursor: "pointer" }} />
        <span style={{ fontWeight: 600 }}>All</span>
      </label>
      {options.map((opt) => (
        <label key={opt} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", cursor: "pointer", fontSize: 12, color: "#374151" }}>
          <input
            type="checkbox"
            checked={selected.length === 0 || selected.includes(opt)}
            onChange={() => toggle(opt)}
            style={{ cursor: "pointer" }}
          />
          {opt}
        </label>
      ))}
    </div>
  );
}

/* ── Filterable column header ───────────────────────────────────────────────── */
function FilterHeader({
  label, field, options, filters, setFilters, align = "left",
}: {
  label: string; field: keyof Filters; options: string[];
  filters: Filters; setFilters: (f: Filters) => void; align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const active = filters[field].length > 0 && filters[field].length < options.length;

  return (
    <th style={{
      padding: "10px 14px", textAlign: align,
      fontSize: 11, fontWeight: 700, color: "#6B7280",
      textTransform: "uppercase", letterSpacing: "0.05em",
      whiteSpace: "nowrap", position: "relative", userSelect: "none",
    }}>
      <div
        style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }}
        onClick={() => setOpen((o) => !o)}
      >
        <span style={{ color: active ? "#1B4332" : "#6B7280" }}>{label}</span>
        <span style={{
          fontSize: 9, color: active ? "#1B4332" : "#9CA3AF",
          background: active ? "#DCFCE7" : "transparent",
          padding: active ? "1px 4px" : "0", borderRadius: 3, fontWeight: 900,
        }}>
          {active ? `${filters[field].length}✓` : "▾"}
        </span>
      </div>
      {open && (
        <FilterDropdown
          options={options}
          selected={filters[field]}
          onChange={(v) => setFilters({ ...filters, [field]: v })}
          onClose={() => setOpen(false)}
        />
      )}
    </th>
  );
}

/* ── Plain column header ────────────────────────────────────────────────────── */
function PlainHeader({ label, align = "left" }: { label: string; align?: "left" | "right" }) {
  return (
    <th style={{
      padding: "10px 14px", textAlign: align,
      fontSize: 11, fontWeight: 700, color: "#6B7280",
      textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap",
    }}>{label}</th>
  );
}

/* ── Pending popup ──────────────────────────────────────────────────────────── */
function PendingModal({
  productName, transfers, onClose,
}: {
  productName: string;
  transfers: PendingTransfer[];
  onClose: () => void;
}) {
  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", zIndex: 200 }} />
      <div style={{
        position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
        background: "#fff", borderRadius: 10, zIndex: 201, width: 480,
        boxShadow: "0 12px 40px rgba(0,0,0,0.2)", overflow: "hidden",
      }}>
        <div style={{ padding: "1rem 1.25rem", background: "#0f2d1f", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 15, color: "#fff", margin: 0 }}>Pending Incoming Stock</p>
            <p style={{ fontSize: 12, color: "#6ee7b7", margin: "2px 0 0" }}>{productName}</p>
          </div>
          <button onClick={onClose} style={{ background: "rgba(255,255,255,0.1)", border: "none", cursor: "pointer", color: "#fff", fontSize: 16, width: 28, height: 28, borderRadius: 4 }}>✕</button>
        </div>
        <div style={{ padding: "1rem" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                {["From Warehouse", "Quantity", "Issued Date", "Ref"].map((h) => (
                  <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {transfers.map((t, i) => (
                <tr key={t.id} style={{ background: i % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "9px 12px", fontWeight: 600, color: "#1F2937" }}>{t.fromWarehouseName}</td>
                  <td style={{ padding: "9px 12px", fontWeight: 700, color: "#1B4332" }}>{t.quantity.toLocaleString()}</td>
                  <td style={{ padding: "9px 12px", color: "#6B7280", fontSize: 12 }}>{new Date(t.issuedDate).toLocaleDateString()} {new Date(t.issuedDate).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                  <td style={{ padding: "9px 12px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{t.ref}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ background: "#F0FDF4", borderTop: "2px solid #BBF7D0" }}>
                <td style={{ padding: "9px 12px", fontWeight: 700, color: "#1B4332", fontSize: 12 }}>Total Pending</td>
                <td style={{ padding: "9px 12px", fontWeight: 800, color: "#1B4332" }}>
                  {transfers.reduce((a, t) => a + t.quantity, 0).toLocaleString()}
                </td>
                <td colSpan={2} style={{ padding: "9px 12px", fontSize: 12, color: "#9CA3AF" }}>
                  In transit · will move to My Stock on receipt
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </>
  );
}

/* ── Main page ───────────────────────────────────────────────────────────────── */
export default function InventoryPage() {
  const { org }        = useParams() as { org: string };
  const user           = getSession();
  const canAddProduct  = usePermission("product:create");
  const { getOnHand, getReceived, getIssued, getAvailable, getPending } = useInventoryStore();

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);

  // Warehouse selector (TA/NM/SA can pick a specific warehouse)
  const [selectedWH, setSelectedWH] = useState<string>(user?.warehouseId ?? "");

  // Active warehouse context
  const whId = selectedWH || user?.warehouseId || "";

  // Column filters
  const [filters, setFilters] = useState<Filters>({ category: [], unit: [], status: [] });

  // Pending popup
  const [pendingModal, setPendingModal] = useState<{ product: DemoProduct; warehouseId: string } | null>(null);

  // Fetch API products (created via Add Product panel)
  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!tenant && !!user && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  if (!user || org === SA_ORG_SLUG) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view inventory.</p>;
  }
  if (!tenant) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;
  }

  // Products to display
  const allProducts = whId
    ? tenant.products.filter((p) => {
        const base = p.stock[whId] ?? 0;
        const onH  = getOnHand(p.id, whId, base);
        const pend = getPending(p.id, whId);
        return onH > 0 || pend.length > 0;
      })
    : tenant.products;

  // Build unique filter option lists
  const categoryOptions = Array.from(new Set(allProducts.map((p) => p.category)));
  const unitOptions     = Array.from(new Set(allProducts.map((p) => p.unit)));
  const statusOptions   = ["In Stock", "Low Stock"];

  // Apply filters
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

  const activeFiltersCount = Object.values(filters).filter((f) => f.length > 0 && f.length < (f === filters.category ? categoryOptions.length : f === filters.unit ? unitOptions.length : 2)).length;

  const showWarehouseColumns = !!whId;

  return (
    <div style={{ padding: "2rem" }}>
      {/* Pending popup */}
      {pendingModal && (
        <PendingModal
          productName={pendingModal.product.name}
          transfers={getPending(pendingModal.product.id, pendingModal.warehouseId)}
          onClose={() => setPendingModal(null)}
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
          <ReceiveStockPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
          <IssueStockPanel   products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
          {canAddProduct && <AddProductPanel apiBase="/api/v1/products" />}
        </div>
      </div>

      {/* Toolbar: warehouse selector + filter summary */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: "1rem", flexWrap: "wrap" }}>
        {/* Warehouse selector — shown to TA/NM/SA */}
        {!user.warehouseId && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Warehouse
            </label>
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

        {/* Active filter chips */}
        {activeFiltersCount > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {(["category", "unit", "status"] as (keyof Filters)[]).map((field) =>
              filters[field].length > 0 && filters[field].length < (field === "category" ? categoryOptions.length : field === "unit" ? unitOptions.length : 2) ? (
                <span key={field} style={{ fontSize: 11, fontWeight: 700, background: "#DCFCE7", color: "#166534", padding: "2px 10px", borderRadius: 99, display: "flex", alignItems: "center", gap: 5 }}>
                  {field}: {filters[field].join(", ")}
                  <button onClick={() => setFilters({ ...filters, [field]: [] })} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#166534", padding: 0, lineHeight: 1 }}>✕</button>
                </span>
              ) : null
            )}
            <button onClick={() => setFilters({ category: [], unit: [], status: [] })} style={{ fontSize: 11, color: "#6B7280", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
              Clear all
            </button>
          </div>
        )}

        {/* Summary stat */}
        <div style={{ marginLeft: "auto", fontSize: 12, color: "#6B7280" }}>
          {visibleProducts.length} of {allProducts.length} products · {totalStockAll.toLocaleString()} total units
        </div>
      </div>

      {/* ── Main table ── */}
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
                <PlainHeader label={whId ? "On Hand"   : "Total Stock"} align="right" />
                {showWarehouseColumns && <PlainHeader label="Received"  align="right" />}
                {showWarehouseColumns && <PlainHeader label="Issued"    align="right" />}
                {showWarehouseColumns && <PlainHeader label="In Transit" align="right" />}
                {showWarehouseColumns && <PlainHeader label="Available" align="right" />}
                <PlainHeader label="Reorder Pt" align="right" />
                <FilterHeader label="Status" field="status" options={statusOptions} filters={filters} setFilters={setFilters} align="left" />
              </tr>
            </thead>
            <tbody>
              {visibleProducts.map((p, idx) => {
                const base      = whId ? (p.stock[whId] ?? 0) : Object.values(p.stock).reduce((a, b) => a + b, 0);
                const onHand    = whId ? getOnHand(p.id, whId, base) : base;
                const received  = whId ? getReceived(p.id, whId) : 0;
                const issued    = whId ? getIssued(p.id, whId) : 0;
                const available = whId ? getAvailable(p.id, whId, base) : base;
                const pendList  = whId ? getPending(p.id, whId) : [];
                const pendQty   = pendList.reduce((a, t) => a + t.quantity, 0);
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

                    {/* On Hand / Total Stock */}
                    <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 700, color: onHand > 0 ? "#111827" : "#9CA3AF" }}>
                      {onHand.toLocaleString()}
                    </td>

                    {/* Received (session) */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 600, color: received > 0 ? "#059669" : "#E5E7EB" }}>
                        {received > 0 ? `+${received.toLocaleString()}` : "—"}
                      </td>
                    )}

                    {/* Issued (direct: sales, damage, etc.) */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 600, color: issued > 0 ? "#DC2626" : "#E5E7EB" }}>
                        {issued > 0 ? `−${issued.toLocaleString()}` : "—"}
                      </td>
                    )}

                    {/* In Transit / Pending (clickable) */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right" }}>
                        {pendQty > 0 ? (
                          <button
                            onClick={() => setPendingModal({ product: p, warehouseId: whId })}
                            style={{
                              fontWeight: 700, fontSize: 12, color: "#92400E",
                              background: "#FEF3C7", border: "1px solid #FDE68A",
                              borderRadius: 4, padding: "3px 10px", cursor: "pointer",
                              display: "inline-flex", alignItems: "center", gap: 4,
                            }}
                          >
                            <span>⏳</span>{pendQty.toLocaleString()}
                          </button>
                        ) : (
                          <span style={{ color: "#E5E7EB" }}>—</span>
                        )}
                      </td>
                    )}

                    {/* Available = On Hand − Issued */}
                    {showWarehouseColumns && (
                      <td style={{ padding: "10px 14px", textAlign: "right", fontWeight: 700 }}>
                        <span style={{
                          display: "inline-block",
                          background: available > p.reorderPoint ? "#EFF6FF" : "#FEF2F2",
                          color: available > p.reorderPoint ? "#1D4ED8" : "#DC2626",
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

              {/* API (new) products — always at bottom with 0 balance */}
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
          <strong style={{ color: "#059669" }}>Received</strong> — received this session ·{" "}
          <strong style={{ color: "#DC2626" }}>Issued</strong> — dispatched to customers / written off ·{" "}
          <strong style={{ color: "#92400E" }}>In Transit ⏳</strong> — inbound from another warehouse (click for details) ·{" "}
          <strong style={{ color: "#1D4ED8" }}>Available</strong> — On Hand minus Issued (blue = above reorder, red = below)
        </p>
      )}
    </div>
  );
}
