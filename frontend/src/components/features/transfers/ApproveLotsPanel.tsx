"use client";

import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { formatExpiry } from "@/components/features/transfers/TransferLotDetails";
import {
  PreviewLotList,
  PreviewWarnings,
  strategyLabel,
  type DispatchPreviewApi,
} from "@/components/features/transfers/DispatchPreview";

const REASON_MAX = 500;

/** Approval errors the panel translates; anything else gets the generic message. */
const APPROVE_ERROR_CODES = new Set([
  "OVERRIDE_REASON_REQUIRED",
  "OVERRIDE_NOT_PERMITTED",
  "LOT_SELECTION_NOT_ALLOWED",
  "INSUFFICIENT_STOCK",
  "INSUFFICIENT_LOT_STOCK",
  "LOT_EXPIRED",
  "LOT_NOT_IN_WAREHOUSE",
  "SELECTION_QTY_MISMATCH",
]);

/** A batch-tracked transfer line with the engine's suggested split. */
export interface ApproveLine {
  lineId: string;
  productId: string;
  productName: string;
  quantity: number;
  /** Preview at the source warehouse for the line quantity; strategy is non-null. */
  preview: DispatchPreviewApi;
}

/** Body of POST {transfers base path}/{id}/approve when the approver changes lots. */
export interface ApproveLotsBody {
  lot_selections: Array<{ line_id: string; lots: Array<{ lot_id: string; quantity: number }> }>;
  override_reason?: string;
}

export interface ApproveFailure {
  message: string;
  /** Extra line under the message, e.g. usable / expired quantities. */
  detail?: string;
}

/** Translated message for a failed approval; never a raw code or id. */
export function approveFailure(err: unknown): ApproveFailure {
  const e = err as { code?: string; detail?: Record<string, unknown> };
  const code = e.code ?? "";
  if (!APPROVE_ERROR_CODES.has(code)) return { message: t("errors.INTERNAL_ERROR") };
  const failure: ApproveFailure = { message: t(`errors.${code}`) };
  if (code === "INSUFFICIENT_STOCK") {
    const usable  = Number(e.detail?.available);
    const expired = Number(e.detail?.expired_qty);
    if (e.detail?.available != null && e.detail?.expired_qty != null && isFinite(usable) && isFinite(expired)) {
      failure.detail = t("transfers.approve.stock_detail")
        .replace("{usable}", formatQty(usable))
        .replace("{expired}", formatQty(expired));
    }
  }
  return failure;
}

/* ── GET /api/v1/inventory/lots — the parts the picker reads ─────────────── */
interface LotApi {
  lot_id: string;
  lot_number: string;
  quantity: string;
  expiry_date: string | null;
}

/** Quantities are compared at 4 decimals (NUMERIC(15,4) on the server). */
const SCALE = 10_000;
const scaled = (n: number): number => Math.round(n * SCALE);

/** "" counts as 0; otherwise a non-negative number with at most 4 decimals. */
function parseQty(raw: string): number | null {
  const s = raw.trim();
  if (s === "") return 0;
  if (!/^\d+(\.\d{1,4})?$/.test(s)) return null;
  return Number(s);
}

/** lot_id (lowercased) → scaled quantity, zero quantities left out. */
function suggestedMap(preview: DispatchPreviewApi): Map<string, number> {
  const m = new Map<string, number>();
  for (const lot of preview.lines) {
    const q = scaled(Number(lot.quantity));
    if (q > 0) m.set(lot.lot_id.toLowerCase(), (m.get(lot.lot_id.toLowerCase()) ?? 0) + q);
  }
  return m;
}

function sameSplit(a: Map<string, number>, b: Map<string, number>): boolean {
  if (a.size !== b.size) return false;
  let same = true;
  a.forEach((q, id) => { if (b.get(id) !== q) same = false; });
  return same;
}

/**
 * Final-approver panel: the engine's suggested lots per batch-tracked line, with
 * an optional "Change lots" editor. Unchanged → onSubmit(null) (today's approve);
 * a different split → onSubmit({ lot_selections, override_reason }). Whether the
 * approver may change lots is decided by the server, not guessed here.
 */
