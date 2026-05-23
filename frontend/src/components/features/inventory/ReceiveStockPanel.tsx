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
import { t } from "@/lib/i18n";
import type { DemoProduct } from "@/lib/demo-data";

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
  quantity: string; lotNumber: string; expiryDate: string;
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
  const qc         = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const logAudit   = useAuditStore((s) => s.log);

  const user          = getSession();
  const warehouseId   = user?.warehouseId   ?? "";
  const warehouseName = user?.warehouseName ?? warehouseId;

  const [open, setOpen]               = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scanHint, setScanHint]       = useState("");
  const [form, setForm] = useState<FormState>({ productId: "", referenceType: "", quantity: "", lotNumber: "", expiryDate: "" });
  const [error, setError]     = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const onScan = useCallback((code: string) => {
    const found = products.find((p) => p.sku === code || p.sku.toLowerCase() === code.toLowerCase());
    if (found) { setForm((f) => ({ ...f, productId: found.id })); setScanHint(`✓ ${found.name}`); setScannerOpen(false); }
    else { setScanHint(`No product: ${code}`); }
  }, [products]);

  const { videoRef, isActive: scanActive, error: scanError, start: startScan, stop: stopScan } = useScanner(onScan);

  function reset() { setForm({ productId: "", referenceType: "", quantity: "", lotNumber: "", expiryDate: "" }); setError(""); setSuccess(""); setScanHint(""); setScannerOpen(false); stopScan(); }
  function set(key: keyof FormState, val: string) { setForm((f) => ({ ...f, [key]: val })); setError(""); }
  function toggleScanner() { if (scannerOpen) { stopScan(); setScannerOpen(false); } else { setScannerOpen(true); void startScan(); } }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (!form.productId)     { setError(t("receive_panel.error_product"));   return; }
    if (!warehouseId)        { setError(t("receive_panel.error_warehouse")); return; }
    if (!form.referenceType) { setError(t("receive_panel.error_ref_type")); return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0) { setError(t("receive_panel.error_qty")); return; }
    const product = products.find((p) => p.id === form.productId);
    const key = `receive:${form.productId}:${warehouseId}:${Date.now()}:${nanoid(8)}`;
    const payload = { product_id: form.productId, warehouse_id: warehouseId, reference_type: form.referenceType, quantity: qty.toFixed(4), lot_number: form.lotNumber || undefined, expiry_date: form.expiryDate || undefined, idempotency_key: key };
    setLoading(true);
    try {
      if (!isOnline) {
        await enqueueOfflineTransaction({ idempotencyKey: key, action: "inventory:receive", payload });
        setSuccess(t("inventory.receive.queue_offline"));
      } else {
        await api.post("/api/v1/inventory/receive", payload);
        addReceive(form.productId, warehouseId, qty);
        if (user) logAudit({ tenantSlug: orgSlug, userEmail: user.email, userName: user.name, role: user.role, action: "inventory:receive", category: "INVENTORY", resourceRef: product?.sku ?? form.productId, resourceType: "InventoryTransaction", productName: product?.name, quantityStr: `+${qty.toLocaleString()} ${product?.unit ?? "units"}`, toWarehouse: warehouseName, notes: t(`transfer.reference.${form.referenceType}`) });
        setSuccess(t("inventory.receive.success"));
        void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
        void qc.invalidateQueries({ queryKey: ["receipts", orgSlug] });
      }
      reset(); setTimeout(() => { setSuccess(""); setOpen(false); }, 2500);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")); }
    finally { setLoading(false); }
  };

  return (
    <>
      <button onClick={() => { reset(); setOpen(true); }} className="px-4 py-2 bg-eth-forest text-eth-gold font-bold text-sm rounded border-0 cursor-pointer">
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
            <select value={form.productId} onChange={(e) => set("productId", e.target.value)} className={selectCls} required>
              <option value="">— {t("receive_panel.select_product")} —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
            </select>
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
          <Field label={t("inventory.receive.lot_number")} hint={`(${t("receive_panel.optional")})`}>
            <input type="text" value={form.lotNumber} onChange={(e) => set("lotNumber", e.target.value)} placeholder="e.g. LOT-2026-001" className={inputCls} />
          </Field>
          <Field label={t("inventory.receive.expiry_date")} hint={`(${t("receive_panel.optional")})`}>
            <input type="date" value={form.expiryDate} onChange={(e) => set("expiryDate", e.target.value)} className={inputCls} />
          </Field>

          {error   && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-3">{error}</div>}
          {success && <div className="bg-green-50 border border-emerald-200 rounded p-3 text-sm text-emerald-600 mb-3">✓ {success}</div>}
        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => setOpen(false)} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={loading}
            className={`flex-[2] py-2.5 font-bold text-sm rounded border-0 text-eth-gold ${loading ? "opacity-70 cursor-not-allowed" : "cursor-pointer"} ${isOnline ? "bg-eth-forest" : "bg-amber-800"}`}>
            {loading ? t("common.loading") : isOnline ? t("inventory.receive.submit") : t("inventory.receive.queue_offline")}
          </button>
        </div>
      </div>
    </>
  );
}
