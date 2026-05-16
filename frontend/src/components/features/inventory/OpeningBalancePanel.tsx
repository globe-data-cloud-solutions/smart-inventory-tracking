"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { getSession } from "@/lib/demo-auth";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

interface Props {
  products: DemoProduct[];
  warehouses: DemoWarehouse[];
  orgSlug: string;
}

type FormState = {
  warehouseId: string;
  productId: string;
  quantity: string;
  lotNumber: string;
  manufactureDate: string;
  expiryDate: string;
  notes: string;
  referenceDocument: string;
};

const PANEL_W = 440;

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label
        style={{
          display: "block",
          fontSize: 12,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: "#374151",
          marginBottom: 4,
        }}
      >
        {label}
        {hint && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 400,
              textTransform: "none",
              color: "#9CA3AF",
              marginLeft: 6,
            }}
          >
            {hint}
          </span>
        )}
      </label>
      {children}
    </div>
  );
}

const INPUT: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  fontSize: 13,
  border: "1px solid #D1D5DB",
  borderRadius: 4,
  outline: "none",
  background: "#fff",
  boxSizing: "border-box",
};

const INPUT_LOCKED: React.CSSProperties = {
  ...INPUT,
  background: "#F3F4F6",
  color: "#6B7280",
  cursor: "not-allowed",
};

const SELECT: React.CSSProperties = { ...INPUT, cursor: "pointer" };

