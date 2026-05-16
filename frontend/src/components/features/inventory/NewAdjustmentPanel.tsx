"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
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

const THRESHOLDS = { low: 100, medium: 500 };

function getApprovalInfo(qty: number): { role: string; label: string; cls: string } {
  const abs = Math.abs(qty);
  if (abs < THRESHOLDS.low)    return { role: "NONE", label: t("adjustment.auto_applied"),  cls: "bg-green-50 text-emerald-700" };
  if (abs < THRESHOLDS.medium) return { role: "RM",   label: t("adjustment.pending_rm"),    cls: "bg-amber-50 text-amber-800" };
  return                              { role: "NM",   label: t("adjustment.pending_nm"),    cls: "bg-red-50 text-red-700" };
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
  const qc = useQueryClient();
  const [open, setOpen]               = useState(false);
  const [productId, setProductId]     = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity]       = useState("");
  const [reason, setReason]           = useState("");
  const [notes, setNotes]             = useState("");
  const [error, setError]             = useState("");
  const [result, setResult]           = useState<AdjResult | null>(null);
  const [loading, setLoading]         = useState(false);

  function reset() { setProductId(""); setWarehouseId(""); setQuantity(""); setReason(""); setNotes(""); setError(""); setResult(null); }

  const qty          = parseFloat(quantity) || 0;
  const approvalInfo = qty !== 0 ? getApprovalInfo(qty) : null;
  const selectedP    = products.find((p) => p.id === productId);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (!productId)   { setError(t("receive_panel.error_product"));   return; }
    if (!warehouseId) { setError(t("receive_panel.error_warehouse")); return; }
    if (!reason)      { setError(t("issue.error_reason")); return; }
    if (qty === 0)    { setError(t("adjustment.error_qty")); return; }
    const key = `adjust:${productId}:${warehouseId}:${Date.now()}:${nanoid(8)}`;
    setLoading(true);
    try {
      const adj = await api.post<AdjResult>("/api/v1/inventory/adjust", { product_id: productId, product_name: selectedP?.name, product_sku: selectedP?.sku, warehouse_id: warehouseId, warehouse_name: warehouses.find((w) => w.id === warehouseId)?.name, quantity: qty, reason_code: reason, notes, idempotency_key: key });
      setResult(adj);
      void qc.invalidateQueries({ queryKey: ["adjustments", orgSlug] });
    } catch (err: unknown) { setError(err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")); }
    finally { setLoading(false); }
  };

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

        {result ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
            <div className={`w-16 h-16 rounded-full flex items-center justify-center text-3xl mb-5 ${result.status === "APPLIED" ? "bg-green-100" : "bg-amber-100"}`}>
              {result.status === "APPLIED" ? "✓" : "⏳"}
            </div>
            <p className="font-extrabold text-lg text-gray-900 mb-2">
              {result.status === "APPLIED" ? t("adjustment.success_applied") : t("adjustment.success_submitted")}
            </p>
            <p className="text-sm text-gray-500 mb-8">
              {result.status === "APPLIED" ? t("adjustment.auto_applied") : `${t("adjustment.pending_rm").split(" ").slice(0, 2).join(" ")} ${result.approval_required_role}.`}
            </p>
            <div className="flex gap-2.5">
              <button onClick={reset} className="px-5 py-2 bg-gray-100 border-0 rounded-md text-sm font-semibold cursor-pointer">{t("adjustment.new_btn")}</button>
              <button onClick={() => { reset(); setOpen(false); }} className="px-5 py-2 bg-cyan-600 text-white border-0 rounded-md text-sm font-bold cursor-pointer">{t("common.confirm")}</button>
            </div>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="flex-1 overflow-y-auto p-6">
            <Field label={t("table.product")}>
              <select value={productId} onChange={(e) => setProductId(e.target.value)} className={selectCls} required>
                <option value="">— {t("receive_panel.select_product")} —</option>
                {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
              </select>
            </Field>
            <Field label={t("inventory.warehouse")}>
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} className={selectCls} required>
                <option value="">— {t("receive_panel.select_warehouse")} —</option>
                {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
            <Field label={t("adjustment.quantity")} hint={t("adjustment.quantity_hint")}>
              <input type="number" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="e.g. -50 or +200" className={inputCls} />
              {approvalInfo && (
                <div className={`mt-1.5 px-2.5 py-1.5 rounded text-xs ${approvalInfo.cls}`}>{approvalInfo.label}</div>
              )}
            </Field>
            <Field label={t("adjustment.reason")}>
              <select value={reason} onChange={(e) => setReason(e.target.value)} className={selectCls} required>
                <option value="">— {t("receive_panel.select_type")} —</option>
                {REASONS.map((r) => <option key={r.value} value={r.value}>{t(r.label)}</option>)}
              </select>
            </Field>
            <Field label={t("audit.notes")} hint={`(${t("receive_panel.optional")})`}>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Supporting details…" rows={3} className={`${inputCls} resize-y`} />
            </Field>
            {error && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-3">{error}</div>}
          </form>
        )}

        {!result && (
          <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
            <button type="button" onClick={() => setOpen(false)} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
            <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={loading} className={`flex-[2] py-2.5 bg-cyan-600 text-white font-bold text-sm rounded border-0 ${loading ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}>
              {loading ? t("common.loading") : t("adjustment.submit")}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
