"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { useInventoryStore } from "@/lib/inventory-state";
import { getSession } from "@/lib/demo-auth";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { t } from "@/lib/i18n";
import { notify } from "@/lib/notify";
import { PanelError } from "@/components/ui/PanelError";
import { lotErrorMessage } from "@/lib/lotErrors";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";
import { LotFields } from "@/components/features/inventory/LotFields";

interface Props { products: DemoProduct[]; warehouses: DemoWarehouse[]; orgSlug: string; }

type FormState = { warehouseId: string; productId: string; quantity: string; lotNumber: string; autoLot: boolean; expiryDate: string; notes: string; referenceDocument: string; };

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
const lockedCls = `${inputCls} bg-gray-100 text-gray-500 cursor-not-allowed`;

export function OpeningBalancePanel({ products, warehouses, orgSlug }: Props) {
  const qc        = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const user       = getSession();
  const lockedWarehouseId = user?.warehouseId ?? "";

  const [open, setOpen]       = useState(false);
  const [form, setForm]       = useState<FormState>({ warehouseId: lockedWarehouseId, productId: "", quantity: "", lotNumber: "", autoLot: false, expiryDate: "", notes: "", referenceDocument: "" });
  const [error, setError]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const writeGuard = useWriteGuard();
  const gp = guardProps(writeGuard);

  const availableWarehouses = warehouses;
  const selectedProduct    = products.find((p) => p.id === form.productId);
  const requiresBatch      = selectedProduct?.batchTracking === true;
  const expiryRequired     = requiresBatch && selectedProduct?.expiryTracking === true;

  function clearForm() { setForm({ warehouseId: lockedWarehouseId, productId: "", quantity: "", lotNumber: "", autoLot: false, expiryDate: "", notes: "", referenceDocument: "" }); setError(""); }
  function reset() { clearForm(); }
  function set(key: "warehouseId" | "productId" | "quantity" | "lotNumber" | "expiryDate" | "notes" | "referenceDocument", val: string) { setForm((f) => ({ ...f, [key]: val })); setError(""); }
  function setAutoLot(val: boolean) { setForm((f) => ({ ...f, autoLot: val, lotNumber: val ? "" : f.lotNumber })); setError(""); }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (gp.disabled || submitting) return;
    if (!user)             { setError(t("opening_balance.error_session"));   return; }
    if (!form.warehouseId) { setError(t("receive_panel.error_warehouse")); return; }
    if (!form.productId)   { setError(t("receive_panel.error_product"));   return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0)  { setError(t("receive_panel.error_qty")); return; }
    if (requiresBatch) {
      if (!form.autoLot && !form.lotNumber) { setError(t("errors.LOT_NUMBER_REQUIRED")); return; }
      if (expiryRequired && !form.expiryDate) { setError(t("errors.EXPIRY_REQUIRED")); return; }
    }
    const product   = products.find((p) => p.id === form.productId);
    const idempotencyKey = `ob:${form.productId}:${form.warehouseId}:${Date.now()}:${nanoid(8)}`;
    const payload = {
      product_id:       form.productId,
      warehouse_id:     form.warehouseId,
      quantity:         qty,
      idempotency_key:  idempotencyKey,
      source:           "OPENING_BALANCE",
      ...(requiresBatch
        ? { auto_lot: form.autoLot, lot_number: form.autoLot ? undefined : form.lotNumber, expiry_date: form.expiryDate || undefined }
        : {}),
    };
    setSubmitting(true);
    try {
      const resp = await api.post<{ lot_number?: string | null }>("/api/v1/inventory/receive/", payload);
      addReceive(form.productId, form.warehouseId, qty);
      void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
      void qc.invalidateQueries({ queryKey: ["receipts", orgSlug] });
      clearForm(); setOpen(false);
      const what = `${product?.name ?? ""} (${product?.sku ?? ""}) +${qty.toLocaleString()} ${product?.unit ?? ""}`.trim();
      notify({
        kind: "success",
        message: resp.lot_number
          ? `${t("inventory.receive.success_lot").replace("{lot}", resp.lot_number)} ${what}`
          : `${t("opening_balance.success")} ${what}`,
      });
    } catch (err: unknown) {
      setError(lotErrorMessage(err) ?? (err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")));
    }
    finally { setSubmitting(false); }
  };

  if (!user) return null;

  return (
    <>
      <button onClick={() => { reset(); setOpen(true); }} {...gp} className="px-4 py-2 bg-blue-800 text-white font-bold text-sm rounded border-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
        + {t("opening_balance.title")}
      </button>

      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 bg-black/35 z-[100] backdrop-blur-sm" />}

      <div className={`fixed top-0 right-0 w-[440px] h-screen bg-white z-[110] shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="px-6 py-5 bg-blue-800 flex items-start justify-between">
          <div>
            <p className="font-bold text-base text-white m-0">{t("opening_balance.title")}</p>
            <p className="text-xs text-blue-200 mt-0.5">{t("opening_balance.subtitle")}</p>
            <p className="text-[10px] text-blue-300 mt-1 font-mono tracking-wide">
              {t("status.DRAFT")} → {t("status.PENDING_APPROVAL")} → {t("status.POSTED")}
            </p>
          </div>
          <button onClick={() => setOpen(false)} className="bg-white/10 border-0 cursor-pointer text-white text-lg w-8 h-8 rounded flex items-center justify-center shrink-0">✕</button>
        </div>

        <form onSubmit={onSubmit} className="flex-1 overflow-y-auto p-6">
          <PanelError message={error} />
          {gp.disabled && gp.title && (
            <div role="alert" className="bg-amber-50 border border-amber-200 rounded px-3.5 py-2.5 text-sm text-amber-800 mb-4">
              {gp.title}
            </div>
          )}
          <div className="bg-blue-50 border border-blue-200 rounded-md px-3 py-2.5 text-xs text-blue-800 mb-5 leading-relaxed">
            <strong>{t("opening_balance.title")}:</strong> {t("opening_balance.info")}
          </div>

          <Field label={t("inventory.warehouse")}>
            {lockedWarehouseId ? (
              <input type="text" value={warehouses.find((w) => w.id.toLowerCase() === lockedWarehouseId.toLowerCase())?.name ?? lockedWarehouseId} readOnly className={lockedCls} />
            ) : (
              <select value={form.warehouseId} onChange={(e) => set("warehouseId", e.target.value)} className={selectCls} required>
                <option value="">— {t("receive_panel.select_warehouse")} —</option>
                {availableWarehouses.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}{w.type === "MWH" ? " (Main)" : w.type === "RWH" ? " (Regional)" : ""}{w.location ? ` · ${w.location}` : ""}</option>
                ))}
              </select>
            )}
          </Field>

          <Field label={t("table.product")}>
            <select
              value={form.productId}
              onChange={(e) => setForm((f) => ({ ...f, productId: e.target.value, lotNumber: "", autoLot: false, expiryDate: "" }))}
              className={selectCls} required>
              <option value="">— {t("receive_panel.select_product")} —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}{p.batchTracking ? " [BATCH]" : ""}</option>)}
            </select>
          </Field>

          <Field label={t("opening_balance.opening_qty")}>
            <input type="number" min="1" step="any" value={form.quantity} onChange={(e) => set("quantity", e.target.value)} placeholder="e.g. 1000" className={inputCls} required />
          </Field>

          {requiresBatch && (
            <>
              <div className="bg-violet-50 border border-violet-200 rounded px-3 py-2 text-[11px] text-violet-800 font-semibold mb-3.5">
                {t("opening_balance.batch_required")}
              </div>
              <LotFields
                lotNumber={form.lotNumber}
                expiryDate={form.expiryDate}
                autoLot={form.autoLot}
                expiryRequired={!!expiryRequired}
                onLotNumberChange={(v) => set("lotNumber", v)}
                onExpiryDateChange={(v) => set("expiryDate", v)}
                onAutoLotChange={setAutoLot}
              />
            </>
          )}

          <Field label={t("audit.notes")} hint={`(${t("receive_panel.optional")})`}>
            <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder={t("opening_balance.notes_placeholder")} rows={2} className={`${inputCls} resize-y`} />
          </Field>
          <Field label={t("opening_balance.ref_doc")} hint={`(${t("receive_panel.optional")})`}>
            {/* i18n-ignore: example reference-document code */}
            <input type="text" value={form.referenceDocument} onChange={(e) => set("referenceDocument", e.target.value)} placeholder="e.g. PHYS-COUNT-2026-001" className={inputCls} />
          </Field>

        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => { reset(); setOpen(false); }} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={submitting || gp.disabled} title={gp.title} className={`flex-[2] py-2.5 bg-blue-800 text-white font-bold text-sm rounded border-0 ${submitting || gp.disabled ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}>
            {submitting ? t("common.saving") : t("opening_balance.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
