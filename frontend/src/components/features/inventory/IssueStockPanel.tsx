"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { enqueueOfflineTransaction } from "@/store/offlineQueue";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useInventoryStore } from "@/lib/inventory-state";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

interface Props {
  products: DemoProduct[];
  warehouses: DemoWarehouse[];
  orgSlug: string;
}

const REASONS = [
  { value: "SALE",            label: "Sale / Dispatch to Customer" },
  { value: "INTERNAL_USE",    label: "Internal Use" },
  { value: "DAMAGE",          label: "Damaged / Write-off" },
  { value: "EXPIRY",          label: "Expired Stock Disposal" },
  { value: "SAMPLE",          label: "Sample / Promotion" },
  { value: "OTHER",           label: "Other" },
];

// Destination label and placeholder per reason code
const DESTINATION_META: Record<string, { label: string; placeholder: string; required: boolean }> = {
  SALE:         { label: "Issued To (Customer / Recipient)", placeholder: "e.g. Addis Supermarket, Order #1042", required: true  },
  INTERNAL_USE: { label: "Issued To (Department / Team)",   placeholder: "e.g. Quality Control, Head Office",   required: true  },
  SAMPLE:       { label: "Issued To (Recipient)",           placeholder: "e.g. Distributor name, event name",   required: true  },
  DAMAGE:       { label: "Destination / Disposal Note",     placeholder: "e.g. Disposed on-site, Returned to supplier", required: false },
  EXPIRY:       { label: "Destination / Disposal Note",     placeholder: "e.g. Disposed on-site, Incinerated", required: false },
  OTHER:        { label: "Issued To / Destination",         placeholder: "Recipient or destination",             required: false },
};

const PANEL_W = 420;

