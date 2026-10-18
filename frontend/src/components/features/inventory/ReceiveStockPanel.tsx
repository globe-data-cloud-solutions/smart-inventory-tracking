"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { enqueueOfflineTransaction } from "@/store/offlineQueue";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useScanner } from "@/hooks/useScanner";
import { getSession } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { notify } from "@/lib/notify";
import { PanelError } from "@/components/ui/PanelError";
import { lotErrorMessage } from "@/lib/lotErrors";
import { useWarehouses } from "@/hooks/useWarehouses";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import type { DemoProduct } from "@/lib/demo-data";
import { buildOverrideTooltip } from "@/components/features/inventory/ProductLabel";
import { LotFields } from "@/components/features/inventory/LotFields";

interface Props { products: DemoProduct[]; orgSlug: string; }

const REFERENCE_TYPES = [
  { value: "PURCHASE_ORDER", label: "transfer.reference.PURCHASE_ORDER" },
  { value: "PRODUCTION",     label: "transfer.reference.PRODUCTION"     },
  { value: "RETURN",         label: "transfer.reference.RETURN"         },
  { value: "DONATION",       label: "transfer.reference.DONATION"       },
  { value: "MANUAL",         label: "transfer.reference.MANUAL"         },
];

type FormState = {
  productId: string; referenceType: string;
  quantity: string; lotNumber: string; expiryDate: string; autoLot: boolean;
};

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

const inputCls = "w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white";
const selectCls = `${inputCls} cursor-pointer`;

