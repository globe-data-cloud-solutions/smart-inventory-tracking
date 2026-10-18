"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { notify } from "@/lib/notify";
import { PanelError } from "@/components/ui/PanelError";
import { isQuantityDeltaError, lotErrorMessage } from "@/lib/lotErrors";
import { getSession } from "@/lib/demo-auth";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { useInventoryStore } from "@/lib/inventory-state";
import { buildOverrideTooltip } from "@/components/features/inventory/ProductLabel";
import { LotFields } from "@/components/features/inventory/LotFields";
import { formatQty } from "@/lib/utils";
import { formatExpiry } from "@/components/features/transfers/TransferLotDetails";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";

interface Props { products: DemoProduct[]; warehouses: DemoWarehouse[]; orgSlug: string; }

const REASONS = [
  { value: "DAMAGE",            label: "adjustment.reasons.DAMAGE"            },
  { value: "EXPIRY",            label: "adjustment.reasons.EXPIRY"            },
  { value: "THEFT",             label: "adjustment.reasons.THEFT"             },
  { value: "COUNT_DISCREPANCY", label: "adjustment.reasons.COUNT_DISCREPANCY" },
  { value: "RETURN",            label: "adjustment.reasons.RETURN"            },
  { value: "PRODUCTION_USE",    label: "adjustment.reasons.PRODUCTION_USE"    },
  { value: "SAMPLE",            label: "adjustment.reasons.SAMPLE"            },
  { value: "OTHER",             label: "adjustment.reasons.OTHER"             },
];

// These reasons always deduct stock — user enters magnitude, system negates.
// Drives this panel's quantity-field layout only (unchanged — kept as today).
// The backend's own effective-sign rule is _FORCE_NEGATIVE_REASONS in
// inventory_service.py (DAMAGE, EXPIRY, SUPPLIER_RETURN); batch-product lot
// selection below mirrors that via `qty`'s sign — see isLotNegative/isLotPositive.
const FORCE_NEGATIVE = new Set(["DAMAGE", "EXPIRY", "THEFT"]);

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

interface AdjResult { adjustment_id: string; status: string; quantity_delta: string }

// GET /api/v1/inventory/lots — the fields this panel's lot pickers read.
interface AdjLotApi {
  lot_id: string;
  lot_number: string;
  quantity: string;
  expiry_date: string | null;
  status: string; // ACTIVE | DEPLETED | EXPIRED
}

