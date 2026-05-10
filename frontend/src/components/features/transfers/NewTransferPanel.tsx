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

type FormState = {
  productId: string;
  fromWarehouseId: string;
  toWarehouseId: string;
  quantity: string;
  notes: string;
};

const PANEL_W = 420;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{
        display: "block", fontSize: 12, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: "0.05em",
        color: "#374151", marginBottom: 4,
      }}>
        {label}
        {hint && <span style={{ fontSize: 11, fontWeight: 400, textTransform: "none", color: "#9CA3AF", marginLeft: 6 }}>{hint}</span>}
      </label>
      {children}
    </div>
  );
}

const INPUT: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #D1D5DB", borderRadius: 4,
  outline: "none", background: "#fff", boxSizing: "border-box",
};
const SELECT: React.CSSProperties = { ...INPUT, cursor: "pointer" };

export function NewTransferPanel({ products, warehouses, orgSlug }: Props) {
  const qc = useQueryClient();

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>({
    productId: "", fromWarehouseId: "", toWarehouseId: "", quantity: "", notes: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  function reset() {
    setForm({ productId: "", fromWarehouseId: "", toWarehouseId: "", quantity: "", notes: "" });
    setError("");
    setSuccess("");
  }

  function set(key: keyof FormState, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
    setError("");
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!form.productId) { setError("Please select a product."); return; }
    if (!form.fromWarehouseId) { setError("Please select the origin warehouse."); return; }
    if (!form.toWarehouseId) { setError("Please select the destination warehouse."); return; }
    if (form.fromWarehouseId === form.toWarehouseId) { setError("Origin and destination must be different."); return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0) { setError("Quantity must be a positive number."); return; }

    const product = products.find((p) => p.id === form.productId);
    const fromWH  = warehouses.find((w) => w.id === form.fromWarehouseId);
    const toWH    = warehouses.find((w) => w.id === form.toWarehouseId);

    setLoading(true);
    try {
      await api.post("/api/v1/transfers", {
        product_id: form.productId,
        product_name: product?.name,
        from_warehouse_id: form.fromWarehouseId,
        from_warehouse_name: fromWH?.name,
        to_warehouse_id: form.toWarehouseId,
        to_warehouse_name: toWH?.name,
        quantity: qty,
        notes: form.notes,
        idempotency_key: `transfer:${form.productId}:${form.fromWarehouseId}:${form.toWarehouseId}:${Date.now()}:${nanoid(8)}`,
      });
      setSuccess(`Transfer created for ${product?.name ?? "product"} → ${toWH?.name}.`);
      void qc.invalidateQueries({ queryKey: ["transfers", orgSlug] });
      reset();
      setTimeout(() => { setSuccess(""); setOpen(false); }, 2500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create transfer.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={() => { reset(); setOpen(true); }}
        style={{
          padding: "8px 16px", background: "#FCDD09", color: "#0f2d1f",
          fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer",
        }}
      >
        + New Transfer
      </button>

      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)",
            zIndex: 100, backdropFilter: "blur(2px)",
          }}
        />
      )}

      <div style={{
        position: "fixed", top: 0, right: open ? 0 : -PANEL_W,
        width: PANEL_W, height: "100vh", background: "#fff", zIndex: 110,
        boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
        transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)",
        display: "flex", flexDirection: "column",
      }}>
        <div style={{
          padding: "1.25rem 1.5rem", background: "#0f2d1f",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>New Stock Transfer</p>
            <p style={{ fontSize: 12, color: "#6ee7b7", margin: "2px 0 0" }}>Creates a DRAFT transfer order</p>
          </div>
          <button onClick={() => setOpen(false)} style={{
            background: "rgba(255,255,255,0.1)", border: "none", cursor: "pointer",
            color: "#fff", fontSize: 18, width: 32, height: 32, borderRadius: 4,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>✕</button>
        </div>

        <form onSubmit={onSubmit} style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
          <Field label="Product">
            <select value={form.productId} onChange={(e) => set("productId", e.target.value)} style={SELECT} required>
              <option value="">— select product —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>
              ))}
            </select>
          </Field>

          <Field label="From Warehouse">
            <select value={form.fromWarehouseId} onChange={(e) => set("fromWarehouseId", e.target.value)} style={SELECT} required>
              <option value="">— origin —</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </Field>

          <Field label="To Warehouse">
            <select value={form.toWarehouseId} onChange={(e) => set("toWarehouseId", e.target.value)} style={SELECT} required>
              <option value="">— destination —</option>
              {warehouses
                .filter((w) => w.id !== form.fromWarehouseId)
                .map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
            </select>
          </Field>

          <Field label="Quantity">
            <input
              type="number" min="1" step="1"
              value={form.quantity}
              onChange={(e) => set("quantity", e.target.value)}
              placeholder="e.g. 200"
              style={INPUT}
              required
            />
          </Field>

          <Field label="Notes" hint="optional">
            <textarea
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Reason for transfer, special instructions…"
              rows={3}
              style={{ ...INPUT, resize: "vertical" }}
            />
          </Field>

          {error && (
            <div style={{
              background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 4,
              padding: "10px 12px", fontSize: 13, color: "#DC2626", marginBottom: 12,
            }}>{error}</div>
          )}

          {success && (
            <div style={{
              background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 4,
              padding: "10px 12px", fontSize: 13, color: "#059669", marginBottom: 12,
            }}>✓ {success}</div>
          )}
        </form>

        <div style={{ padding: "1rem 1.5rem", borderTop: "1px solid #E5E7EB", display: "flex", gap: 10 }}>
          <button
            type="button" onClick={() => setOpen(false)}
            style={{
              flex: 1, padding: "10px", background: "#F3F4F6", border: "1px solid #E5E7EB",
              borderRadius: 4, fontSize: 13, fontWeight: 600, color: "#374151", cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={onSubmit as unknown as React.MouseEventHandler}
            disabled={loading}
            style={{
              flex: 2, padding: "10px", fontWeight: 700, fontSize: 13, borderRadius: 4,
              border: "none", cursor: loading ? "not-allowed" : "pointer",
              background: "#0f2d1f", color: "#FCDD09", opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "Creating…" : "Create Transfer"}
          </button>
        </div>
      </div>
    </>
  );
}
