"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { useInventoryStore, type TransferEntry } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { getSession } from "@/lib/demo-auth";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

/** All facilities ABOVE warehouseId in the parentId chain (valid PULL sources). */
function getAncestorScope(warehouseId: string, warehouses: DemoWarehouse[]): string[] {
  const ancestors: string[] = [];
  let cur = warehouses.find((w) => w.id === warehouseId);
  while (cur?.parentId) {
    ancestors.push(cur.parentId);
    cur = warehouses.find((w) => w.id === cur!.parentId);
  }
  return ancestors;
}

/** warehouseId + all facilities BELOW it in the parentId chain (valid PUSH destinations). */
function getDescendantScope(warehouseId: string, warehouses: DemoWarehouse[]): string[] {
  const scope = new Set<string>([warehouseId]);
  function add(pid: string) {
    for (const wh of warehouses) {
      if (wh.parentId === pid && !scope.has(wh.id)) {
        scope.add(wh.id);
        add(wh.id);
      }
    }
  }
  add(warehouseId);
  return Array.from(scope).filter((id) => id !== warehouseId); // exclude self
}

interface Props {
  products: DemoProduct[];
  warehouses: DemoWarehouse[];
  orgSlug: string;
}

type TransferType = "PULL" | "PUSH" | "SISTER";

type FormState = {
  transferType: TransferType;
  productId: string;
  fromWarehouseId: string;
  toWarehouseId: string;
  quantity: string;
  notes: string;
};

const PANEL_W = 440;

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

const INPUT: React.CSSProperties = {
  width: "100%", padding: "8px 10px", fontSize: 13,
  border: "1px solid #D1D5DB", borderRadius: 4,
  outline: "none", background: "#fff", boxSizing: "border-box",
};
const SELECT: React.CSSProperties = { ...INPUT, cursor: "pointer" };
const LOCKED: React.CSSProperties = { ...INPUT, background: "#F3F4F6", color: "#6B7280", cursor: "not-allowed" };