export function ReceiveStockPanel({ products, orgSlug }: Props) {
  const { isOnline } = useOfflineSync();
  const qc       = useQueryClient();

  const user        = getSession();
  const warehouseId = user?.warehouseId ?? "";
  const { warehouses } = useWarehouses();
  const warehouseName =
    warehouses.find((w) => w.id.toLowerCase() === warehouseId.toLowerCase())?.name
    ?? user?.warehouseName
    ?? warehouseId;

  const [open, setOpen]               = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scanHint, setScanHint]       = useState("");
  const [form, setForm] = useState<FormState>({ productId: "", referenceType: "", quantity: "", lotNumber: "", expiryDate: "", autoLot: false });
  const [error, setError]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const writeGuard = useWriteGuard();
  const gp = guardProps(writeGuard);

  const onScan = useCallback((code: string) => {
    const found = products.find((p) => p.sku === code || p.sku.toLowerCase() === code.toLowerCase());
    if (found) { setForm((f) => ({ ...f, productId: found.id })); setScanHint(`✓ ${found.name}`); setScannerOpen(false); }
    else { setScanHint(`No product: ${code}`); }
  }, [products]);

  const { videoRef, isActive: scanActive, error: scanError, start: startScan, stop: stopScan } = useScanner(onScan);

  function clearForm() { setForm({ productId: "", referenceType: "", quantity: "", lotNumber: "", expiryDate: "", autoLot: false }); setError(""); setScanHint(""); setScannerOpen(false); stopScan(); }
  function reset() { clearForm(); }
  function set(key: "productId" | "referenceType" | "quantity" | "lotNumber" | "expiryDate", val: string) { setForm((f) => ({ ...f, [key]: val })); setError(""); }
  function setAutoLot(val: boolean) { setForm((f) => ({ ...f, autoLot: val, lotNumber: val ? "" : f.lotNumber })); setError(""); }
  function toggleScanner() { if (scannerOpen) { stopScan(); setScannerOpen(false); } else { setScannerOpen(true); void startScan(); } }

  const selectedProduct = products.find((p) => p.id === form.productId);
  const isBatchProduct  = selectedProduct?.batchTracking === true;
  const expiryRequired  = isBatchProduct && selectedProduct?.expiryTracking === true;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (gp.disabled || submitting) return; // defense in depth — form's native Enter-to-submit bypasses the button's disabled attr
    if (!form.productId)     { setError(t("receive_panel.error_product"));   return; }
    if (!warehouseId)        { setError(t("receive_panel.error_warehouse")); return; }
    if (!form.referenceType) { setError(t("receive_panel.error_ref_type")); return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0) { setError(t("receive_panel.error_qty")); return; }
    if (isBatchProduct) {
      if (form.autoLot && !isOnline) { setError(t("receive_panel.auto_lot_offline_blocked")); return; }
      if (!form.autoLot && !form.lotNumber) { setError(t("errors.LOT_NUMBER_REQUIRED")); return; }
      if (expiryRequired && !form.expiryDate) { setError(t("errors.EXPIRY_REQUIRED")); return; }
    }
    const product = selectedProduct;
    const key = `receive:${form.productId}:${warehouseId}:${Date.now()}:${nanoid(8)}`;
    const payload = {
      product_id: form.productId, warehouse_id: warehouseId, reference_type: form.referenceType,
      quantity: qty.toFixed(4), idempotency_key: key,
      ...(isBatchProduct
        ? { auto_lot: form.autoLot, lot_number: form.autoLot ? undefined : form.lotNumber, expiry_date: form.expiryDate || undefined }
        : {}),
    };
    setSubmitting(true);
    try {
      if (!isOnline) {
        await enqueueOfflineTransaction({ idempotencyKey: key, action: "inventory:receive", payload });
        clearForm(); setOpen(false);
        notify({ kind: "success", message: `${t("inventory.receive.queue_offline")} — ${product?.name ?? ""} (${product?.sku ?? ""}) +${qty.toLocaleString()}` });
      } else {
        const resp = await api.post<{ lot_number?: string | null }>("/api/v1/inventory/receive/", payload);
        clearForm(); setOpen(false);
        const what = `${product?.name ?? ""} (${product?.sku ?? ""}) +${qty.toLocaleString()} ${product?.unit ?? ""}`.trim();
        notify({
          kind: "success",
          message: resp.lot_number
            ? `${t("inventory.receive.success_lot").replace("{lot}", resp.lot_number)} ${what}`
            : `${t("inventory.receive.success")} — ${what}`,
        });
        void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
        void qc.invalidateQueries({ queryKey: ["inventory-stock", orgSlug] });
      }
    } catch (err: unknown) {
      setError(lotErrorMessage(err) ?? (err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")));
    }
    finally { setSubmitting(false); }
  };

  return (
    <>
      <button onClick={() => { reset(); setOpen(true); }} {...gp} className="px-4 py-2 bg-eth-forest text-eth-gold font-bold text-sm rounded border-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
        + {t("inventory.receive.title")}
      </button>

      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 bg-black/35 z-[100] backdrop-blur-sm" />}

      <div className={`fixed top-0 right-0 w-[420px] h-screen bg-white z-[110] shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="px-6 py-5 bg-eth-forest flex items-center justify-between">
          <div>
            <p className="font-bold text-base text-white m-0">{t("inventory.receive.title")}</p>
            <p className="text-xs text-emerald-300 mt-0.5">{isOnline ? t("receive_panel.online_note") : t("receive_panel.offline_note")}</p>
          </div>
          <button onClick={() => setOpen(false)} className="bg-white/10 border-0 cursor-pointer text-white text-lg w-8 h-8 rounded flex items-center justify-center">✕</button>
        </div>

        <form onSubmit={onSubmit} className="flex-1 overflow-y-auto p-6">
          <PanelError message={error} />
          {gp.disabled && gp.title && (
            <div role="alert" className="bg-amber-50 border border-amber-200 rounded px-3.5 py-2.5 text-sm text-amber-800 mb-4">
              {gp.title}
            </div>
          )}
          <div className="mb-4">
            <button type="button" onClick={toggleScanner}
              className={`w-full py-2.5 rounded cursor-pointer border-2 border-dashed text-sm font-semibold flex items-center justify-center gap-2 ${scannerOpen ? "border-emerald-600 bg-green-50 text-emerald-600" : "border-gray-300 bg-gray-50 text-gray-500"}`}>
              <span>{scannerOpen ? "■" : "⬛"}</span>
              {scannerOpen ? t("scanner.stop") : t("scanner.start")}
            </button>
            {scannerOpen && (
              <div className="mt-2 rounded-md overflow-hidden bg-black relative">
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <video ref={videoRef} className="w-full h-[180px] object-cover block" playsInline muted />
                {!scanActive && <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white text-sm">{t("scanner.idle")}…</div>}
              </div>
            )}
            {scanError && <p className="text-xs text-red-600 mt-1">{scanError}</p>}
            {scanHint  && <p className={`text-xs mt-1 font-semibold ${scanHint.startsWith("✓") ? "text-emerald-600" : "text-red-600"}`}>{scanHint}</p>}
          </div>

          <Field label={t("table.product")}>
            <select
              value={form.productId}
              onChange={(e) => setForm((f) => ({ ...f, productId: e.target.value, lotNumber: "", expiryDate: "", autoLot: false }))}
              className={selectCls} required>
              <option value="">— {t("receive_panel.select_product")} —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.sku}{p.approval_overrides?.RECEIVE ? " 🔒" : ""}
                </option>
              ))}
            </select>
            {selectedProduct?.approval_overrides?.RECEIVE ? (
              <p className="text-xs text-amber-700 mt-1.5 flex items-start gap-1">
                <span>🔒</span><span>{buildOverrideTooltip(selectedProduct.approval_overrides.RECEIVE)}</span>
              </p>
            ) : null}
          </Field>
          <Field label={t("inventory.warehouse")}>
            <div className={`${inputCls} bg-gray-50 text-gray-700 select-none`}>
              {warehouseName || "—"}
            </div>
          </Field>
          <Field label={t("receive_panel.reference_type")}>
            <select value={form.referenceType} onChange={(e) => set("referenceType", e.target.value)} className={selectCls} required>
              <option value="">— {t("receive_panel.select_type")} —</option>
              {REFERENCE_TYPES.map((r) => <option key={r.value} value={r.value}>{t(r.label)}</option>)}
            </select>
          </Field>
          <Field label={t("inventory.receive.quantity")}>
            <input type="number" min="0.0001" step="any" value={form.quantity} onChange={(e) => set("quantity", e.target.value)} placeholder="e.g. 500" className={inputCls} required />
          </Field>
          {isBatchProduct && (
            <LotFields
              lotNumber={form.lotNumber}
              expiryDate={form.expiryDate}
              autoLot={form.autoLot}
              expiryRequired={!!expiryRequired}
              onLotNumberChange={(v) => set("lotNumber", v)}
              onExpiryDateChange={(v) => set("expiryDate", v)}
              onAutoLotChange={setAutoLot}
            />
          )}

        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => setOpen(false)} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={submitting || gp.disabled} title={gp.title}
            className={`flex-[2] py-2.5 font-bold text-sm rounded border-0 text-eth-gold ${submitting || gp.disabled ? "opacity-70 cursor-not-allowed" : "cursor-pointer"} ${isOnline ? "bg-eth-forest" : "bg-amber-800"}`}>
            {submitting ? t("common.saving") : isOnline ? t("inventory.receive.submit") : t("inventory.receive.queue_offline")}
          </button>
        </div>
      </div>
    </>
  );
}