export function OpeningBalancePanel({ products, warehouses, orgSlug }: Props) {
  const qc = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const logAudit = useAuditStore((s) => s.log);
  const user = getSession();

  // Pre-fill warehouse if user is locked to one
  const lockedWarehouseId = user?.warehouseId ?? "";

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>({
    warehouseId: lockedWarehouseId,
    productId: "",
    quantity: "",
    lotNumber: "",
    manufactureDate: "",
    expiryDate: "",
    notes: "",
    referenceDocument: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  // Filter warehouses — prefer MWH for opening balances; fall back to all if no MWH
  const mwhWarehouses = warehouses.filter((w) => w.type === "MWH");
  const availableWarehouses = mwhWarehouses.length > 0 ? mwhWarehouses : warehouses;

  const selectedProduct = products.find((p) => p.id === form.productId);
  const requiresBatch = selectedProduct?.batchTracking === true;

  function reset() {
    setForm({
      warehouseId: lockedWarehouseId,
      productId: "",
      quantity: "",
      lotNumber: "",
      manufactureDate: "",
      expiryDate: "",
      notes: "",
      referenceDocument: "",
    });
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

    if (!user) { setError("No session found — please log in again."); return; }
    if (!form.warehouseId) { setError("Please select a warehouse."); return; }
    if (!form.productId)   { setError("Please select a product."); return; }

    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0) { setError("Quantity must be a positive number."); return; }

    if (requiresBatch) {
      if (!form.lotNumber)     { setError("Lot / Batch Number is required for batch-tracked products."); return; }
      if (!form.manufactureDate) { setError("Manufacture Date is required for batch-tracked products."); return; }
    }

    const product   = products.find((p) => p.id === form.productId);
    const warehouse = availableWarehouses.find((w) => w.id === form.warehouseId)
      ?? warehouses.find((w) => w.id === form.warehouseId);

    const idempotencyKey = `ob:${form.productId}:${form.warehouseId}:${Date.now()}:${nanoid(8)}`;

    const payload = {
      warehouse_id:       form.warehouseId,
      warehouse_name:     warehouse?.name ?? form.warehouseId,
      product_id:         form.productId,
      product_name:       product?.name ?? form.productId,
      product_sku:        product?.sku ?? "",
      quantity:           qty,
      uom:                product?.unit ?? "units",
      batch_number:       form.lotNumber || null,
      manufacture_date:   form.manufactureDate || null,
      expiry_date:        form.expiryDate || null,
      notes:              form.notes || "",
      reference_document: form.referenceDocument || null,
      idempotency_key:    idempotencyKey,
      created_by:         user.email,
    };

    setLoading(true);
    try {
      await api.post("/api/v1/receipts/opening-balance", payload);

      // Update balance immediately in the Zustand store (demo simulation of POSTED)
      addReceive(form.productId, form.warehouseId, qty);

      logAudit({
        tenantSlug:   orgSlug,
        userEmail:    user.email,
        userName:     user.name,
        role:         user.role,
        action:       "inventory:opening_balance",
        category:     "INVENTORY",
        resourceRef:  product?.sku ?? form.productId,
        resourceType: "OpeningBalanceReceipt",
        productName:  product?.name,
        quantityStr:  `+${qty.toLocaleString()} ${product?.unit ?? "units"}`,
        toWarehouse:  warehouse?.name ?? form.warehouseId,
        notes:        form.notes || undefined,
      });

      void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
      void qc.invalidateQueries({ queryKey: ["receipts", orgSlug] });

      setSuccess(
        `Opening Balance receipt created — status: PENDING_APPROVAL. Submit this to your National Manager for approval.`
      );
      reset();
      setTimeout(() => { setSuccess(""); setOpen(false); }, 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create receipt.");
    } finally {
      setLoading(false);
    }
  };

  if (!user) return null;

  return (
    <>
      <button
        onClick={() => { reset(); setOpen(true); }}
        style={{
          padding: "8px 16px",
          background: "#1E40AF",
          color: "#fff",
          fontWeight: 700,
          fontSize: 13,
          borderRadius: 4,
          border: "none",
          cursor: "pointer",
        }}
      >
        + Opening Balance
      </button>

      {/* Backdrop */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            zIndex: 100,
            backdropFilter: "blur(2px)",
          }}
        />
      )}

      {/* Slide-in panel */}
      <div
        style={{
          position: "fixed",
          top: 0,
          right: open ? 0 : -PANEL_W,
          width: PANEL_W,
          height: "100vh",
          background: "#fff",
          zIndex: 110,
          boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
          transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "1.25rem 1.5rem",
            background: "#1E40AF",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
          }}
        >
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>
              Opening Balance Receipt
            </p>
            <p style={{ fontSize: 12, color: "#BFDBFE", margin: "2px 0 0" }}>
              Initialize stock for a new product or go-live setup
            </p>
            <p
              style={{
                fontSize: 10,
                color: "#93C5FD",
                margin: "4px 0 0",
                fontFamily: "monospace",
                letterSpacing: "0.03em",
              }}
            >
              DRAFT → PENDING_APPROVAL → POSTED
            </p>
          </div>
          <button
            onClick={() => setOpen(false)}
            style={{
              background: "rgba(255,255,255,0.1)",
              border: "none",
              cursor: "pointer",
              color: "#fff",
              fontSize: 18,
              width: 32,
              height: 32,
              borderRadius: 4,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <form
          onSubmit={onSubmit}
          style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}
        >
          {/* Info banner */}
          <div
            style={{
              background: "#EFF6FF",
              border: "1px solid #BFDBFE",
              borderRadius: 6,
              padding: "10px 12px",
              fontSize: 12,
              color: "#1D4ED8",
              marginBottom: 20,
              lineHeight: 1.5,
            }}
          >
            <strong>Opening Balance</strong> receipts are used to initialise stock levels at
            go-live or when adding a new product. They follow the PULL approval workflow and
            require National Manager sign-off before posting.
          </div>

          <Field label="Warehouse">
            {lockedWarehouseId ? (
              <input
                type="text"
                value={
                  warehouses.find((w) => w.id === lockedWarehouseId)?.name ??
                  lockedWarehouseId
                }
                readOnly
                style={INPUT_LOCKED}
              />
            ) : (
              <select
                value={form.warehouseId}
                onChange={(e) => set("warehouseId", e.target.value)}
                style={SELECT}
                required
              >
                <option value="">— select warehouse —</option>
                {availableWarehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                    {w.type === "MWH" ? " (Main)" : w.type === "RWH" ? " (Regional)" : ""}
                    {w.location ? ` · ${w.location}` : ""}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <Field label="Product">
            <select
              value={form.productId}
              onChange={(e) => {
                set("productId", e.target.value);
                // Clear batch fields when product changes
                setForm((f) => ({
                  ...f,
                  productId: e.target.value,
                  lotNumber: "",
                  manufactureDate: "",
                  expiryDate: "",
                }));
              }}
              style={SELECT}
              required
            >
              <option value="">— select product —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.sku}
                  {p.batchTracking ? " [BATCH]" : ""}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Opening Quantity">
            <input
              type="number"
              min="1"
              step="any"
              value={form.quantity}
              onChange={(e) => set("quantity", e.target.value)}
              placeholder="e.g. 1000"
              style={INPUT}
              required
            />
          </Field>

          {/* Batch fields — only shown when product has batchTracking */}
          {requiresBatch && (
            <>
              <div
                style={{
                  background: "#F5F3FF",
                  border: "1px solid #DDD6FE",
                  borderRadius: 4,
                  padding: "8px 12px",
                  fontSize: 11,
                  color: "#5B21B6",
                  fontWeight: 600,
                  marginBottom: 14,
                }}
              >
                BATCH TRACKED — lot details required
              </div>

              <Field label="Lot / Batch Number">
                <input
                  type="text"
                  value={form.lotNumber}
                  onChange={(e) => set("lotNumber", e.target.value)}
                  placeholder="e.g. LOT-2026-001"
                  style={INPUT}
                  required
                />
              </Field>

              <Field label="Manufacture Date">
                <input
                  type="date"
                  value={form.manufactureDate}
                  onChange={(e) => set("manufactureDate", e.target.value)}
                  style={INPUT}
                  required
                />
              </Field>
            </>
          )}

          <Field
            label="Expiry Date"
            hint={requiresBatch ? "required" : "optional"}
          >
            <input
              type="date"
              value={form.expiryDate}
              onChange={(e) => set("expiryDate", e.target.value)}
              style={INPUT}
              required={requiresBatch}
            />
          </Field>

          <Field label="Notes" hint="optional">
            <textarea
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="e.g. Initial go-live stock count"
              rows={2}
              style={{ ...INPUT, resize: "vertical" }}
            />
          </Field>

          <Field label="Reference Document" hint="optional">
            <input
              type="text"
              value={form.referenceDocument}
              onChange={(e) => set("referenceDocument", e.target.value)}
              placeholder="e.g. PHYS-COUNT-2026-001"
              style={INPUT}
            />
          </Field>

          {error && (
            <div
              style={{
                background: "#FEF2F2",
                border: "1px solid #FECACA",
                borderRadius: 4,
                padding: "10px 12px",
                fontSize: 13,
                color: "#DC2626",
                marginBottom: 12,
              }}
            >
              {error}
            </div>
          )}

          {success && (
            <div
              style={{
                background: "#EFF6FF",
                border: "1px solid #BFDBFE",
                borderRadius: 4,
                padding: "10px 12px",
                fontSize: 13,
                color: "#1D4ED8",
                marginBottom: 12,
                lineHeight: 1.5,
              }}
            >
              ✓ {success}
            </div>
          )}
        </form>

        {/* Footer */}
        <div
          style={{
            padding: "1rem 1.5rem",
            borderTop: "1px solid #E5E7EB",
            display: "flex",
            gap: 10,
          }}
        >
          <button
            type="button"
            onClick={() => { reset(); setOpen(false); }}
            style={{
              flex: 1,
              padding: "10px",
              background: "#F3F4F6",
              border: "1px solid #E5E7EB",
              borderRadius: 4,
              fontSize: 13,
              fontWeight: 600,
              color: "#374151",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={onSubmit as unknown as React.MouseEventHandler}
            disabled={loading}
            style={{
              flex: 2,
              padding: "10px",
              fontWeight: 700,
              fontSize: 13,
              borderRadius: 4,
              border: "none",
              cursor: loading ? "not-allowed" : "pointer",
              background: "#1E40AF",
              color: "#fff",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "Submitting…" : "Submit Opening Balance"}
          </button>
        </div>
      </div>
    </>
  );
}
