"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { enqueueOfflineTransaction } from "@/store/offlineQueue";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { getSession } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import type { DemoProduct } from "@/lib/demo-data";

interface Props { products: DemoProduct[]; orgSlug: string; }

const REASONS = [
  { value: "SALE",         label: "issue.reasons.SALE"         },
  { value: "INTERNAL_USE", label: "issue.reasons.INTERNAL_USE" },
  { value: "DAMAGE",       label: "issue.reasons.DAMAGE"       },
  { value: "EXPIRY",       label: "issue.reasons.EXPIRY"       },
  { value: "SAMPLE",       label: "issue.reasons.SAMPLE"       },
  { value: "OTHER",        label: "issue.reasons.OTHER"        },
];

const DESTINATION_META: Record<string, { label: string; placeholder: string; required: boolean }> = {
  SALE:         { label: "Issued To (Customer / Recipient)", placeholder: "e.g. Addis Supermarket, Order #1042", required: true  },
  INTERNAL_USE: { label: "Issued To (Department / Team)",   placeholder: "e.g. Quality Control, Head Office",   required: true  },
  SAMPLE:       { label: "Issued To (Recipient)",           placeholder: "e.g. Distributor name, event name",   required: true  },
  DAMAGE:       { label: "Destination / Disposal Note",     placeholder: "e.g. Disposed on-site",               required: false },
  EXPIRY:       { label: "Destination / Disposal Note",     placeholder: "e.g. Disposed on-site, Incinerated",  required: false },
  OTHER:        { label: "Issued To / Destination",         placeholder: "Recipient or destination",             required: false },
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

const inputCls  = "w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white";
const selectCls = `${inputCls} cursor-pointer`;

export function IssueStockPanel({ products, orgSlug }: Props) {
  const { isOnline } = useOfflineSync();
  const qc = useQueryClient();
  const { getAvailable } = useInventoryStore();
  const logAudit = useAuditStore((s) => s.log);

  const user          = getSession();
  const warehouseId   = user?.warehouseId   ?? "";
  const warehouseName = user?.warehouseName ?? warehouseId;

  const [open, setOpen]             = useState(false);
  const [productId, setProductId]   = useState("");
  const [quantity, setQuantity]     = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [issuedTo, setIssuedTo]     = useState("");
  const [notes, setNotes]           = useState("");
  const [error, setError]           = useState("");
  const [success, setSuccess]       = useState("");
  const [loading, setLoading]       = useState(false);

  const destMeta = reasonCode ? DESTINATION_META[reasonCode] : null;

  function reset() { setProductId(""); setQuantity(""); setReasonCode(""); setIssuedTo(""); setNotes(""); setError(""); setSuccess(""); }

  const selectedProduct = products.find((p) => p.id === productId);
  const availableStock  = selectedProduct && warehouseId
    ? getAvailable(selectedProduct.id, warehouseId, selectedProduct.stock[warehouseId] ?? 0)
    : null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError("");
    if (!productId)   { setError(t("receive_panel.error_product"));   return; }
    if (!warehouseId) { setError(t("receive_panel.error_warehouse")); return; }
    if (!reasonCode)  { setError(t("issue.error_reason")); return; }
    if (destMeta?.required && !issuedTo.trim()) { setError(`"${destMeta.label}" is required.`); return; }
    const qty = parseFloat(quantity);
    if (!qty || qty <= 0) { setError(t("receive_panel.error_qty")); return; }
    if (availableStock !== null && qty > availableStock) { setError(`${t("issue.insufficient")} ${availableStock.toLocaleString()}`); return; }
    const key = `issue:${productId}:${warehouseId}:${Date.now()}:${nanoid(8)}`;
    const payload = { product_id: productId, warehouse_id: warehouseId, quantity: qty.toFixed(4), reason_code: reasonCode, issued_to: issuedTo.trim() || undefined, notes, idempotency_key: key };
    setLoading(true);
    try {
      if (!isOnline) {
        await enqueueOfflineTransaction({ idempotencyKey: key, action: "inventory:issue", payload });
        setSuccess(t("inventory.receive.queue_offline"));
      } else {
        await api.post("/api/v1/inventory/issues/", payload);
        if (user) logAudit({ tenantSlug: orgSlug, userEmail: user.email, userName: user.name, role: user.role, action: "inventory:issue", category: "INVENTORY", resourceRef: selectedProduct?.sku ?? productId, resourceType: "InventoryTransaction", productName: selectedProduct?.name, quantityStr: `-${qty.toLocaleString()} ${selectedProduct?.unit ?? "units"}`, fromWarehouse: warehouseName, toWarehouse: issuedTo.trim() || undefined, notes: `[${reasonCode}]` });
        setSuccess(t("issue.success"));
        void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
        void qc.invalidateQueries({ queryKey: ["inventory-stock", orgSlug] });
      }
      reset(); setTimeout(() => { setSuccess(""); setOpen(false); }, 2500);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")); }
    finally { setLoading(false); }
  };

  return (
    <>
      <button onClick={() => { reset(); setOpen(true); }} className="px-4 py-2 bg-violet-600 text-white font-bold text-sm rounded border-0 cursor-pointer">
        {t("issue.title")}
      </button>

      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 bg-black/35 z-[100] backdrop-blur-sm" />}

      <div className={`fixed top-0 right-0 w-[420px] h-screen bg-white z-[110] shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="px-6 py-5 bg-violet-600 flex items-center justify-between">
          <div>
            <p className="font-bold text-base text-white m-0">{t("issue.title")}</p>
            <p className="text-xs text-violet-200 mt-0.5">{t("issue.subtitle")}</p>
          </div>
          <button onClick={() => setOpen(false)} className="bg-white/15 border-0 cursor-pointer text-white text-lg w-8 h-8 rounded flex items-center justify-center">✕</button>
        </div>

        <form onSubmit={onSubmit} className="flex-1 overflow-y-auto p-6">
          <Field label={t("table.product")}>
            <select value={productId} onChange={(e) => setProductId(e.target.value)} className={selectCls} required>
              <option value="">— {t("receive_panel.select_product")} —</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>)}
            </select>
          </Field>

          <Field label={t("inventory.transfer.from_warehouse")}>
            <div className={`${inputCls} bg-gray-50 text-gray-700 select-none`}>
              {warehouseName || "—"}
            </div>
          </Field>

          {availableStock !== null && (
            <div className="bg-violet-50 border border-violet-200 rounded-md px-3 py-2 mb-3 text-xs text-violet-800">
              {t("inventory.available")}: <strong>{availableStock.toLocaleString()}</strong> {t("lots.units")}
            </div>
          )}

          <Field label={t("issue.qty_to_issue")}>
            <input type="number" min="0.0001" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="e.g. 100" className={inputCls} required />
          </Field>

          <Field label={t("issue.reason")}>
            <select value={reasonCode} onChange={(e) => { setReasonCode(e.target.value); setIssuedTo(""); }} className={selectCls} required>
              <option value="">— {t("receive_panel.select_type")} —</option>
              {REASONS.map((r) => <option key={r.value} value={r.value}>{t(r.label)}</option>)}
            </select>
          </Field>

          {destMeta && (
            <Field label={destMeta.label} hint={destMeta.required ? undefined : `(${t("receive_panel.optional")})`}>
              <input type="text" value={issuedTo} onChange={(e) => setIssuedTo(e.target.value)} placeholder={destMeta.placeholder} className={inputCls} required={destMeta.required} />
            </Field>
          )}

          <Field label={t("audit.notes")} hint={`(${t("receive_panel.optional")})`}>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Customer name, order reference, notes…" rows={3} className={`${inputCls} resize-y`} />
          </Field>

          {error   && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-3">{error}</div>}
          {success && <div className="bg-violet-50 border border-violet-200 rounded p-3 text-sm text-violet-700 mb-3">✓ {success}</div>}
        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => setOpen(false)} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={loading} className={`flex-[2] py-2.5 bg-violet-600 text-white font-bold text-sm rounded border-0 ${loading ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}>
            {loading ? t("common.loading") : t("issue.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
