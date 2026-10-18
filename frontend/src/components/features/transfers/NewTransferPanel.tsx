"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { useInventoryStore, type TransferEntry } from "@/lib/inventory-state";
import { getSession } from "@/lib/demo-auth";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { t } from "@/lib/i18n";
import { notify } from "@/lib/notify";
import { PanelError } from "@/components/ui/PanelError";
import { formatQty } from "@/lib/utils";
import { buildOverrideTooltip } from "@/components/features/inventory/ProductLabel";
import { DispatchPreviewInfo, fetchDispatchPreview, type DispatchPreviewApi } from "@/components/features/transfers/DispatchPreview";
import type { DemoProduct, DemoWarehouse, ProductApprovalOverride } from "@/lib/demo-data";

function getAncestorScope(warehouseId: string, warehouses: DemoWarehouse[]): string[] {
  const ancestors: string[] = [];
  let cur = warehouses.find((w) => w.id === warehouseId);
  while (cur?.parentId) { ancestors.push(cur.parentId); cur = warehouses.find((w) => w.id === cur!.parentId); }
  return ancestors;
}

function getDescendantScope(warehouseId: string, warehouses: DemoWarehouse[]): string[] {
  const scope = new Set<string>([warehouseId]);
  function add(pid: string) { for (const wh of warehouses) { if (wh.parentId === pid && !scope.has(wh.id)) { scope.add(wh.id); add(wh.id); } } }
  add(warehouseId);
  return Array.from(scope).filter((id) => id !== warehouseId);
}

interface Props { products: DemoProduct[]; warehouses: DemoWarehouse[]; orgSlug: string; }
type TransferType = "PULL" | "PUSH" | "SISTER";
type FormState = {
  transferType: TransferType;
  transferTypeConfigId?: string;   // links to transfer_type_config for display name + validation
  productId: string;
  fromWarehouseId: string;
  toWarehouseId: string;
  quantity: string;
  notes: string;
};