export function ApproveLotsPanel({
  transferRef,
  sourceWarehouseId,
  lines,
  onClose,
  onSubmit,
}: {
  transferRef: string;
  sourceWarehouseId: string;
  lines: ApproveLine[];
  onClose: () => void;
  /** Resolves to null when the panel should close, or to the error to show. */
  onSubmit: (body: ApproveLotsBody | null) => Promise<ApproveFailure | null>;
}) {
  const { isOnline } = useOfflineSync();
  const gp = guardProps(useWriteGuard());

  // lineId → { lotId → typed quantity }; a line absent from the map keeps the suggestion.
  const [edits, setEdits]           = useState<Record<string, Record<string, string>>>({});
  const [reason, setReason]         = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure]       = useState<ApproveFailure | null>(null);

  const lotQueries = useQueries({
    queries: lines.map((line) => ({
      queryKey: ["transfer-approve-lots", line.productId, sourceWarehouseId],
      queryFn:  () => {
        const qs = new URLSearchParams({ product_id: line.productId, warehouse_id: sourceWarehouseId, status: "ACTIVE" });
        return api.get<LotApi[]>(`/api/v1/inventory/lots?${qs.toString()}`);
      },
      enabled:   line.lineId in edits,
      staleTime: 0,
    })),
  });

  function startEditing(line: ApproveLine) {
    setFailure(null);
    const initial: Record<string, string> = {};
    for (const lot of line.preview.lines) initial[lot.lot_id.toLowerCase()] = String(Number(lot.quantity));
    setEdits((prev) => ({ ...prev, [line.lineId]: initial }));
  }
  function stopEditing(line: ApproveLine) {
    setFailure(null);
    setEdits((prev) => {
      const next = { ...prev };
      delete next[line.lineId];
      return next;
    });
  }
  function setLotQty(line: ApproveLine, lotId: string, value: string) {
    setFailure(null);
    setEdits((prev) => ({ ...prev, [line.lineId]: { ...prev[line.lineId], [lotId.toLowerCase()]: value } }));
  }

  // Per-line view of the edit: the chosen split, whether it is valid, whether it differs.
  const states = lines.map((line, i) => {
    const edit = edits[line.lineId];
    const query = lotQueries[i];
    if (!edit) return { line, edit, query, valid: true, differs: false, chosen: [] as Array<{ lot_id: string; quantity: number }>, total: 0 };
    const lots = query?.data;
    if (!lots) return { line, edit, query, valid: false, differs: false, chosen: [], total: 0 };
    let valid = true;
    let total = 0;
    const chosen: Array<{ lot_id: string; quantity: number }> = [];
    const chosenMap = new Map<string, number>();
    for (const lot of lots) {
      const qty = parseQty(edit[lot.lot_id.toLowerCase()] ?? "");
      if (qty === null || scaled(qty) > scaled(Number(lot.quantity))) { valid = false; continue; }
      if (qty > 0) {
        total += scaled(qty);
        chosen.push({ lot_id: lot.lot_id, quantity: qty });
        chosenMap.set(lot.lot_id.toLowerCase(), scaled(qty));
      }
    }
    if (total !== scaled(line.quantity)) valid = false;
    return { line, edit, query, valid, differs: !sameSplit(chosenMap, suggestedMap(line.preview)), chosen, total: total / SCALE };
  });

  const anyDiffers     = states.some((s) => s.differs);
  const reasonRequired = states.some((s) => s.differs && s.line.preview.strategy === "FEFO");
  const allValid       = states.every((s) => s.valid);
  const reasonMissing  = reasonRequired && !reason.trim();

  const blocked = !isOnline || gp.disabled;
  const blockedReason = !isOnline ? t("errors.OFFLINE") : gp.title;

  async function submit() {
    if (submitting || blocked || !allValid || reasonMissing) return;
    setSubmitting(true);
    setFailure(null);
    try {
      let body: ApproveLotsBody | null = null;
      if (anyDiffers) {
        body = {
          lot_selections: states
            .filter((s) => s.differs)
            .map((s) => ({ line_id: s.line.lineId, lots: s.chosen })),
        };
        if (reason.trim()) body.override_reason = reason.trim();
      }
      setFailure(await onSubmit(body));
    } finally {
      setSubmitting(false);
    }
  }

  const TH = "px-2 py-2 text-left text-[10px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap";
  const TD = "px-2 py-2 text-xs text-gray-700 align-top";

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 bg-black/40 z-[200]" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg p-6 z-[201] shadow-2xl w-[640px] max-w-[95vw] max-h-[88vh] overflow-y-auto">
        <p className="font-bold text-base text-gray-900 mb-1">
          {t("transfers.approve.title").replace("{ref}", transferRef)}
        </p>
        <p className="text-sm text-gray-500 mb-4">{t("transfers.approve.intro")}</p>

        {blockedReason && (
          <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
            {blockedReason}
          </p>
        )}

        {states.map((state) => {
          const { line, edit, query } = state;
          const lots = query?.data ?? [];
          return (
            <div key={line.lineId} className="border border-gray-200 rounded p-3.5 mb-4">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                  <p className="font-semibold text-sm text-gray-900 m-0">{line.productName}</p>
                  <p className="text-xs text-gray-500 mt-0.5 mb-0">
                    {t("transfers.approve.line_quantity").replace("{qty}", formatQty(line.quantity))}
                    {" · "}
                    {strategyLabel(line.preview.strategy ?? "")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => (edit ? stopEditing(line) : startEditing(line))}
                  className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border border-gray-300 bg-white text-gray-700 cursor-pointer"
                >
                  {edit ? t("transfers.approve.use_suggested") : t("transfers.approve.change_lots")}
                </button>
              </div>

              {!edit && (
                <>
                  <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-1">
                    {t("transfers.approve.suggested")}
                  </p>
                  <PreviewLotList lots={line.preview.lines} />
                  <PreviewWarnings preview={line.preview} />
                </>
              )}

              {edit && query?.isLoading && <p className="text-xs text-gray-400">{t("common.loading")}</p>}
              {edit && query?.isError && <p className="text-xs text-red-600">{t("transfers.approve.lots_load_failed")}</p>}
              {edit && query?.isSuccess && lots.length === 0 && (
                <p className="text-xs text-gray-400 italic">{t("transfers.approve.no_active_lots")}</p>
              )}
              {edit && query?.isSuccess && lots.length > 0 && (
                <>
                  <div className="overflow-x-auto border border-gray-200 rounded">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr className="bg-gray-50 border-b border-gray-200">
                          <th className={TH}>{t("transfers.lots.col_lot")}</th>
                          <th className={TH}>{t("transfers.lots.col_expiry")}</th>
                          <th className={TH}>{t("transfers.approve.col_available")}</th>
                          <th className={TH}>{t("transfers.lots.col_quantity")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lots.map((lot) => {
                          const raw     = edit[lot.lot_id.toLowerCase()] ?? "";
                          const qty     = parseQty(raw);
                          const invalid = qty === null || scaled(qty) > scaled(Number(lot.quantity));
                          return (
                            <tr key={lot.lot_id} className="border-b border-gray-100">
                              <td className={`${TD} font-mono font-semibold`}>{lot.lot_number}</td>
                              <td className={TD}>{formatExpiry(lot.expiry_date)}</td>
                              <td className={`${TD} font-semibold text-gray-900`}>{formatQty(lot.quantity)}</td>
                              <td className={TD}>
                                <input
                                  type="number" min="0" max={Number(lot.quantity)} step="any"
                                  aria-label={t("transfers.lots.col_quantity")}
                                  value={raw}
                                  onChange={(e) => setLotQty(line, lot.lot_id, e.target.value)}
                                  className={`w-24 px-2 py-1 text-sm rounded border outline-none ${invalid ? "border-red-600" : "border-gray-300"}`}
                                />
                                {invalid && (
                                  <p className="text-[11px] text-red-600 mt-1 max-w-[180px]">
                                    {t("transfers.approve.err_quantity").replace("{available}", formatQty(lot.quantity))}
                                  </p>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {scaled(state.total) !== scaled(line.quantity) && (
                    <p className="text-[11px] text-red-600 mt-1.5">
                      {t("transfers.approve.err_total")
                        .replace("{chosen}", formatQty(state.total))
                        .replace("{required}", formatQty(line.quantity))}
                    </p>
                  )}
                </>
              )}
            </div>
          );
        })}

        {anyDiffers && (
          <div className="mb-4">
            <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
              {t("transfers.approve.reason_label")}
              <span className="text-[11px] font-normal normal-case text-gray-400 ml-1.5">
                ({reasonRequired ? t("transfers.approve.reason_required") : t("receive_panel.optional")})
              </span>
            </label>
            <textarea
              value={reason}
              maxLength={REASON_MAX}
              rows={2}
              required={reasonRequired}
              aria-label={t("transfers.approve.reason_label")}
              placeholder={t("transfers.approve.reason_placeholder")}
              onChange={(e) => { setReason(e.target.value); setFailure(null); }}
              className={`w-full px-2.5 py-2 text-sm rounded border outline-none resize-y ${reasonMissing ? "border-red-600" : "border-gray-300"}`}
            />
            {reasonMissing && (
              <p className="text-[11px] text-red-600 mt-1">{t("errors.OVERRIDE_REASON_REQUIRED")}</p>
            )}
          </div>
        )}

        {failure && (
          <div className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
            <p className="m-0">{failure.message}</p>
            {failure.detail && <p className="font-normal mt-1 mb-0">{failure.detail}</p>}
          </div>
        )}

        <div className="flex gap-2.5">
          <button onClick={onClose} className="flex-1 py-2.5 bg-gray-100 border-0 rounded-md text-sm font-semibold cursor-pointer">
            {t("common.cancel")}
          </button>
          <button
            disabled={submitting || blocked || !allValid || reasonMissing}
            title={blockedReason}
            onClick={() => void submit()}
            className="flex-[2] py-2.5 bg-eth-forest text-eth-gold border-0 rounded-md text-sm font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting
              ? t("common.loading")
              : anyDiffers ? t("transfers.approve.submit_changed") : t("transfers.approve.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