export function NewAdjustmentPanel({ products, warehouses, orgSlug }: Props) {
  const qc      = useQueryClient();
  const session = getSession();
  const guard   = useWriteGuard();
  const gp      = guardProps(guard);
  // Auto-assign warehouse from JWT for any role that has a specific facility
  // assignment (WM, RM, LM). Only NM/TA who have no warehouseId in their JWT
  // see the dropdown so they can choose which facility to adjust.
  const hasAssignedWarehouse = !!session?.warehouseId;

  type AdjRule = {
    role_code: string; level_number: number; threshold_type: string;
    qty_limit: string | null; value_limit: string | null;
    approver_role_code: string | null; is_active: boolean;
  };
  const tenantId = session?.tenantId;
  const { data: adjRules = [] } = useQuery<AdjRule[]>({
    queryKey: ["adj-approval-rules", tenantId],
    queryFn:  () => api.get<AdjRule[]>(`/api/v1/tenants/${tenantId}/adjustment-approval-rules`),
    enabled:  IS_GATEWAY_MODE && !!tenantId,
    staleTime: 60_000,
  });

  const approvalHint = useMemo(() => {
    // Match a rule for the current user's role + level
    const userRole  = session?.role ?? "";
    const userLevel = (session as { level_number?: number } | null)?.level_number ?? null;
    const activeRules = adjRules.filter(
      (r) => r.is_active && r.role_code === userRole &&
             (userLevel === null || r.level_number === userLevel)
    );
    return (qty: number): { role: string; label: string; cls: string } | null => {
      if (qty === 0) return null;
      const abs = Math.abs(qty);
      if (activeRules.length === 0) return null;
      const match = activeRules.find((r) => {
        const limit = r.qty_limit ? parseFloat(r.qty_limit) : null;
        return r.threshold_type === "QUANTITY" && (limit === null || abs <= limit);
      });
      if (!match) {
        return { role: "TA", label: t("adjustment.pending_ta"), cls: "bg-red-50 text-red-700" };
      }
      if (match.approver_role_code === null) {
        return { role: "NONE", label: t("adjustment.auto_applied"), cls: "bg-green-50 text-emerald-700" };
      }
      const cls = match.approver_role_code === "TA" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800";
      const label = match.approver_role_code === "TA" ? t("adjustment.pending_ta") : t("adjustment.pending_rm");
      return { role: match.approver_role_code, label, cls };
    };
  }, [adjRules, session?.role]);

  const [open, setOpen]               = useState(false);
  const [productId, setProductId]     = useState("");
  const [warehouseId, setWarehouseId] = useState(""); // non-WM only
  const [addQty, setAddQty]           = useState("");
  const [removeQty, setRemoveQty]     = useState("");
  const [reason, setReason]           = useState("");
  const [notes, setNotes]             = useState("");
  const [error, setError]             = useState("");
  const [submitting, setSubmitting]   = useState(false);
  const [zeroWarn, setZeroWarn]       = useState(false);

  // Batch-tracked lot choice (lot tracking on). Negative: one existing lot to
  // deduct from. Positive: either an existing lot (any warehouse) or a new one.
  const [lotId, setLotId]         = useState("");
  const [lotMode, setLotMode]     = useState<"existing" | "new">("existing");
  const [lotNumber, setLotNumber] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [autoLot, setAutoLot]     = useState(false);

  function clearLot() {
    setLotId(""); setLotMode("existing"); setLotNumber(""); setExpiryDate(""); setAutoLot(false);
  }

  const effectiveWarehouseId = hasAssignedWarehouse ? (session?.warehouseId ?? "") : warehouseId;
  const effectiveWarehouseName = hasAssignedWarehouse
    ? (warehouses.find((w) => w.id.toLowerCase() === effectiveWarehouseId.toLowerCase())?.name
        ?? session?.warehouseName ?? "")
    : warehouses.find((w) => w.id.toLowerCase() === warehouseId.toLowerCase())?.name ?? "";

  const forceNeg  = FORCE_NEGATIVE.has(reason);
  const addNum    = parseFloat(addQty)    || 0;
  const removeNum = parseFloat(removeQty) || 0;
  // Bug 4A: DAMAGE/EXPIRY → always negative. Bug 4B: other reasons → add minus remove.
  const qty       = forceNeg ? -Math.abs(addNum) : addNum - removeNum;

  const approvalInfo = qty !== 0 ? approvalHint(qty) : null;
  const selectedP    = products.find((p) => p.id === productId);
  const isBatchProduct = selectedP?.batchTracking === true;
  const newLotExpiryRequired = isBatchProduct && selectedP?.expiryTracking === true;

  // Lot selection branches on the sign of `qty` (computed above), which already
  // matches the backend's effective-sign rule in inventory_service.py
  // (_FORCE_NEGATIVE_REASONS: DAMAGE, EXPIRY, SUPPLIER_RETURN always negative;
  // every other reason follows the sign the user actually entered).
  // SUPPLIER_RETURN is a legacy backend-only value and never appears in REASONS.
  const isLotNegative = qty < 0;
  const isLotPositive = qty > 0;

  // GET /api/v1/inventory/lots?product_id&warehouse_id — non-depleted lots
  // (ACTIVE + EXPIRED) with stock at this warehouse, for the negative path.
  const { data: negativeLots = [] } = useQuery<AdjLotApi[]>({
    queryKey: ["adj-lots-negative", productId, effectiveWarehouseId],
    queryFn: () => api.get<AdjLotApi[]>(
      `/api/v1/inventory/lots?${new URLSearchParams({ product_id: productId, warehouse_id: effectiveWarehouseId }).toString()}`
    ),
    enabled: IS_GATEWAY_MODE && isBatchProduct && isLotNegative && !!productId && !!effectiveWarehouseId,
    staleTime: 0,
  });

  // GET /api/v1/inventory/lots?product_id&include_depleted=true — every lot of
  // this product (any warehouse), de-duplicated by lot_id, for the positive
  // "Existing lot" path.
  const { data: allProductLots = [] } = useQuery<AdjLotApi[]>({
    queryKey: ["adj-lots-existing", productId],
    queryFn: () => api.get<AdjLotApi[]>(
      `/api/v1/inventory/lots?${new URLSearchParams({ product_id: productId, include_depleted: "true" }).toString()}`
    ),
    enabled: IS_GATEWAY_MODE && isBatchProduct && isLotPositive && lotMode === "existing" && !!productId,
    staleTime: 0,
  });
  const existingLots = useMemo(() => {
    const map = new Map<string, AdjLotApi>();
    for (const l of allProductLots) if (!map.has(l.lot_id)) map.set(l.lot_id, l);
    return Array.from(map.values());
  }, [allProductLots]);

  const selectedNegativeLot = negativeLots.find((l) => l.lot_id === lotId);
  const lotQtyError = isLotNegative && selectedNegativeLot && Math.abs(qty) > parseFloat(selectedNegativeLot.quantity)
    ? t("adjustment.lot_error_exceeds").replace("{available}", formatQty(selectedNegativeLot.quantity))
    : "";

  // Switching sign (typing Add vs Remove) or reason clears an incompatible lot choice.
  const lotClearKey = `${reason}|${isLotNegative ? "neg" : isLotPositive ? "pos" : "zero"}`;
  const prevLotClearKey = useRef(lotClearKey);
  useEffect(() => {
    if (prevLotClearKey.current !== lotClearKey) {
      clearLot();
      prevLotClearKey.current = lotClearKey;
    }
  }, [lotClearKey]);

  function reset() {
    setProductId(""); setWarehouseId(""); setAddQty(""); setRemoveQty("");
    setReason(""); setNotes(""); setError(""); setZeroWarn(false); clearLot();
  }

  async function doSubmit(bypassZeroFloor = false) {
    if (submitting) return;
    setError("");
    const blockedReason = guard.reason();
    if (blockedReason) { setError(blockedReason); return; }

    if (!productId)            { setError(t("receive_panel.error_product"));   return; }
    if (!effectiveWarehouseId) { setError(t("receive_panel.error_warehouse")); return; }
    if (!reason)               { setError(t("issue.error_reason")); return; }
    if (forceNeg  && addNum === 0)                 { setError(t("adjustment.error_qty")); return; }
    if (!forceNeg && addNum === 0 && removeNum === 0) { setError(t("adjustment.error_qty")); return; }
    if (!forceNeg && addNum > 0 && removeNum > 0) {
      setError(t("adjustment.error_fill_either"));
      return;
    }

    if (isBatchProduct && qty !== 0) {
      if (isLotNegative) {
        if (!lotId) { setError(t("errors.LOT_REQUIRED")); return; }
        if (lotQtyError) { setError(lotQtyError); return; }
      } else if (isLotPositive) {
        if (lotMode === "existing") {
          if (!lotId) { setError(t("errors.LOT_REQUIRED")); return; }
        } else {
          if (!autoLot && !lotNumber.trim()) { setError(t("errors.LOT_NUMBER_REQUIRED")); return; }
          if (newLotExpiryRequired && !expiryDate) { setError(t("errors.EXPIRY_REQUIRED")); return; }
        }
      }
    }

    // Bug 7: zero-floor guard — block WM, confirm for managers
    if (!bypassZeroFloor) {
      const store     = useInventoryStore.getState();
      const baseStock = selectedP?.stock?.[effectiveWarehouseId] ?? 0;
      const projected = store.getOnHand(productId, effectiveWarehouseId, baseStock) + qty;
      if (projected < 0) {
        if (hasAssignedWarehouse) {
          setError(t("adjustment.zero_floor_wm"));
          return;
        }
        setZeroWarn(true);
        return;
      }
    }

    setZeroWarn(false);
    const key = `adjust:${productId}:${effectiveWarehouseId}:${Date.now()}:${nanoid(8)}`;
    setSubmitting(true);
    try {
      const adj = await api.post<AdjResult>("/api/v1/inventory/adjustments/", {
        product_id:     productId,
        product_name:   selectedP?.name,
        product_sku:    selectedP?.sku,
        warehouse_id:   effectiveWarehouseId,
        warehouse_name: effectiveWarehouseName,
        quantity_delta: qty,
        reason_code:    reason,
        notes,
        idempotency_key: key,
        ...(isBatchProduct && qty !== 0
          ? isLotNegative
            ? { lot_id: lotId }
            : lotMode === "existing"
              ? { lot_id: lotId }
              : { lot_number: autoLot ? undefined : lotNumber.trim(), expiry_date: expiryDate || undefined, auto_lot: autoLot }
          : {}),
      });

      // Bug 5: update Zustand inventory store when adjustment is auto-applied
      if (adj.status === "APPLIED") {
        const store = useInventoryStore.getState();
        if (qty > 0) store.addReceive(productId, effectiveWarehouseId, qty);
        else         store.addIssue(productId, effectiveWarehouseId, Math.abs(qty));
      }

      reset(); setOpen(false);
      notify({
        kind: "success",
        message: `${adj.status === "APPLIED" ? t("adjustment.success_applied") : t("adjustment.success_submitted")} — ${selectedP?.name ?? ""} (${selectedP?.sku ?? ""}) ${qty > 0 ? "+" : ""}${qty}`,
      });
      void qc.invalidateQueries({ queryKey: ["adjustments", orgSlug] });
    } catch (err: unknown) {
      setError(
        isQuantityDeltaError(err)
          ? t("adjustment.error_qty")
          : lotErrorMessage(err) ?? (err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")),
      );
    } finally {
      setSubmitting(false);
    }
  }

  const onFormSubmit = (e: React.FormEvent) => { e.preventDefault(); void doSubmit(); };

  return (
    <>
      <button
        onClick={() => { if (gp.disabled) return; reset(); setOpen(true); }}
        disabled={gp.disabled}
        title={gp.title}
        className={`px-4 py-2 font-bold text-sm rounded border-0 ${gp.disabled ? "bg-gray-200 text-gray-400 cursor-not-allowed" : "bg-cyan-600 text-white cursor-pointer"}`}
      >
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
          {gp.title && (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-4">
              {gp.title}
            </div>
          )}

          <PanelError message={error} />

          <Field label={t("table.product")}>
            <select value={productId} onChange={(e) => { setProductId(e.target.value); clearLot(); }} className={selectCls} required>
              <option value="">— {t("receive_panel.select_product")} —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.sku}{(p.approval_overrides && Object.keys(p.approval_overrides).length > 0) ? " 🔒" : ""}
                </option>
              ))}
            </select>
            {selectedP?.approval_overrides && Object.keys(selectedP.approval_overrides).length > 0 && (
              <p className="text-xs text-amber-700 mt-1.5 flex items-start gap-1">
                <span>🔒</span><span>
                  {selectedP.approval_overrides.ADJUSTMENT
                    ? buildOverrideTooltip(selectedP.approval_overrides.ADJUSTMENT)
                    : t("product.controlled_tooltip")}
                </span>
              </p>
            )}
          </Field>

          {/* Auto-assign from JWT for roles with a specific facility (WM/RM/LM).
              NM/TA have no warehouseId in JWT so they see a dropdown. */}
          <Field label={t("inventory.warehouse")}>
            {hasAssignedWarehouse ? (
              <div>
                <p className="text-[11px] text-gray-400 mb-0.5">{t("adjustment.warehouse_auto")}</p>
                <div className={`${inputCls} bg-gray-50 text-gray-600 cursor-not-allowed border-dashed`}>
                  {effectiveWarehouseName || "—"}
                </div>
              </div>
            ) : (
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} className={selectCls} required>
                <option value="">— {t("adjustment.warehouse_select")} —</option>
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

          {isBatchProduct && reason && qty !== 0 && (
            isLotNegative ? (
              <Field label={t("adjustment.lot_label")}>
                <select
                  data-testid="adj-lot-select"
                  value={lotId}
                  onChange={(e) => setLotId(e.target.value)}
                  className={selectCls}
                  required
                >
                  <option value="">— {t("adjustment.lot_select_placeholder")} —</option>
                  {negativeLots.map((l) => (
                    <option key={l.lot_id} value={l.lot_id}>
                      {l.lot_number}
                      {l.expiry_date ? ` · ${formatExpiry(l.expiry_date)}` : ""}
                      {` · ${formatQty(l.quantity)} ${t("lots.units")}`}
                      {l.status === "EXPIRED" ? ` · ${t("lots.expired")}` : ""}
                    </option>
                  ))}
                </select>
                {lotQtyError && (
                  <p data-testid="adj-lot-error" className="text-xs text-red-600 mt-1">{lotQtyError}</p>
                )}
              </Field>
            ) : (
              <Field label={t("adjustment.lot_label")}>
                <div className="flex gap-2 mb-2">
                  <button
                    type="button"
                    data-testid="adj-lot-mode-existing"
                    onClick={() => setLotMode("existing")}
                    className={`flex-1 py-1.5 rounded text-xs font-bold border cursor-pointer ${lotMode === "existing" ? "bg-cyan-600 text-white border-cyan-600" : "bg-white text-gray-700 border-gray-300"}`}
                  >
                    {t("adjustment.lot_mode_existing")}
                  </button>
                  <button
                    type="button"
                    data-testid="adj-lot-mode-new"
                    onClick={() => setLotMode("new")}
                    className={`flex-1 py-1.5 rounded text-xs font-bold border cursor-pointer ${lotMode === "new" ? "bg-cyan-600 text-white border-cyan-600" : "bg-white text-gray-700 border-gray-300"}`}
                  >
                    {t("adjustment.lot_mode_new")}
                  </button>
                </div>
                {lotMode === "existing" ? (
                  <select value={lotId} onChange={(e) => setLotId(e.target.value)} className={selectCls} required>
                    <option value="">— {t("adjustment.lot_existing_placeholder")} —</option>
                    {existingLots.map((l) => (
                      <option key={l.lot_id} value={l.lot_id}>
                        {l.lot_number}{l.expiry_date ? ` · ${formatExpiry(l.expiry_date)}` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <LotFields
                    lotNumber={lotNumber}
                    expiryDate={expiryDate}
                    autoLot={autoLot}
                    expiryRequired={newLotExpiryRequired}
                    onLotNumberChange={setLotNumber}
                    onExpiryDateChange={setExpiryDate}
                    onAutoLotChange={(v) => { setAutoLot(v); if (v) setLotNumber(""); }}
                  />
                )}
              </Field>
            )
          )}

          <Field label={t("audit.notes")} hint={`(${t("receive_panel.optional")})`}>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("adjustment.notes_placeholder")} rows={3} className={`${inputCls} resize-y`} />
          </Field>

          {/* Bug 7: manager override confirmation when projected balance goes negative */}
          {zeroWarn && (
            <div className="bg-amber-50 border border-amber-300 rounded p-3 mb-3">
              <p className="text-sm font-bold text-amber-900 mb-1">{t("adjustment.zero_floor_warn")}</p>
              <p className="text-xs text-amber-700 mb-3">{t("adjustment.zero_floor_audit_notice")}</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => setZeroWarn(false)} className="px-3 py-1.5 bg-white border border-amber-300 rounded text-xs font-semibold cursor-pointer">
                  {t("common.cancel")}
                </button>
                <button type="button" disabled={gp.disabled} title={gp.title} onClick={() => void doSubmit(true)} className={`px-3 py-1.5 text-white rounded text-xs font-bold ${gp.disabled ? "bg-gray-300 cursor-not-allowed" : "bg-amber-700 cursor-pointer"}`}>
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
            disabled={submitting || zeroWarn || gp.disabled}
            title={gp.title}
            className={`flex-[2] py-2.5 bg-cyan-600 text-white font-bold text-sm rounded border-0 ${(submitting || zeroWarn || gp.disabled) ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}
          >
            {submitting ? t("common.saving") : t("adjustment.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