interface ApiTransferType {
  id: string;
  underlying_type: TransferType;
  display_name: string;
  is_active: boolean;
  level_permissions: Array<{ level_number: number; can_initiate: boolean; can_receive: boolean }>;
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
const lockedCls = `${inputCls} bg-gray-100 text-gray-500 cursor-not-allowed`;

const TIER_TEXT = ["text-gray-900",   "text-amber-700",  "text-red-600"  ] as const;
const TIER_BG   = ["bg-transparent",  "bg-amber-50",     "bg-red-50"     ] as const;
const TIER_ICON = ["",                "⚠",               "✕"             ] as const;

function stockTier(avail: number, reorderPoint: number): 0 | 1 | 2 {
  if (avail < 0)                                return 2;
  if (reorderPoint > 0 && avail <= reorderPoint) return 1;
  return 0;
}

interface ProductOption { id: string; name: string; sku: string; avail: number; tier: 0 | 1 | 2; sourceKnown: boolean; isControlled: boolean; override?: ProductApprovalOverride; }

function ProductSelect({ options, value, onChange }: { options: ProductOption[]; value: string; onChange: (id: string) => void; }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function close(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const selected = options.find((o) => o.id === value);

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="w-full px-2.5 py-2 text-sm border border-gray-300 rounded bg-white text-left cursor-pointer outline-none flex items-center justify-between gap-2">
        {selected ? (
          <span className="flex-1 overflow-hidden">
            <span className={`font-semibold ${TIER_TEXT[selected.tier]}`}>
              {TIER_ICON[selected.tier] && <span className="mr-1">{TIER_ICON[selected.tier]}</span>}
              {selected.name}
            </span>
            <span className="text-gray-400 text-[11px] ml-1.5">{selected.sku}</span>
            {selected.isControlled && (
              <span className="ml-1.5" title={selected.override ? buildOverrideTooltip(selected.override) : t("product.controlled_tooltip")}>🔒</span>
            )}
          </span>
        ) : (
          <span className="text-gray-400 flex-1">— {t("receive_panel.select_product")} —</span>
        )}
        <span className="text-gray-400 text-[10px] shrink-0">▾</span>
      </button>

      {open && (
        <div className="absolute top-[calc(100%+2px)] left-0 right-0 z-[300] bg-white border border-gray-300 rounded shadow-xl max-h-[300px] overflow-y-auto">
          {options.length === 0 && <p className="p-3 text-gray-400 text-sm text-center">{t("common.no_data")}</p>}
          {options.map((o) => (
            <div key={o.id} onMouseDown={() => { onChange(o.id); setOpen(false); }}
              className={`px-2.5 py-2.5 cursor-pointer text-sm border-b border-gray-100 flex items-center justify-between gap-2 ${o.id === value ? TIER_BG[o.tier] : "hover:bg-gray-50"}`}>
              <span className="flex-1 overflow-hidden">
                <span className={`${TIER_TEXT[o.tier]} ${o.tier > 0 ? "font-semibold" : "font-medium"}`}>
                  {TIER_ICON[o.tier] && <span className="mr-1">{TIER_ICON[o.tier]}</span>}
                  {o.name}
                </span>
                <span className="text-gray-400 text-[11px] ml-1.5">{o.sku}</span>
                {o.isControlled && (
                  <span className="ml-1.5" title={o.override ? buildOverrideTooltip(o.override) : t("product.controlled_tooltip")}>🔒</span>
                )}
              </span>
              {o.sourceKnown && (
                <span className={`text-[11px] font-bold shrink-0 px-1.5 py-0.5 rounded ${TIER_TEXT[o.tier]} ${TIER_BG[o.tier]}`}>
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

export function NewTransferPanel({ products, warehouses, orgSlug }: Props) {
  const qc = useQueryClient();
  const { addTransfer, getAvailable, getOnHand } = useInventoryStore();

  const user     = getSession();
  const tenantId = user?.tenantId ?? "";
  const guard    = useWriteGuard();
  const gp       = guardProps(guard);

  // ── Fetch tenant transfer type configs (gateway mode only) ─────────────────
  const isGateway = !!process.env.NEXT_PUBLIC_API_URL;
  const { data: apiTransferTypes = [] } = useQuery<ApiTransferType[]>({
    queryKey: ["transfer-types-panel", tenantId],
    queryFn:  () => api.get<ApiTransferType[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    enabled:  isGateway && !!tenantId,
    staleTime: 60_000,
  });

  // Active types from API, or fall back to static default set in BFF mode
  const activeTypes: ApiTransferType[] = isGateway && apiTransferTypes.length > 0
    ? apiTransferTypes.filter((t) => t.is_active)
    : [
        { id: "", underlying_type: "PULL",   display_name: t("transfer_panel.pull_desc"),   is_active: true, level_permissions: [] },
        { id: "", underlying_type: "PUSH",   display_name: t("transfer_panel.push_desc"),   is_active: true, level_permissions: [] },
        { id: "", underlying_type: "SISTER", display_name: t("transfer_panel.sister_desc"), is_active: true, level_permissions: [] },
      ];

  // Check whether the current user's level can initiate a given transfer type
  const userLevel = user?.levelNumber ?? 99;
  function canUserInitiate(cfg: ApiTransferType): boolean {
    if (!cfg.level_permissions.length) return true;  // no restrictions configured
    const perm = cfg.level_permissions.find((p) => p.level_number === userLevel);
    if (!perm) return true;  // level not in config → allowed by default
    return perm.can_initiate;
  }

  const lockedWH     = user?.warehouseId;
  const userWH       = warehouses.find((w) => w.id === lockedWH);
  const lockedWHName = user?.warehouseName ?? userWH?.name ?? lockedWH ?? "";
  // canPush: facility hierarchy level_number <= 2 (L1 = Main WH, L2 = Regional WH only).
  // NEVER derive this from warehouse type string — type strings are display labels, not authority.
  // useWarehouses hook provides level_number from org_node_hierarchy.
  const canPush      = !lockedWH || ((userWH?.level_number ?? 99) <= 2);
  const defaultType: TransferType = canPush ? "PUSH" : "PULL";

  function initialForm(type: TransferType): FormState {
    const toShouldLock   = type === "PULL" || type === "SISTER";
    const fromShouldLock = type === "PUSH";
    return { transferType: type, productId: "", fromWarehouseId: (fromShouldLock && lockedWH) ? lockedWH : "", toWarehouseId: (toShouldLock && lockedWH) ? lockedWH : "", quantity: "", notes: "" };
  }

  const [open, setOpen]         = useState(false);
  const [form, setForm]         = useState<FormState>(initialForm(defaultType));
  const [error, setError]       = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [stockAlert, setStockAlert] = useState<{ fromWHName: string; productName: string; onHand: number; available: number; requested: number; canForce: boolean; } | null>(null);

  // When warehouse data loads asynchronously and canPush flips true,
  // reset the form to use the now-correct defaultType — but only if panel is closed.
  const prevCanPush = useRef(canPush);
  useEffect(() => {
    if (prevCanPush.current !== canPush && !open) {
      setForm(initialForm(defaultType));
    }
    prevCanPush.current = canPush;
  }, [canPush, open, defaultType]);  // eslint-disable-line react-hooks/exhaustive-deps

  // reset() always uses the live defaultType so opening the panel picks up latest canPush state
  const reset = useCallback(() => {
    setForm(initialForm(defaultType));
    setError("");
    setStockAlert(null);
  }, [defaultType, lockedWH]);  // eslint-disable-line react-hooks/exhaustive-deps
  function setField(key: keyof FormState, val: string) { setForm((f) => ({ ...f, [key]: val })); setError(""); setStockAlert(null); }
  function changeType(type: TransferType, configId?: string) {
    setForm({ ...initialForm(type), transferTypeConfigId: configId });
    setError(""); setStockAlert(null);
  }

  const isPull    = form.transferType === "PULL";
  const isSister  = form.transferType === "SISTER";
  const isPush    = form.transferType === "PUSH";
  const toIsLocked   = !!lockedWH && (isPull || isSister);
  const fromIsLocked = !!lockedWH && isPush;
  const effectiveFrom = fromIsLocked ? (lockedWH ?? "") : form.fromWarehouseId;
  const effectiveTo   = toIsLocked   ? (lockedWH ?? "") : form.toWarehouseId;

  const ancestorIds   = lockedWH ? getAncestorScope(lockedWH, warehouses)   : null;
  const descendantIds = lockedWH ? getDescendantScope(lockedWH, warehouses) : null;

  const fromOptions = warehouses.filter((w) => {
    if (w.id === effectiveTo)          return false;
    if (lockedWH && w.id === lockedWH) return false;
    if (isPull && lockedWH && ancestorIds && ancestorIds.length > 0) return ancestorIds.includes(w.id);
    return true;
  });
  const toOptions = warehouses.filter((w) => {
    if (w.id === effectiveFrom)        return false;
    if (lockedWH && w.id === lockedWH) return false;
    if (isPush && lockedWH && descendantIds && descendantIds.length > 0) return descendantIds.includes(w.id);
    return true;
  });

  // Estimated transfer value (Step 5C) — displayed when unit_price is available
  const selectedProduct = products.find((p) => p.id === form.productId);
  const unitPrice: number | undefined = (selectedProduct as DemoProduct & { unit_price?: number })?.unit_price;
  const qty = parseFloat(form.quantity);
  const estimatedValue = unitPrice && qty > 0 ? unitPrice * qty : undefined;

  // Dispatch preview — information only. Never blocks the request and nothing
  // from it is sent with the request; lots are allocated at approval.
  const [preview, setPreview] = useState<DispatchPreviewApi | null>(null);
  const previewProductId = form.productId;
  useEffect(() => {
    setPreview(null);
    if (!open || !previewProductId || !effectiveFrom || !(qty > 0)) return;
    let stale = false;
    const timer = setTimeout(() => {
      fetchDispatchPreview(previewProductId, effectiveFrom, qty)
        .then((data) => { if (!stale) setPreview(data); })
        .catch((err: unknown) => { if (!stale) console.warn("[NewTransferPanel] dispatch preview failed:", err); });
    }, 400);
    return () => { stale = true; clearTimeout(timer); };
  }, [open, previewProductId, effectiveFrom, qty]);

  const productOptions: ProductOption[] = [...products]
    .map((p) => { const base = effectiveFrom ? (p.stock[effectiveFrom] ?? 0) : 0; const avail = effectiveFrom ? getAvailable(p.id, effectiveFrom, base) : 0; return { id: p.id, name: p.name, sku: p.sku, avail, tier: effectiveFrom ? stockTier(avail, p.reorderPoint) : 0, sourceKnown: !!effectiveFrom, isControlled: !!(p.approval_overrides && Object.keys(p.approval_overrides).length > 0), override: p.approval_overrides?.[form.transferType] } as ProductOption; })
    .sort((a, b) => a.tier - b.tier || a.name.localeCompare(b.name));

  async function doCreate(skipStockCheck: boolean) {
    if (submitting) return;
    setError("");
    const blockedReason = guard.reason();
    if (blockedReason) { setError(blockedReason); return; }
    if (!form.productId)  { setError(t("receive_panel.error_product"));   return; }
    if (!effectiveFrom)   { setError(t("transfer_panel.error_from"));     return; }
    if (!effectiveTo)     { setError(t("transfer_panel.error_to"));       return; }
    if (effectiveFrom === effectiveTo) { setError(t("transfer_panel.error_same")); return; }
    const qty = parseFloat(form.quantity);
    if (!qty || qty <= 0) { setError(t("receive_panel.error_qty")); return; }
    const product = products.find((p) => p.id === form.productId);
    const fromWH  = warehouses.find((w) => w.id === effectiveFrom);
    const toWH    = warehouses.find((w) => w.id === effectiveTo);
    if (!skipStockCheck && product && effectiveFrom) {
      const baseStock = product.stock[effectiveFrom] ?? 0;
      const liveAvail = getAvailable(product.id, effectiveFrom, baseStock);
      if (qty > liveAvail) {
        setStockAlert({ fromWHName: fromWH?.name ?? effectiveFrom, productName: product.name, onHand: getOnHand(product.id, effectiveFrom, baseStock), available: liveAvail, requested: qty, canForce: isPull || isSister });
        return;
      }
    }
    setSubmitting(true);
    try {
      const created = await api.post<{ transfer_id: string; total_value?: number; currency?: string }>("/api/v1/inventory/transfers/", {
        transfer_type: form.transferType,
        from_warehouse_id: effectiveFrom,
        to_warehouse_id: effectiveTo,
        lines: [{ product_id: form.productId, quantity: qty }],
        notes: form.notes || null,
        transfer_type_config_id: form.transferTypeConfigId || null,
      });
      const transferId  = created.transfer_id;
      const displayRef  = transferId.slice(0, 8).toUpperCase();
      const entry: TransferEntry = { id: transferId, ref: displayRef, tenantSlug: orgSlug, productId: form.productId, fromWarehouseId: effectiveFrom, fromWarehouseName: fromWH?.name ?? effectiveFrom, toWarehouseId: effectiveTo, toWarehouseName: toWH?.name ?? effectiveTo, quantity: qty, issuedDate: new Date().toISOString(), status: "DRAFT" };
      addTransfer(entry);
      void qc.invalidateQueries({ queryKey: ["transfers", orgSlug] });
      reset(); setOpen(false);
      notify({ kind: "success", message: `${t("transfer_panel.created")} ${displayRef} — ${fromWH?.name} → ${toWH?.name}.` });
    } catch (err: unknown) { setError(err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")); }
    finally { setSubmitting(false); }
  }

  const onSubmit = (e: React.FormEvent) => { e.preventDefault(); void doCreate(false); };

  return (
    <>
      <button
        onClick={() => { if (gp.disabled) return; reset(); setOpen(true); }}
        disabled={gp.disabled}
        title={gp.title}
        className={`px-4 py-2 font-bold text-sm rounded border-0 ${gp.disabled ? "bg-gray-200 text-gray-400 cursor-not-allowed" : "bg-eth-gold text-[#0f2d1f] cursor-pointer"}`}
      >
        + {t("inventory.transfer.title")}
      </button>

      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 bg-black/35 z-[100] backdrop-blur-sm" />}

      <div className={`fixed top-0 right-0 w-[440px] h-screen bg-white z-[110] shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="px-6 py-5 bg-[#0f2d1f] flex items-center justify-between">
          <div>
            <p className="font-bold text-base text-white m-0">{t("transfer_panel.title")}</p>
            <p className="text-xs text-emerald-300 mt-0.5">{t("transfer_panel.subtitle")}</p>
          </div>
          <button onClick={() => setOpen(false)} className="bg-white/10 border-0 cursor-pointer text-white text-lg w-8 h-8 rounded flex items-center justify-center">✕</button>
        </div>

        <form onSubmit={onSubmit} className="flex-1 overflow-y-auto p-6">
          <PanelError message={error} />
          {gp.title && (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-4">
              {gp.title}
            </div>
          )}

          <Field label={t("transfer_panel.type_label")}>
            <select
              value={form.transferType}
              onChange={(e) => {
                const cfg = activeTypes.find((tt) => tt.underlying_type === e.target.value);
                changeType(e.target.value as TransferType, cfg?.id || undefined);
              }}
              className={selectCls}
            >
              {activeTypes
                .filter((tt) => tt.underlying_type !== "PUSH" || canPush)
                .map((tt) => {
                  const blocked = !canUserInitiate(tt);
                  return (
                    <option key={tt.underlying_type} value={tt.underlying_type} disabled={blocked}>
                      {tt.display_name}{blocked ? ` (${t("transfer_panel.level_cannot_initiate")})` : ""}
                    </option>
                  );
                })}
            </select>
          </Field>

          {lockedWH && (
            <div className="bg-green-50 border border-emerald-200 rounded px-3 py-2 text-xs text-green-800 mb-4">
              {isPush ? `📤 ${t("transfer_panel.from_note")}: ${lockedWHName}` : isSister ? `↔ ${t("transfer_panel.sister_note")}: ${lockedWHName}` : `📥 ${t("transfer_panel.to_note")}: ${lockedWHName}`}
            </div>
          )}

          <Field label={t("table.product")} hint={effectiveFrom ? t("transfer_panel.color_hint") : t("transfer_panel.select_source_first")}>
            <ProductSelect options={productOptions} value={form.productId} onChange={(id) => setField("productId", id)} />
            {(() => {
              const override = productOptions.find((o) => o.id === form.productId)?.override;
              return override ? (
                <p className="text-xs text-amber-700 mt-1.5 flex items-start gap-1">
                  <span>🔒</span><span>{buildOverrideTooltip(override)}</span>
                </p>
              ) : null;
            })()}
          </Field>

          <Field label={isPull || isSister ? t("transfer_panel.from_supply") : t("inventory.transfer.from_warehouse")} hint={fromIsLocked ? t("transfer_panel.your_facility") : undefined}>
            {fromIsLocked ? (
              <input value={lockedWHName} disabled className={lockedCls} />
            ) : (
              <select value={form.fromWarehouseId} onChange={(e) => setField("fromWarehouseId", e.target.value)} className={selectCls} required>
                <option value="">— {t("transfer_panel.origin")} —</option>
                {fromOptions.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            )}
          </Field>

          <Field label={isPull || isSister ? t("transfer_panel.to_your_wh") : t("inventory.transfer.to_warehouse")} hint={toIsLocked ? t("transfer_panel.locked") : undefined}>
            {toIsLocked ? (
              <input value={lockedWHName} disabled className={lockedCls} />
            ) : (
              <select value={form.toWarehouseId} onChange={(e) => setField("toWarehouseId", e.target.value)} className={selectCls} required>
                <option value="">— {t("transfer_panel.destination")} —</option>
                {toOptions.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            )}
          </Field>

          <Field label={t("lots.quantity")}>
            <input type="number" min="1" step="1" value={form.quantity} onChange={(e) => setField("quantity", e.target.value)} placeholder="e.g. 1455" className={inputCls} required />
            {estimatedValue !== undefined && (
              <p className="text-xs text-emerald-700 mt-1">
                💰 {t("transfer_panel.estimated_value")}: ETB {estimatedValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </p>
            )}
          </Field>

          {preview && <DispatchPreviewInfo preview={preview} />}

          <Field label={t("audit.notes")} hint={`(${t("receive_panel.optional")})`}>
            <textarea value={form.notes} onChange={(e) => setField("notes", e.target.value)} placeholder={t("transfer_panel.notes_placeholder")} rows={3} className={`${inputCls} resize-y`} />
          </Field>

          {stockAlert && (
            <div className="bg-red-50 border-2 border-red-600 rounded-md p-3.5 mb-3">
              <p className="font-bold text-sm text-red-600 mb-2 flex items-center gap-1.5">
                ⛔ {t("transfer_panel.insufficient")} — {stockAlert.fromWHName}
              </p>
              <div className="text-xs text-gray-700 flex flex-col gap-1">
                <div><strong>{t("table.product")}:</strong> {stockAlert.productName}</div>
                <div className="flex gap-5">
                  <span><strong>{t("inventory.on_hand")}:</strong> {formatQty(stockAlert.onHand)}</span>
                  <span><strong>{t("inventory.available")}:</strong> <span className="text-red-600 font-bold">{formatQty(stockAlert.available)}</span></span>
                </div>
                <div><strong>{t("transfer_panel.requested")}:</strong> {formatQty(stockAlert.requested)} <span className="text-red-600 ml-2">({formatQty(stockAlert.requested - stockAlert.available)} over)</span></div>
              </div>
              {stockAlert.canForce ? (
                <div className="mt-2.5 flex gap-2">
                  <button type="button" disabled={gp.disabled} title={gp.title} onClick={() => { setStockAlert(null); void doCreate(true); }} className={`flex-1 py-1.5 px-3 text-white font-bold text-xs rounded border-0 ${gp.disabled ? "bg-gray-300 cursor-not-allowed" : "bg-red-600 cursor-pointer"}`}>{t("transfer_panel.proceed_anyway")}</button>
                  <button type="button" onClick={() => setStockAlert(null)} className="py-1.5 px-3 bg-gray-100 text-gray-700 font-semibold text-xs rounded border border-gray-300 cursor-pointer">{t("common.cancel")}</button>
                </div>
              ) : (
                <p className="text-[11px] text-gray-400 mt-2">{t("transfer_panel.reduce_qty")}</p>
              )}
            </div>
          )}

        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => setOpen(false)} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          <button onClick={onSubmit as unknown as React.MouseEventHandler} disabled={submitting || gp.disabled} title={gp.title} className={`flex-[2] py-2.5 bg-[#0f2d1f] text-eth-gold font-bold text-sm rounded border-0 ${(submitting || gp.disabled) ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}>
            {submitting ? t("common.saving") : t("inventory.transfer.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
