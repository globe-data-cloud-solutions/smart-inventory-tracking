"use client";

import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { getSession } from "@/lib/demo-auth";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

interface Props { products: DemoProduct[]; warehouses: DemoWarehouse[]; orgSlug: string; }

const REASONS = [
  { value: "DAMAGE",            label: "adjustment.reasons.DAMAGE"            },
  { value: "COUNT_VARIANCE",    label: "adjustment.reasons.COUNT_VARIANCE"    },
  { value: "EXPIRY",            label: "adjustment.reasons.EXPIRY"            },
  { value: "SUPPLIER_RETURN",   label: "adjustment.reasons.SUPPLIER_RETURN"   },
  { value: "SYSTEM_CORRECTION", label: "adjustment.reasons.SYSTEM_CORRECTION" },
  { value: "OTHER",             label: "adjustment.reasons.OTHER"             },
];

// Bug 4A: These reasons always deduct stock — user enters magnitude, system negates
const FORCE_NEGATIVE = new Set(["DAMAGE", "EXPIRY", "SUPPLIER_RETURN"]);

const THRESHOLDS = { low: 100, medium: 1000 };

function getApprovalInfo(qty: number): { role: string; label: string; cls: string } {
  const abs = Math.abs(qty);
  if (abs < THRESHOLDS.low)    return { role: "NONE", label: t("adjustment.auto_applied"),  cls: "bg-green-50 text-emerald-700" };
  if (abs < THRESHOLDS.medium) return { role: "RM",   label: t("adjustment.pending_rm"),    cls: "bg-amber-50 text-amber-800" };
  return                              { role: "TA",   label: t("adjustment.pending_ta"),    cls: "bg-red-50 text-red-700" };
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
        {label}
        {hint && <span className="text-[11px] font-normal normal-case text-gray-400 ml-1.5">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

const inputCls  = "w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white";
const selectCls = `${inputCls} cursor-pointer`;

interface AdjResult { status: string; approval_required_role: string }

export function NewAdjustmentPanel({ products, warehouses, orgSlug }: Props) {
  const qc      = useQueryClient();
  const session = getSession();
  const isWM    = session?.role === "WM";

  const [open, setOpen]               = useState(false);
  const [productId, setProductId]     = useState("");
  const [warehouseId, setWarehouseId] = useState(""); // non-WM only
  const [addQty, setAddQty]           = useState("");
  const [removeQty, setRemoveQty]     = useState("");
  const [reason, setReason]           = useState("");
  const [notes, setNotes]             = useState("");
  const [error, setError]             = useState("");
  const [loading, setLoading]         = useState(false);
  const [toast, setToast]             = useState<{ msg: string; applied: boolean } | null>(null);
  const [zeroWarn, setZeroWarn]       = useState(false);

  // Bug 1: WM warehouse is always the JWT session warehouse — never a dropdown selection
  const effectiveWarehouseId   = isWM ? (session?.warehouseId ?? "") : warehouseId;
  const effectiveWarehouseName = isWM
    ? (session?.warehouseName ?? "")
    : warehouses.find((w) => w.id === warehouseId)?.name ?? "";

  const forceNeg  = FORCE_NEGATIVE.has(reason);
  const addNum    = parseFloat(addQty)    || 0;
  const removeNum = parseFloat(removeQty) || 0;
  // Bug 4A: DAMAGE/EXPIRY → always negative. Bug 4B: other reasons → add minus remove.
  const qty       = forceNeg ? -Math.abs(addNum) : addNum - removeNum;

  const approvalInfo = qty !== 0 ? getApprovalInfo(qty) : null;
  const selectedP    = products.find((p) => p.id === productId);

  function reset() {
    setProductId(""); setWarehouseId(""); setAddQty(""); setRemoveQty("");
    setReason(""); setNotes(""); setError(""); setZeroWarn(false);
  }

  // Bug 6: auto-dismiss toast and close panel after 3 s
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => { setToast(null); setOpen(false); }, 3000);
    return () => clearTimeout(id);
  }, [toast]);

  async function doSubmit(bypassZeroFloor = false) {
    setError("");

    if (!productId)            { setError(t("receive_panel.error_product"));   return; }
    if (!effectiveWarehouseId) { setError(t("receive_panel.error_warehouse")); return; }
    if (!reason)               { setError(t("issue.error_reason")); return; }
    if (forceNeg  && addNum === 0)                 { setError(t("adjustment.error_qty")); return; }
    if (!forceNeg && addNum === 0 && removeNum === 0) { setError(t("adjustment.error_qty")); return; }
    if (!forceNeg && addNum > 0 && removeNum > 0) {
      setError("Fill either Add Stock or Remove Stock, not both.");
      return;
    }

    // Bug 7: zero-floor guard — block WM, confirm for managers
    if (!bypassZeroFloor) {
      const store     = useInventoryStore.getState();
      const baseStock = selectedP?.stock?.[effectiveWarehouseId] ?? 0;
      const projected = store.getOnHand(productId, effectiveWarehouseId, baseStock) + qty;
      if (projected < 0) {
        if (isWM) {
          setError(t("adjustment.zero_floor_wm"));
          return;
        }
        setZeroWarn(true);
        return;
      }
    }

    setZeroWarn(false);
    const key = `adjust:${productId}:${effectiveWarehouseId}:${Date.now()}:${nanoid(8)}`;
    setLoading(true);
    try {
      const adj = await api.post<AdjResult>("/api/v1/inventory/adjust", {
        product_id:     productId,
        product_name:   selectedP?.name,
        product_sku:    selectedP?.sku,
        warehouse_id:   effectiveWarehouseId,
        warehouse_name: effectiveWarehouseName,
        quantity:       qty,
        reason_code:    reason,
        notes,
        idempotency_key: key,
      });

      // Bug 5: update Zustand inventory store when adjustment is auto-applied
      if (adj.status === "APPLIED") {
        const store = useInventoryStore.getState();
        if (qty > 0) store.addReceive(productId, effectiveWarehouseId, qty);
        else         store.addIssue(productId, effectiveWarehouseId, Math.abs(qty));
      }

      // Bug 8: write audit log entry
      if (session) {
        useAuditStore.getState().log({
          tenantSlug:    orgSlug,
          userEmail:     session.email,
          userName:      session.name,
          role:          session.role,
          category:      "ADJUSTMENT",
          action:        adj.status === "APPLIED" ? "ADJUSTMENT_APPLIED" : "ADJUSTMENT_SUBMITTED",
          resourceRef:   key,
          resourceType:  "adjustment",
          productName:   selectedP?.name,
          quantityStr:   `${qty > 0 ? "+" : ""}${qty}`,
          fromWarehouse: effectiveWarehouseName,
          notes,
        });
      }

      // Bug 6: show toast, reset form, auto-close in 3 s (via useEffect)
      reset();
      setToast({
        msg:     adj.status === "APPLIED" ? t("adjustment.success_applied") : t("adjustment.success_submitted"),
        applied: adj.status === "APPLIED",
      });
      void qc.invalidateQueries({ queryKey: ["adjustments", orgSlug] });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("errors.INTERNAL_ERROR"));
    } finally {
      setLoading(false);
    }
  }

  const onFormSubmit = (e: React.FormEvent) => { e.preventDefault(); void doSubmit(); };

  return (
    <>
      <button onClick={() => { reset(); setOpen(true); }} className="px-4 py-2 bg-cyan-600 text-white font-bold text-sm rounded border-0 cursor-pointer">
        {t("adjustment.new_btn")}
      </button>

      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 bg-black/35 z-[100] backdrop-blur-sm" />}

      <div className={`fixed top-0 right-0 w-[440px] h-screen bg-white z-[110] shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="px-6 py-5 bg-cyan-600 flex items-center justify-between">
          <div>
            <p className="font-bold text-base text-white m-0">{t("adjustment.title")}</p>
            <p className="text-xs text-cyan-100 mt-0.5">{t("adjustment.subtitle")}</p>
          </div>
          <button onClick={() => setOpen(false)} className="bg-white/15 border-0 cursor-pointer text-white text-lg w-8 h-8 rounded flex items-center justify-center">✕</button>
        </div>

        <form onSubmit={onFormSubmit} className="flex-1 overflow-y-auto p-6">
          {/* Bug 6: toast replaces full-screen result */}
          {toast && (
            <div className={`mb-4 px-4 py-3 rounded-md text-sm font-semibold flex items-center gap-2 ${toast.applied ? "bg-green-50 text-green-800 border border-green-200" : "bg-amber-50 text-amber-800 border border-amber-200"}`}>
              <span>{toast.applied ? "✓" : "⏳"}</span>
              {toast.msg}
            </div>
          )}

          <Field label={t("table.product")}>
            <select value={productId} onChange={(e) => setProductId(e.target.value)} className={selectCls} required>
              <option value="">— {t("receive_panel.select_product")} —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
            </select>
          </Field>

          {/* Bug 1: WM sees read-only warehouse from JWT; managers see dropdown */}
          <Field label={t("inventory.warehouse")}>
            {isWM ? (
              <div className={`${inputCls} bg-gray-50 text-gray-600 cursor-not-allowed border-dashed`}>
                {effectiveWarehouseName || "—"}
              </div>
            ) : (
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} className={selectCls} required>
                <option value="">— {t("receive_panel.select_warehouse")} —</option>
                {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            )}
          </Field>

          <Field label={t("adjustment.reason")}>
            <select
              value={reason}
              onChange={(e) => { setReason(e.target.value); setAddQty(""); setRemoveQty(""); }}
              className={selectCls}
              required
            >
              <option value="">— {t("receive_panel.select_type")} —</option>
              {REASONS.map((r) => <option key={r.value} value={r.value}>{t(r.label)}</option>)}
            </select>
          </Field>

          {reason && (
            forceNeg ? (
              /* Bug 4A: DAMAGE / EXPIRY — always a deduction, user enters positive magnitude */
              <Field label={t("adjustment.quantity")} hint={t("adjustment.quantity_hint_remove")}>
                <input
                  type="number" min="0" step="any"
                  value={addQty}
                  onChange={(e) => setAddQty(e.target.value)}
                  placeholder="e.g. 50"
                  className={inputCls}
                />
                {approvalInfo && (
                  <div className={`mt-1.5 px-2.5 py-1.5 rounded text-xs ${approvalInfo.cls}`}>
                    −{addNum || 0} units · {approvalInfo.label}
                  </div>
                )}
              </Field>
            ) : (
              /* Bug 4B: other reasons — two inputs, only one fillable at a time */
              <div className="mb-4">
                <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-2">
                  {t("adjustment.quantity")}
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-[11px] text-emerald-700 font-semibold mb-1">{t("adjustment.add_stock")}</p>
                    <input
                      type="number" min="0" step="any"
                      value={addQty}
                      onChange={(e) => { setAddQty(e.target.value); if (e.target.value) setRemoveQty(""); }}
                      placeholder="0"
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <p className="text-[11px] text-red-600 font-semibold mb-1">{t("adjustment.remove_stock")}</p>
                    <input
                      type="number" min="0" step="any"
                      value={removeQty}
                      onChange={(e) => { setRemoveQty(e.target.value); if (e.target.value) setAddQty(""); }}
                      placeholder="0"
                      className={inputCls}
                    />
                  </div>
                </div>
                {approvalInfo && qty !== 0 && (
                  <div className={`mt-1.5 px-2.5 py-1.5 rounded text-xs ${approvalInfo.cls}`}>
                    {qty > 0 ? "+" : ""}{qty} units · {approvalInfo.label}
                  </div>
                )}
              </div>
            )
          )}

          <Field label={t("audit.notes")} hint={`(${t("receive_panel.optional")})`}>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Supporting details…" rows={3} className={`${inputCls} resize-y`} />
          </Field>

          {error && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-3">{error}</div>}

          {/* Bug 7: manager override confirmation when projected balance goes negative */}
          {zeroWarn && (
            <div className="bg-amber-50 border border-amber-300 rounded p-3 mb-3">
              <p className="text-sm font-bold text-amber-900 mb-1">{t("adjustment.zero_floor_warn")}</p>
              <p className="text-xs text-amber-700 mb-3">This action will be audit-logged.</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => setZeroWarn(false)} className="px-3 py-1.5 bg-white border border-amber-300 rounded text-xs font-semibold cursor-pointer">
                  {t("common.cancel")}
                </button>
                <button type="button" onClick={() => void doSubmit(true)} className="px-3 py-1.5 bg-amber-700 text-white rounded text-xs font-bold cursor-pointer">
                  {t("adjustment.zero_floor_proceed")}
                </button>
              </div>
            </div>
          )}
        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => setOpen(false)} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          <button
            type="button"
            onClick={() => void doSubmit()}
            disabled={loading || zeroWarn}
            className={`flex-[2] py-2.5 bg-cyan-600 text-white font-bold text-sm rounded border-0 ${(loading || zeroWarn) ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}
          >
            {loading ? t("common.loading") : t("adjustment.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
