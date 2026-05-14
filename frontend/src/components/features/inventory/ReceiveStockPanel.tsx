"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { enqueueOfflineTransaction } from "@/store/offlineQueue";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useScanner } from "@/hooks/useScanner";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { getSession } from "@/lib/demo-auth";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

interface Props {
  products: DemoProduct[];
  warehouses: DemoWarehouse[];
  orgSlug: string;
}

const REFERENCE_TYPES = [
  { value: "PURCHASE_ORDER", label: "Purchase Order" },
  { value: "PRODUCTION",     label: "Production Output" },
  { value: "RETURN",         label: "Customer / Supplier Return" },
  { value: "DONATION",       label: "Donation" },
  { value: "MANUAL",         label: "Manual Entry" },
];

type FormState = {
  productId: string;
  warehouseId: string;
  referenceType: string;
  quantity: string;
  lotNumber: string;
  expiryDate: string;
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

const INPUT = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #D1D5DB", borderRadius: 4,
  outline: "none", background: "#fff", boxSizing: "border-box" as const,
};

const SELECT = { ...INPUT, cursor: "pointer" };

export function ReceiveStockPanel({ products, warehouses, orgSlug }: Props) {
  const { isOnline } = useOfflineSync();
  const qc = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const logAudit   = useAuditStore((s) => s.log);

  const [open, setOpen]           = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scanHint, setScanHint]   = useState("");
  const [form, setForm] = useState<FormState>({
    productId: "", warehouseId: "", referenceType: "", quantity: "", lotNumber: "", expiryDate: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  // Barcode scan handler — look up product by SKU
  const onScan = useCallback((code: string) => {
    const found = products.find(
      (p) => p.sku === code || p.sku.toLowerCase() === code.toLowerCase()
    );
    if (found) {
      setForm((f) => ({ ...f, productId: found.id }));
      setScanHint(`✓ Found: ${found.name}`);
      setScannerOpen(false);
    } else {
      setScanHint(`No product matched: ${code}`);
    }
  }, [products]);

  const { videoRef, isActive: scanActive, error: scanError, start: startScan, stop: stopScan } = useScanner(onScan);

  function reset() {
    setForm({ productId: "", warehouseId: "", referenceType: "", quantity: "", lotNumber: "", expiryDate: "" });
    setError(""); setSuccess(""); setScanHint(""); setScannerOpen(false); stopScan();
  }

  function set(key: keyof FormState, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
    setError("");
  }

  function toggleScanner() {
    if (scannerOpen) { stopScan(); setScannerOpen(false); }
    else { setScannerOpen(true); void startScan(); }
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!form.productId)       { setError("Please select a product."); return; }
    if (!form.warehouseId)     { setError("Please select a warehouse."); return; }
    if (!form.referenceType)   { setError("Please select a reference type."); return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0) { setError("Quantity must be a positive number."); return; }

    const product = products.find((p) => p.id === form.productId);
    const key = `receive:${form.productId}:${form.warehouseId}:${Date.now()}:${nanoid(8)}`;
    const payload = {
      product_id:      form.productId,
      warehouse_id:    form.warehouseId,
      reference_type:  form.referenceType,
      quantity:        qty.toFixed(4),
      lot_number:      form.lotNumber || undefined,
      expiry_date:     form.expiryDate || undefined,
      idempotency_key: key,
    };

    setLoading(true);
    try {
      if (!isOnline) {
        await enqueueOfflineTransaction({ idempotencyKey: key, action: "inventory:receive", payload });
        setSuccess(`${product?.name ?? "Stock"} queued for sync when back online.`);
      } else {
        await api.post("/api/v1/inventory/receive", payload);
        addReceive(form.productId, form.warehouseId, qty);
        const user = getSession();
        const wh   = warehouses.find((w) => w.id === form.warehouseId);
        if (user) {
          logAudit({
            tenantSlug: orgSlug, userEmail: user.email, userName: user.name, role: user.role,
            action: "inventory:receive", category: "INVENTORY",
            resourceRef: product?.sku ?? form.productId, resourceType: "InventoryTransaction",
            details: `+${qty.toLocaleString()} ${product?.unit ?? "units"} ${product?.name ?? ""} → ${wh?.name ?? form.warehouseId}`,
          });
        }
        setSuccess(`${product?.name ?? "Stock"} received successfully.`);
        void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
        void qc.invalidateQueries({ queryKey: ["receipts", orgSlug] });
      }
      reset();
      setTimeout(() => { setSuccess(""); setOpen(false); }, 2500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to receive stock.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={() => { reset(); setOpen(true); }}
        style={{
          padding: "8px 16px", background: "#1B4332", color: "#FCDD09",
          fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer",
        }}
      >
        + Receive Stock
      </button>

      {/* Backdrop */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)",
            zIndex: 100, backdropFilter: "blur(2px)",
          }}
        />
      )}

      {/* Slide-in panel */}
      <div style={{
        position: "fixed", top: 0, right: open ? 0 : -PANEL_W,
        width: PANEL_W, height: "100vh", background: "#fff", zIndex: 110,
        boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
        transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{
          padding: "1.25rem 1.5rem", background: "#1B4332",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>Receive Stock</p>
            <p style={{ fontSize: 12, color: "#6ee7b7", margin: "2px 0 0" }}>
              {isOnline ? "Online — will post immediately" : "Offline — will queue for sync"}
            </p>
          </div>
          <button onClick={() => setOpen(false)} style={{
            background: "rgba(255,255,255,0.1)", border: "none", cursor: "pointer",
            color: "#fff", fontSize: 18, width: 32, height: 32, borderRadius: 4,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>✕</button>
        </div>

        {/* Body */}
        <form onSubmit={onSubmit} style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
          {/* Barcode scanner toggle */}
          <div style={{ marginBottom: 16 }}>
            <button
              type="button"
              onClick={toggleScanner}
              style={{
                width: "100%", padding: "9px", borderRadius: 4, cursor: "pointer",
                border: `2px dashed ${scannerOpen ? "#059669" : "#D1D5DB"}`,
                background: scannerOpen ? "#F0FDF4" : "#F9FAFB",
                color: scannerOpen ? "#059669" : "#6B7280",
                fontSize: 13, fontWeight: 600,
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              }}
            >
              <span style={{ fontSize: 16 }}>{scannerOpen ? "■" : "⬛"}</span>
              {scannerOpen ? "Stop Scanner" : "Scan Barcode to Find Product"}
            </button>
            {scannerOpen && (
              <div style={{ marginTop: 8, borderRadius: 6, overflow: "hidden", background: "#000", position: "relative" }}>
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <video ref={videoRef} style={{ width: "100%", height: 180, objectFit: "cover", display: "block" }} playsInline muted />
                {!scanActive && (
                  <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.5)", color: "#fff", fontSize: 13 }}>
                    Starting camera…
                  </div>
                )}
              </div>
            )}
            {scanError && <p style={{ fontSize: 12, color: "#DC2626", marginTop: 4 }}>{scanError}</p>}
            {scanHint  && (
              <p style={{ fontSize: 12, marginTop: 4, color: scanHint.startsWith("✓") ? "#059669" : "#DC2626", fontWeight: 600 }}>
                {scanHint}
              </p>
            )}
          </div>

          <Field label="Product" >
            <select value={form.productId} onChange={(e) => set("productId", e.target.value)} style={SELECT} required>
              <option value="">— select product —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>
              ))}
            </select>
          </Field>

          <Field label="Warehouse">
            <select value={form.warehouseId} onChange={(e) => set("warehouseId", e.target.value)} style={SELECT} required>
              <option value="">— select warehouse —</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}{w.location ? ` · ${w.location}` : ""}</option>
              ))}
            </select>
          </Field>

          <Field label="Reference Type">
            <select value={form.referenceType} onChange={(e) => set("referenceType", e.target.value)} style={SELECT} required>
              <option value="">— select type —</option>
              {REFERENCE_TYPES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </Field>

          <Field label="Quantity">
            <input
              type="number" min="0.0001" step="any"
              value={form.quantity}
              onChange={(e) => set("quantity", e.target.value)}
              placeholder="e.g. 500"
              style={INPUT}
              required
            />
          </Field>

          <Field label="Lot / Batch Number" hint="optional">
            <input
              type="text" value={form.lotNumber}
              onChange={(e) => set("lotNumber", e.target.value)}
              placeholder="e.g. LOT-2026-001"
              style={INPUT}
            />
          </Field>

          <Field label="Expiry Date" hint="optional">
            <input
              type="date" value={form.expiryDate}
              onChange={(e) => set("expiryDate", e.target.value)}
              style={INPUT}
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

        {/* Footer */}
        <div style={{
          padding: "1rem 1.5rem", borderTop: "1px solid #E5E7EB",
          display: "flex", gap: 10,
        }}>
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
              background: isOnline ? "#1B4332" : "#92400E",
              color: "#FCDD09", opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "Processing…" : isOnline ? "Receive Stock" : "Queue for Sync"}
          </button>
        </div>
      </div>
    </>
  );
}
