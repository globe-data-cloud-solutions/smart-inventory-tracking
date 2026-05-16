"use client";

import { useState, useRef, useEffect } from "react";
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

/* ── Tier helpers ─────────────────────────────────────────────────────────── */
const TIER_COLOR = ["#111827", "#D97706", "#DC2626"] as const;
const TIER_BG    = ["#F0FDF4", "#FFFBEB", "#FEF2F2"] as const;
const TIER_ICON  = ["",        "⚠",       "✕"       ] as const;

function stockTier(avail: number, reorderPoint: number): 0 | 1 | 2 {
  if (avail < 0)                                   return 2;
  if (reorderPoint > 0 && avail <= reorderPoint)   return 1;
  return 0;
}

interface ProductOption {
  id: string; name: string; sku: string;
  avail: number; tier: 0 | 1 | 2; sourceKnown: boolean;
}

/** Custom color-coded product dropdown.
 *  Tier 0 = ok (black) · Tier 1 = below reorder (orange) · Tier 2 = negative (red).
 *  Red items are sorted to the bottom of the list.
 */
function ProductSelect({
  options, value, onChange,
}: {
  options: ProductOption[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const selected = options.find((o) => o.id === value);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", padding: "8px 10px", fontSize: 13,
          border: "1px solid #D1D5DB", borderRadius: 4, background: "#fff",
          textAlign: "left", cursor: "pointer", outline: "none",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
        }}
      >
        {selected ? (
          <span style={{ flex: 1, overflow: "hidden" }}>
            <span style={{ color: TIER_COLOR[selected.tier], fontWeight: 600 }}>
              {TIER_ICON[selected.tier] && <span style={{ marginRight: 4 }}>{TIER_ICON[selected.tier]}</span>}
              {selected.name}
            </span>
            <span style={{ color: "#9CA3AF", fontSize: 11, marginLeft: 6 }}>{selected.sku}</span>
          </span>
        ) : (
          <span style={{ color: "#9CA3AF", flex: 1 }}>— select product —</span>
        )}
        <span style={{ color: "#9CA3AF", fontSize: 10, flexShrink: 0 }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0, zIndex: 300,
          background: "#fff", border: "1px solid #D1D5DB", borderRadius: 4,
          boxShadow: "0 6px 20px rgba(0,0,0,0.14)", maxHeight: 300, overflowY: "auto",
        }}>
          {options.length === 0 && (
            <p style={{ padding: "12px", color: "#9CA3AF", fontSize: 13, textAlign: "center" }}>
              No products
            </p>
          )}
          {options.map((o) => (
            <div
              key={o.id}
              onMouseDown={() => { onChange(o.id); setOpen(false); }}
              style={{
                padding: "9px 10px", cursor: "pointer", fontSize: 13,
                borderBottom: "1px solid #F3F4F6",
                background: o.id === value ? TIER_BG[o.tier] : "transparent",
                display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
              }}
            >
              <span style={{ flex: 1, overflow: "hidden" }}>
                <span style={{ color: TIER_COLOR[o.tier], fontWeight: o.tier > 0 ? 600 : 500 }}>
                  {TIER_ICON[o.tier] && <span style={{ marginRight: 4 }}>{TIER_ICON[o.tier]}</span>}
                  {o.name}
                </span>
                <span style={{ color: "#9CA3AF", fontSize: 11, marginLeft: 6 }}>{o.sku}</span>
              </span>
              {o.sourceKnown && (
                <span style={{
                  fontSize: 11, fontWeight: 700, flexShrink: 0,
                  color: TIER_COLOR[o.tier],
                  background: TIER_BG[o.tier],
                  padding: "2px 7px", borderRadius: 3,
                }}>
                  {o.avail < 0 ? o.avail.toLocaleString() : `+${o.avail.toLocaleString()}`}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────────────────── */
export function NewTransferPanel({ products, warehouses, orgSlug }: Props) {
  const qc          = useQueryClient();
  const { addTransfer, getAvailable, getOnHand } = useInventoryStore();
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
  const [stockAlert, setStockAlert] = useState<{
    fromWHName: string; productName: string;
    onHand: number; available: number; requested: number;
    canForce: boolean;
  } | null>(null);

  function reset() {
    setForm(initialForm(form.transferType));
    setError("");
    setSuccess("");
    setStockAlert(null);
  }

  function setField(key: keyof FormState, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
    setError("");
    setStockAlert(null);
  }

  function changeType(type: TransferType) {
    setForm(initialForm(type));
    setError("");
    setStockAlert(null);
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

  // ── Computed product options — colour-coded and sorted by availability tier ──
  const productOptions: ProductOption[] = [...products]
    .map((p) => {
      const base  = effectiveFrom ? (p.stock[effectiveFrom] ?? 0) : 0;
      const avail = effectiveFrom ? getAvailable(p.id, effectiveFrom, base) : 0;
      return {
        id: p.id, name: p.name, sku: p.sku,
        avail,
        tier: effectiveFrom ? stockTier(avail, p.reorderPoint) : 0,
        sourceKnown: !!effectiveFrom,
      } as ProductOption;
    })
    .sort((a, b) => a.tier - b.tier || a.name.localeCompare(b.name));

  async function doCreate(skipStockCheck: boolean) {
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

    // ── Insufficient balance guard ────────────────────────────────────────────
    // PUSH: hard block — you can't send what you don't have.
    // PULL / SISTER: soft warning — user may override because the approval
    //   workflow can still handle the request at a source with limited stock.
    if (!skipStockCheck && product && effectiveFrom) {
      const baseStock  = product.stock[effectiveFrom] ?? 0;
      const liveOnHand = getOnHand(product.id, effectiveFrom, baseStock);
      const liveAvail  = getAvailable(product.id, effectiveFrom, baseStock);
      if (qty > liveAvail) {
        setStockAlert({
          fromWHName:  fromWH?.name ?? effectiveFrom,
          productName: product.name,
          onHand:      liveOnHand,
          available:   liveAvail,
          requested:   qty,
          canForce:    isPull || isSister,
        });
        return;
      }
    }

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
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void doCreate(false);
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

          {/* Product — color-coded by available balance at the source warehouse */}
          <Field label="Product"
            hint={effectiveFrom ? "orange = below reorder · red = negative" : "select source warehouse first to see availability"}>
            <ProductSelect
              options={productOptions}
              value={form.productId}
              onChange={(id) => setField("productId", id)}
            />
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

          {/* Insufficient stock alert — structured popup within the panel */}
          {stockAlert && (
            <div style={{ background: "#FEF2F2", border: "2px solid #DC2626", borderRadius: 6, padding: "12px 14px", marginBottom: 12 }}>
              <p style={{ fontWeight: 700, fontSize: 13, color: "#DC2626", margin: "0 0 8px", display: "flex", alignItems: "center", gap: 6 }}>
                ⛔ Insufficient Stock — {stockAlert.fromWHName}
              </p>
              <div style={{ fontSize: 12, color: "#374151", display: "flex", flexDirection: "column", gap: 3 }}>
                <div><strong>Product:</strong> {stockAlert.productName}</div>
                <div style={{ display: "flex", gap: 20 }}>
                  <span><strong>On Hand:</strong> {stockAlert.onHand.toLocaleString()} units</span>
                  <span><strong>Available:</strong>{" "}
                    <span style={{ color: "#DC2626", fontWeight: 700 }}>{stockAlert.available.toLocaleString()} units</span>
                  </span>
                </div>
                <div><strong>Requested:</strong> {stockAlert.requested.toLocaleString()} units
                  <span style={{ color: "#DC2626", marginLeft: 8 }}>
                    ({(stockAlert.requested - stockAlert.available).toLocaleString()} over available)
                  </span>
                </div>
              </div>
              {stockAlert.canForce ? (
                <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    onClick={() => { setStockAlert(null); void doCreate(true); }}
                    style={{ flex: 1, padding: "7px 12px", background: "#DC2626", color: "#fff", fontWeight: 700, fontSize: 12, borderRadius: 4, border: "none", cursor: "pointer" }}
                  >
                    Proceed anyway (PULL draft)
                  </button>
                  <button
                    type="button"
                    onClick={() => setStockAlert(null)}
                    style={{ padding: "7px 12px", background: "#F3F4F6", color: "#374151", fontWeight: 600, fontSize: 12, borderRadius: 4, border: "1px solid #D1D5DB", cursor: "pointer" }}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <p style={{ fontSize: 11, color: "#9CA3AF", margin: "8px 0 0" }}>
                  Reduce the quantity or choose a different source warehouse.
                </p>
              )}
            </div>
          )}

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