export function NewTransferPanel({ products, warehouses, orgSlug }: Props) {
  const qc          = useQueryClient();
  const addTransfer = useInventoryStore((s) => s.addTransfer);
  const logAudit    = useAuditStore((s) => s.log);

  const user    = getSession();
  const lockedWH = user?.warehouseId; // set for WM / NM at a specific facility
  const userWH   = warehouses.find((w) => w.id === lockedWH);

  // MWH and RWH facilities can PUSH; WH/SUB_WH cannot initiate PUSH
  const canPush = !lockedWH || (userWH && ["MWH", "RWH"].includes(userWH.type));

  const defaultType: TransferType = canPush ? "PUSH" : "PULL";

  function initialForm(type: TransferType): FormState {
    // PULL:   user's WH is the TO (they request stock to come TO them)
    // SISTER: user's WH is the TO (they initiate a lateral request, stock comes TO them)
    // PUSH:   user's WH is the FROM (they send stock FROM themselves downward)
    const toShouldLock   = type === "PULL" || type === "SISTER";
    const fromShouldLock = type === "PUSH";
    return {
      transferType: type,
      productId: "",
      fromWarehouseId: (fromShouldLock && lockedWH) ? lockedWH : "",
      toWarehouseId:   (toShouldLock   && lockedWH) ? lockedWH : "",
      quantity: "",
      notes: "",
    };
  }

  const [open, setOpen]       = useState(false);
  const [form, setForm]       = useState<FormState>(initialForm(defaultType));
  const [error, setError]     = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  function reset() {
    setForm(initialForm(form.transferType));
    setError("");
    setSuccess("");
  }

  function setField(key: keyof FormState, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
    setError("");
  }

  function changeType(type: TransferType) {
    setForm(initialForm(type));
    setError("");
  }

  // Derived: which fields are locked to the user's own warehouse
  const isPull      = form.transferType === "PULL";
  const isSister    = form.transferType === "SISTER";
  const isPush      = form.transferType === "PUSH";
  // PULL + SISTER: destination locked to user's WH (they're the requestor)
  // PUSH: origin locked to user's WH (they're the sender)
  const toIsLocked   = !!lockedWH && (isPull || isSister);
  const fromIsLocked = !!lockedWH && isPush;

  // Effective values (locked values always win)
  const effectiveFrom = fromIsLocked ? (lockedWH ?? "") : form.fromWarehouseId;
  const effectiveTo   = toIsLocked   ? (lockedWH ?? "") : form.toWarehouseId;

  // Hierarchy-aware option filtering
  const ancestorIds    = lockedWH ? getAncestorScope(lockedWH, warehouses)    : null;
  const descendantIds  = lockedWH ? getDescendantScope(lockedWH, warehouses)  : null;
  const isPush         = form.transferType === "PUSH";

  const fromOptions = warehouses.filter((w) => {
    if (w.id === effectiveTo)                    return false; // never same as To
    if (lockedWH && w.id === lockedWH)           return false; // own WH excluded from free fields
    // PULL: From must be a valid supply source (ancestor in hierarchy)
    if (isPull && lockedWH && ancestorIds && ancestorIds.length > 0) {
      return ancestorIds.includes(w.id);
    }
    return true;
  });

  const toOptions = warehouses.filter((w) => {
    if (w.id === effectiveFrom)                  return false;
    if (lockedWH && w.id === lockedWH)           return false;
    // PUSH: To must be a valid downstream destination (descendant in hierarchy)
    if (isPush && lockedWH && descendantIds && descendantIds.length > 0) {
      return descendantIds.includes(w.id);
    }
    return true;
  });

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!form.productId)   { setError("Please select a product."); return; }
    if (!effectiveFrom)    { setError("Please select the origin warehouse."); return; }
    if (!effectiveTo)      { setError("Please select the destination warehouse."); return; }
    if (effectiveFrom === effectiveTo) { setError("Origin and destination must be different."); return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0)  { setError("Quantity must be a positive number."); return; }

    const product = products.find((p) => p.id === form.productId);
    const fromWH  = warehouses.find((w) => w.id === effectiveFrom);
    const toWH    = warehouses.find((w) => w.id === effectiveTo);

    setLoading(true);
    try {
      const created = await api.post<{ id: string; ref: string }>("/api/v1/transfers", {
        transfer_type:       form.transferType,
        product_id:          form.productId,
        product_name:        product?.name,
        from_warehouse_id:   effectiveFrom,
        from_warehouse_name: fromWH?.name,
        to_warehouse_id:     effectiveTo,
        to_warehouse_name:   toWH?.name,
        quantity:            qty,
        notes:               form.notes,
        idempotency_key: `transfer:${form.productId}:${effectiveFrom}:${effectiveTo}:${Date.now()}:${nanoid(8)}`,
      });

      const entry: TransferEntry = {
        id:                created.id,
        ref:               created.ref,
        productId:         form.productId,
        fromWarehouseId:   effectiveFrom,
        fromWarehouseName: fromWH?.name ?? effectiveFrom,
        toWarehouseId:     effectiveTo,
        toWarehouseName:   toWH?.name ?? effectiveTo,
        quantity:          qty,
        issuedDate:        new Date().toISOString(),
        status:            "DRAFT",
      };
      addTransfer(entry);

      if (user) {
        logAudit({
          tenantSlug:    orgSlug,
          userEmail:     user.email,
          userName:      user.name,
          role:          user.role,
          action:        "transfer:DRAFT",
          category:      "TRANSFER",
          resourceRef:   created.ref,
          resourceType:  "TransferOrder",
          productName:   product?.name,
          quantityStr:   `${qty.toLocaleString()} ${product?.unit ?? "units"}`,
          fromWarehouse: fromWH?.name,
          toWarehouse:   toWH?.name,
          notes:         `[${form.transferType}]${form.notes ? " " + form.notes : ""}`,
        });
      }

      setSuccess(`Transfer ${created.ref} created — ${fromWH?.name} → ${toWH?.name}.`);
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
        style={{ padding: "8px 16px", background: "#FCDD09", color: "#0f2d1f", fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer" }}
      >
        + New Transfer
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
        {/* Header */}
        <div style={{ padding: "1.25rem 1.5rem", background: "#0f2d1f", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>New Stock Transfer</p>
            <p style={{ fontSize: 12, color: "#6ee7b7", margin: "2px 0 0" }}>Creates a DRAFT transfer order</p>
          </div>
          <button onClick={() => setOpen(false)} style={{ background: "rgba(255,255,255,0.1)", border: "none", cursor: "pointer", color: "#fff", fontSize: 18, width: 32, height: 32, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
        </div>

        <form onSubmit={onSubmit} style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>

          {/* Transfer Type */}
          <Field label="Transfer Type">
            <select
              value={form.transferType}
              onChange={(e) => changeType(e.target.value as TransferType)}
              style={SELECT}
            >
              <option value="PULL">PULL — Request stock from a higher-level facility (MWH/RWH)</option>
              {canPush && <option value="PUSH">PUSH — Send stock down to a lower-level facility</option>}
              <option value="SISTER">SISTER — Request stock from a peer warehouse (you receive, they send)</option>
            </select>
          </Field>

          {/* Scope note for WM */}
          {lockedWH && (
            <div style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 4, padding: "8px 12px", fontSize: 12, color: "#166534", marginBottom: 16 }}>
              {isPush
                ? `📤 Stock will be sent FROM: ${userWH?.name ?? lockedWH}`
                : isSister
                  ? `↔ Lateral request — stock will come TO: ${userWH?.name ?? lockedWH} (your WH)`
                  : `📥 Stock will be requested TO: ${userWH?.name ?? lockedWH}`}
            </div>
          )}

          {/* Product */}
          <Field label="Product">
            <select value={form.productId} onChange={(e) => setField("productId", e.target.value)} style={SELECT} required>
              <option value="">— select product —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>
              ))}
            </select>
          </Field>

          {/* From Warehouse */}
          <Field label={isPull || isSister ? "From Warehouse (supply source)" : "From Warehouse"} hint={fromIsLocked ? "your facility" : undefined}>
            {fromIsLocked ? (
              <input value={userWH?.name ?? lockedWH ?? ""} disabled style={LOCKED} />
            ) : (
              <select value={form.fromWarehouseId} onChange={(e) => setField("fromWarehouseId", e.target.value)} style={SELECT} required>
                <option value="">— origin —</option>
                {fromOptions.map((w) => (
                  <option key={w.id} value={w.id}>{w.name} ({w.type})</option>
                ))}
              </select>
            )}
          </Field>

          {/* To Warehouse */}
          <Field label={isPull || isSister ? "To Warehouse (your warehouse)" : "To Warehouse (destination)"} hint={toIsLocked ? "your facility — locked" : undefined}>
            {toIsLocked ? (
              <input value={userWH?.name ?? lockedWH ?? ""} disabled style={LOCKED} />
            ) : (
              <select value={form.toWarehouseId} onChange={(e) => setField("toWarehouseId", e.target.value)} style={SELECT} required>
                <option value="">— destination —</option>
                {toOptions.map((w) => (
                  <option key={w.id} value={w.id}>{w.name} ({w.type})</option>
                ))}
              </select>
            )}
          </Field>

          {/* Quantity */}
          <Field label="Quantity">
            <input
              type="number" min="1" step="1"
              value={form.quantity}
              onChange={(e) => setField("quantity", e.target.value)}
              placeholder="e.g. 1455"
              style={INPUT}
              required
            />
          </Field>

          {/* Notes */}
          <Field label="Notes" hint="optional">
            <textarea
              value={form.notes}
              onChange={(e) => setField("notes", e.target.value)}
              placeholder="Reason for transfer, special instructions…"
              rows={3}
              style={{ ...INPUT, resize: "vertical" }}
            />
          </Field>

          {error   && <div style={{ background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 4, padding: "10px 12px", fontSize: 13, color: "#DC2626", marginBottom: 12 }}>{error}</div>}
          {success && <div style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 4, padding: "10px 12px", fontSize: 13, color: "#059669", marginBottom: 12 }}>✓ {success}</div>}
        </form>

        <div style={{ padding: "1rem 1.5rem", borderTop: "1px solid #E5E7EB", display: "flex", gap: 10 }}>
          <button type="button" onClick={() => setOpen(false)} style={{ flex: 1, padding: "10px", background: "#F3F4F6", border: "1px solid #E5E7EB", borderRadius: 4, fontSize: 13, fontWeight: 600, color: "#374151", cursor: "pointer" }}>
            Cancel
          </button>
          <button
            onClick={onSubmit as unknown as React.MouseEventHandler}
            disabled={loading}
            style={{ flex: 2, padding: "10px", fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: loading ? "not-allowed" : "pointer", background: "#0f2d1f", color: "#FCDD09", opacity: loading ? 0.7 : 1 }}
          >
            {loading ? "Creating…" : "Create Transfer"}
          </button>
        </div>
      </div>
    </>
  );
}