const INPUT: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #D1D5DB", borderRadius: 4,
  outline: "none", background: "#fff", boxSizing: "border-box",
};
const SELECT: React.CSSProperties = { ...INPUT, cursor: "pointer" };

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: "block", fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#374151", marginBottom: 4 }}>
        {label}
        {hint && <span style={{ fontSize: 11, fontWeight: 400, textTransform: "none", color: "#9CA3AF", marginLeft: 6 }}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

export function IssueStockPanel({ products, warehouses, orgSlug }: Props) {
  const { isOnline } = useOfflineSync();
  const qc = useQueryClient();
  const { addIssue, getAvailable } = useInventoryStore();

  const [open, setOpen]             = useState(false);
  const [productId, setProductId]   = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity]     = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [issuedTo, setIssuedTo]     = useState("");
  const [notes, setNotes]           = useState("");
  const [error, setError]           = useState("");
  const [success, setSuccess]       = useState("");
  const [loading, setLoading]       = useState(false);

  const destMeta = reasonCode ? DESTINATION_META[reasonCode] : null;

  function reset() {
    setProductId(""); setWarehouseId(""); setQuantity("");
    setReasonCode(""); setIssuedTo(""); setNotes("");
    setError(""); setSuccess("");
  }

  // Show only warehouses that have stock for the selected product
  const availableWarehouses = productId
    ? warehouses.filter((w) => {
        const p = products.find((pr) => pr.id === productId);
        if (!p) return true;
        const base = p.stock[w.id] ?? 0;
        return getAvailable(p.id, w.id, base) > 0;
      })
    : warehouses;

  const selectedProduct = products.find((p) => p.id === productId);
  // Use live Available from inventory store (reflects reserved/in-transit stock)
  const availableStock  = selectedProduct && warehouseId
    ? getAvailable(selectedProduct.id, warehouseId, selectedProduct.stock[warehouseId] ?? 0)
    : null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!productId)   { setError("Please select a product."); return; }
    if (!warehouseId) { setError("Please select a warehouse."); return; }
    if (!reasonCode)  { setError("Please select a reason code."); return; }
    if (destMeta?.required && !issuedTo.trim()) {
      setError(`"${destMeta.label}" is required for this reason.`); return;
    }
    const qty = parseFloat(quantity);
    if (!qty || qty <= 0) { setError("Quantity must be a positive number."); return; }
    if (availableStock !== null && qty > availableStock) {
      setError(`Insufficient stock. Available: ${availableStock.toLocaleString()} units.`); return;
    }

    const key = `issue:${productId}:${warehouseId}:${Date.now()}:${nanoid(8)}`;
    const payload = {
      product_id:   productId,
      warehouse_id: warehouseId,
      quantity:     qty.toFixed(4),
      reason_code:  reasonCode,
      issued_to:    issuedTo.trim() || undefined,
      notes,
      idempotency_key: key,
    };

    setLoading(true);
    try {
      if (!isOnline) {
        await enqueueOfflineTransaction({ idempotencyKey: key, action: "inventory:issue", payload });
        setSuccess(`${selectedProduct?.name ?? "Stock"} issue queued for sync.`);
      } else {
        await api.post("/api/v1/inventory/issue", payload);
        addIssue(productId, warehouseId, qty);
        setSuccess(
          issuedTo.trim()
            ? `${selectedProduct?.name ?? "Stock"} issued to ${issuedTo.trim()}.`
            : `${selectedProduct?.name ?? "Stock"} issued successfully.`
        );
        void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
      }
      reset();
      setTimeout(() => { setSuccess(""); setOpen(false); }, 2500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to issue stock.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={() => { reset(); setOpen(true); }}
        style={{
          padding: "8px 16px", background: "#7C3AED", color: "#fff",
          fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer",
        }}
      >
        Issue Stock
      </button>

      {open && (
        <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", zIndex: 100, backdropFilter: "blur(2px)" }} />
      )}

      <div style={{
        position: "fixed", top: 0, right: open ? 0 : -PANEL_W,
        width: PANEL_W, height: "100vh", background: "#fff", zIndex: 110,
        boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
        transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)",
        display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "1.25rem 1.5rem", background: "#7C3AED", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>Issue Stock</p>
            <p style={{ fontSize: 12, color: "#E9D5FF", margin: "2px 0 0" }}>Record outbound stock movement</p>
          </div>
          <button onClick={() => setOpen(false)} style={{ background: "rgba(255,255,255,0.15)", border: "none", cursor: "pointer", color: "#fff", fontSize: 18, width: 32, height: 32, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
        </div>

        <form onSubmit={onSubmit} style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
          <Field label="Product">
            <select value={productId} onChange={(e) => { setProductId(e.target.value); setWarehouseId(""); }} style={SELECT} required>
              <option value="">— select product —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
            </select>
          </Field>

          <Field label="From Warehouse">
            <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} style={SELECT} required>
              <option value="">— select warehouse —</option>
              {availableWarehouses.map((w) => {
                const liveAvail = selectedProduct
                  ? getAvailable(selectedProduct.id, w.id, selectedProduct.stock[w.id] ?? 0)
                  : null;
                return (
                  <option key={w.id} value={w.id}>
                    {w.name}{liveAvail !== null ? ` · ${liveAvail.toLocaleString()} available` : ""}
                  </option>
                );
              })}
            </select>
          </Field>

          {availableStock !== null && (
            <div style={{ background: "#F5F3FF", border: "1px solid #DDD6FE", borderRadius: 6, padding: "8px 12px", marginBottom: 12, fontSize: 12, color: "#5B21B6" }}>
              Available stock: <strong>{availableStock.toLocaleString()}</strong> units
            </div>
          )}

          <Field label="Quantity to Issue">
            <input
              type="number" min="0.0001" step="any"
              value={quantity} onChange={(e) => setQuantity(e.target.value)}
              placeholder="e.g. 100" style={INPUT} required
            />
          </Field>

          <Field label="Reason Code">
            <select
              value={reasonCode}
              onChange={(e) => { setReasonCode(e.target.value); setIssuedTo(""); }}
              style={SELECT}
              required
            >
              <option value="">— select reason —</option>
              {REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </Field>

          {/* Destination — shown after reason is selected, label adapts per reason */}
          {destMeta && (
            <Field
              label={destMeta.label}
              hint={destMeta.required ? undefined : "optional"}
            >
              <input
                type="text"
                value={issuedTo}
                onChange={(e) => setIssuedTo(e.target.value)}
                placeholder={destMeta.placeholder}
                style={INPUT}
                required={destMeta.required}
              />
            </Field>
          )}

          <Field label="Notes" hint="optional">
            <textarea
              value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Customer name, order reference, notes…"
              rows={3} style={{ ...INPUT, resize: "vertical" }}
            />
          </Field>

          {error   && <div style={{ background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 4, padding: "10px 12px", fontSize: 13, color: "#DC2626", marginBottom: 12 }}>{error}</div>}
          {success && <div style={{ background: "#F5F3FF", border: "1px solid #DDD6FE", borderRadius: 4, padding: "10px 12px", fontSize: 13, color: "#5B21B6", marginBottom: 12 }}>✓ {success}</div>}
        </form>

        <div style={{ padding: "1rem 1.5rem", borderTop: "1px solid #E5E7EB", display: "flex", gap: 10 }}>
          <button type="button" onClick={() => setOpen(false)} style={{ flex: 1, padding: "10px", background: "#F3F4F6", border: "1px solid #E5E7EB", borderRadius: 4, fontSize: 13, fontWeight: 600, color: "#374151", cursor: "pointer" }}>
            Cancel
          </button>
          <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={loading} style={{ flex: 2, padding: "10px", fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: loading ? "not-allowed" : "pointer", background: "#7C3AED", color: "#fff", opacity: loading ? 0.7 : 1 }}>
            {loading ? "Processing…" : "Issue Stock"}
          </button>
        </div>
      </div>
    </>
  );
}
