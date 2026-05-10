"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

interface Props {
  products: DemoProduct[];
  warehouses: DemoWarehouse[];
  orgSlug: string;
}

const REASONS = [
  { value: "DAMAGE",            label: "Damaged / Write-off" },
  { value: "COUNT_VARIANCE",    label: "Stock Count Variance" },
  { value: "EXPIRY",            label: "Expired Stock Disposal" },
  { value: "SUPPLIER_RETURN",   label: "Return to Supplier" },
  { value: "SYSTEM_CORRECTION", label: "System Correction" },
  { value: "OTHER",             label: "Other" },
];

// PRODUCER thresholds (mirrors _demo-state.ts)
const THRESHOLDS = { low: 100, medium: 500 };

function getApprovalInfo(qty: number): { role: string; label: string; color: string } {
  const abs = Math.abs(qty);
  if (abs < THRESHOLDS.low)    return { role: "NONE", label: "Auto-approved (below 100 units)", color: "#059669" };
  if (abs < THRESHOLDS.medium) return { role: "RM",   label: "Requires Regional Manager approval (100–500 units)", color: "#D97706" };
  return                              { role: "NM",   label: "Requires National Manager approval (≥500 units)", color: "#DC2626" };
}

const PANEL_W = 440;
const INPUT: React.CSSProperties = { width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 4, outline: "none", background: "#fff", boxSizing: "border-box" };

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: "block", fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#374151", marginBottom: 4 }}>
        {label}{hint && <span style={{ fontSize: 11, fontWeight: 400, textTransform: "none", color: "#9CA3AF", marginLeft: 6 }}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

interface AdjResult { status: string; approval_required_role: string }

export function NewAdjustmentPanel({ products, warehouses, orgSlug }: Props) {
  const qc = useQueryClient();

  const [open, setOpen]           = useState(false);
  const [productId, setProductId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity]   = useState("");
  const [reason, setReason]       = useState("");
  const [notes, setNotes]         = useState("");
  const [error, setError]         = useState("");
  const [result, setResult]       = useState<AdjResult | null>(null);
  const [loading, setLoading]     = useState(false);

  function reset() {
    setProductId(""); setWarehouseId(""); setQuantity(""); setReason(""); setNotes("");
    setError(""); setResult(null);
  }

  const qty       = parseFloat(quantity) || 0;
  const approvalInfo = qty !== 0 ? getApprovalInfo(qty) : null;
  const selectedP = products.find((p) => p.id === productId);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!productId)   { setError("Please select a product."); return; }
    if (!warehouseId) { setError("Please select a warehouse."); return; }
    if (!reason)      { setError("Please select a reason."); return; }
    if (qty === 0)    { setError("Quantity must be non-zero."); return; }

    const key = `adjust:${productId}:${warehouseId}:${Date.now()}:${nanoid(8)}`;
    setLoading(true);
    try {
      const adj = await api.post<AdjResult>("/api/v1/inventory/adjust", {
        product_id: productId, product_name: selectedP?.name, product_sku: selectedP?.sku,
        warehouse_id: warehouseId,
        warehouse_name: warehouses.find((w) => w.id === warehouseId)?.name,
        quantity: qty, reason_code: reason, notes,
        idempotency_key: key,
      });
      setResult(adj);
      void qc.invalidateQueries({ queryKey: ["adjustments", orgSlug] });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit adjustment.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={() => { reset(); setOpen(true); }}
        style={{ padding: "8px 16px", background: "#0891B2", color: "#fff", fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer" }}
      >
        + New Adjustment
      </button>

      {open && <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", zIndex: 100, backdropFilter: "blur(2px)" }} />}

      <div style={{ position: "fixed", top: 0, right: open ? 0 : -PANEL_W, width: PANEL_W, height: "100vh", background: "#fff", zIndex: 110, boxShadow: "-4px 0 24px rgba(0,0,0,0.18)", transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "1.25rem 1.5rem", background: "#0891B2", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>Stock Adjustment</p>
            <p style={{ fontSize: 12, color: "#BAE6FD", margin: "2px 0 0" }}>Correct stock balance — approval may be required</p>
          </div>
          <button onClick={() => setOpen(false)} style={{ background: "rgba(255,255,255,0.15)", border: "none", cursor: "pointer", color: "#fff", fontSize: 18, width: 32, height: 32, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
        </div>

        {result ? (
          /* ── Success screen ── */
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "2rem", textAlign: "center" }}>
            <div style={{ width: 64, height: 64, borderRadius: "50%", background: result.status === "APPLIED" ? "#DCFCE7" : "#FEF3C7", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, margin: "0 0 1.25rem" }}>
              {result.status === "APPLIED" ? "✓" : "⏳"}
            </div>
            <p style={{ fontWeight: 800, fontSize: 18, color: "#111827", margin: "0 0 0.5rem" }}>
              {result.status === "APPLIED" ? "Adjustment Applied" : "Submitted for Approval"}
            </p>
            <p style={{ fontSize: 14, color: "#6B7280", margin: "0 0 2rem" }}>
              {result.status === "APPLIED"
                ? "The adjustment has been auto-approved and applied to the ledger."
                : `Awaiting ${result.approval_required_role} approval.`}
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={reset} style={{ padding: "9px 20px", background: "#F3F4F6", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>New Adjustment</button>
              <button onClick={() => { reset(); setOpen(false); }} style={{ padding: "9px 20px", background: "#0891B2", color: "#fff", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 700, cursor: "pointer" }}>Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={onSubmit} style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
            <Field label="Product">
              <select value={productId} onChange={(e) => setProductId(e.target.value)} style={{ ...INPUT, cursor: "pointer" }} required>
                <option value="">— select product —</option>
                {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
              </select>
            </Field>

            <Field label="Warehouse">
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} style={{ ...INPUT, cursor: "pointer" }} required>
                <option value="">— select warehouse —</option>
                {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>

            <Field label="Adjustment Quantity" hint="positive = add, negative = remove">
              <input
                type="number" step="any"
                value={quantity} onChange={(e) => setQuantity(e.target.value)}
                placeholder="e.g. -50 or +200" style={INPUT}
              />
              {approvalInfo && (
                <div style={{ marginTop: 6, padding: "6px 10px", borderRadius: 4, background: approvalInfo.role === "NONE" ? "#F0FDF4" : approvalInfo.role === "RM" ? "#FEF3C7" : "#FEF2F2", fontSize: 12, color: approvalInfo.color }}>
                  {approvalInfo.label}
                </div>
              )}
            </Field>

            <Field label="Reason">
              <select value={reason} onChange={(e) => setReason(e.target.value)} style={{ ...INPUT, cursor: "pointer" }} required>
                <option value="">— select reason —</option>
                {REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </Field>

            <Field label="Notes" hint="optional">
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Supporting details…" rows={3} style={{ ...INPUT, resize: "vertical" }} />
            </Field>

            {error && <div style={{ background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 4, padding: "10px 12px", fontSize: 13, color: "#DC2626", marginBottom: 12 }}>{error}</div>}
          </form>
        )}

        {!result && (
          <div style={{ padding: "1rem 1.5rem", borderTop: "1px solid #E5E7EB", display: "flex", gap: 10 }}>
            <button type="button" onClick={() => setOpen(false)} style={{ flex: 1, padding: "10px", background: "#F3F4F6", border: "1px solid #E5E7EB", borderRadius: 4, fontSize: 13, fontWeight: 600, color: "#374151", cursor: "pointer" }}>Cancel</button>
            <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={loading} style={{ flex: 2, padding: "10px", fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: loading ? "not-allowed" : "pointer", background: "#0891B2", color: "#fff", opacity: loading ? 0.7 : 1 }}>
              {loading ? "Submitting…" : "Submit Adjustment"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
