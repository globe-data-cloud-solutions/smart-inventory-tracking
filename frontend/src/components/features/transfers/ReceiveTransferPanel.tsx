"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { PanelError } from "@/components/ui/PanelError";
import { formatQty } from "@/lib/utils";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import {
  formatExpiry,
  transferDetailKey,
  type TransferReceiptDetail,
} from "@/components/features/transfers/TransferLotDetails";

const REASONS = ["SHORT", "DAMAGED", "WRONG_LOT"] as const;
/** A row with no lot (non-batch line) cannot be a wrong-lot receipt — the server rejects it. */
const NO_LOT_REASONS = REASONS.filter((r) => r !== "WRONG_LOT");
const NOTE_MAX = 500;

/** Receipt errors the form translates; anything else gets the generic message. */
const RECEIPT_ERROR_CODES = new Set([
  "RECEIPT_LINES_MISMATCH",
  "RECEIPT_EXCEEDS_SENT",
  "RECEIPT_REASON_REQUIRED",
  "WRONG_LOT_NOT_BATCH",
  "INVALID_STATE_TRANSITION",
]);

/** One receipt entry: a lot of a batch line, or a whole non-batch line. */
interface ReceiptRow {
  key: string;
  lineId: string;
  lotId: string | null;
  productName: string;
  lotNumber: string | null;
  expiry: string | null;
  sent: number;
}

interface RowInput {
  received: string;
  reason: string;
  note: string;
}

function buildRows(detail: TransferReceiptDetail): ReceiptRow[] {
  const allocations = detail.lot_allocations ?? [];
  const rows: ReceiptRow[] = [];
  for (const line of detail.lines ?? []) {
    const lots = allocations.filter((a) => a.line_id.toLowerCase() === line.line_id.toLowerCase());
    if (lots.length > 0) {
      for (const lot of lots) {
        rows.push({
          key:         `${line.line_id}:${lot.lot_id}`,
          lineId:      line.line_id,
          lotId:       lot.lot_id,
          productName: line.product_name,
          lotNumber:   lot.lot_number,
          expiry:      lot.expiry_date,
          sent:        Number(lot.quantity),
        });
      }
    } else {
      rows.push({
        key:         line.line_id,
        lineId:      line.line_id,
        lotId:       null,
        productName: line.product_name,
        lotNumber:   null,
        expiry:      null,
        sent:        Number(line.quantity),
      });
    }
  }
  return rows;
}

/** 0 <= received <= sent, at most 4 decimals (NUMERIC(15,4) on the server). */
function isValidReceived(raw: string, sent: number): boolean {
  const s = raw.trim();
  if (!/^\d+(\.\d{1,4})?$/.test(s)) return false;
  const n = Number(s);
  return n >= 0 && n <= sent;
}

/**
 * Receive form for a transfer: one row per allocated lot (batch line) or per
 * line (non-batch line). Posts every row to {basePath}/{id}/receive; a row
 * received short needs a reason and becomes a discrepancy on the server.
 */
export function ReceiveTransferPanel({
  transferId,
  transferRef,
  basePath,
  onClose,
  onReceived,
}: {
  transferId: string;
  transferRef: string;
  /** The transfers base path the host screen already uses, e.g. /api/v1/inventory/transfers */
  basePath: string;
  onClose: () => void;
  onReceived: (receivedTotal: number, discrepancyCount: number) => void;
}) {
  const { isOnline } = useOfflineSync();
  const gp = guardProps(useWriteGuard());

  const [inputs, setInputs]         = useState<Record<string, RowInput>>({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError]   = useState("");

  const { data, isLoading, isError } = useQuery<TransferReceiptDetail>({
    queryKey: transferDetailKey(transferId),
    queryFn:  () => api.get<TransferReceiptDetail>(`${basePath}/${transferId}`),
    staleTime: 0,
  });

  const rows = data ? buildRows(data) : [];
  const inputFor = (row: ReceiptRow): RowInput =>
    inputs[row.key] ?? { received: String(row.sent), reason: "", note: "" };
  const setInput = (row: ReceiptRow, patch: Partial<RowInput>) => {
    setFormError("");
    setInputs((prev) => ({ ...prev, [row.key]: { ...inputFor(row), ...patch } }));
  };
  const isShort = (row: ReceiptRow): boolean => {
    const v = inputFor(row);
    return isValidReceived(v.received, row.sent) && Number(v.received) < row.sent;
  };
  /** Received outside 0..sent, or received short with no reason. */
  const isInvalid = (row: ReceiptRow): boolean =>
    !isValidReceived(inputFor(row).received, row.sent) || (isShort(row) && !inputFor(row).reason);
  const anyInvalid = rows.some(isInvalid);

  const blocked = !isOnline || gp.disabled;
  const blockedReason = !isOnline ? t("errors.OFFLINE") : gp.title;

  async function submit() {
    if (submitting || blocked || rows.length === 0 || anyInvalid) return;

    setSubmitting(true);
    setFormError("");
    try {
      const result = await api.post<TransferReceiptDetail>(`${basePath}/${transferId}/receive`, {
        lines: rows.map((row) => {
          const v = inputFor(row);
          const short = isShort(row);
          return {
            line_id:           row.lineId,
            lot_id:            row.lotId,
            received_quantity: Number(v.received),
            reason:            short ? v.reason : null,
            note:              short && v.note.trim() ? v.note.trim() : null,
          };
        }),
      });
      const receivedTotal = rows.reduce((sum, row) => sum + Number(inputFor(row).received), 0);
      onReceived(receivedTotal, result.discrepancies?.length ?? 0);
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      setFormError(RECEIPT_ERROR_CODES.has(code) ? t(`errors.${code}`) : t("errors.INTERNAL_ERROR"));
    } finally {
      setSubmitting(false);
    }
  }

  const TH = "px-2 py-2 text-left text-[10px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap";
  const TD = "px-2 py-2 text-xs text-gray-700 align-top";

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 bg-black/40 z-[200]" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg p-6 z-[201] shadow-2xl w-[920px] max-w-[95vw] max-h-[88vh] overflow-y-auto">
        <p className="font-bold text-base text-gray-900 mb-1">
          {t("transfers.receive.title").replace("{ref}", transferRef)}
        </p>
        <p className="text-sm text-gray-500 mb-4">{t("transfers.receive.intro")}</p>

        <PanelError message={formError} />

        {blockedReason && (
          <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
            {blockedReason}
          </p>
        )}

        {isLoading && <p className="text-sm text-gray-400 mb-4">{t("common.loading")}</p>}
        {(isError || (!isLoading && rows.length === 0)) && (
          <p className="text-sm text-red-600 mb-4">{t("transfers.receive.load_failed")}</p>
        )}

        {rows.length > 0 && (
          <div className="overflow-x-auto mb-4 border border-gray-200 rounded">
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className={TH}>{t("transfers.receive.col_item")}</th>
                  <th className={TH}>{t("transfers.receive.col_lot")}</th>
                  <th className={TH}>{t("transfers.receive.col_expiry")}</th>
                  <th className={TH}>{t("transfers.receive.col_sent")}</th>
                  <th className={TH}>{t("transfers.receive.col_received")}</th>
                  <th className={TH}>{t("transfers.receive.col_reason")}</th>
                  <th className={TH}>{t("transfers.receive.col_note")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const v          = inputFor(row);
                  const qtyInvalid = !isValidReceived(v.received, row.sent);
                  const short      = isShort(row);
                  const reasonErr  = short && !v.reason;
                  return (
                    <tr key={row.key} className="border-b border-gray-100">
                      <td className={`${TD} font-semibold text-gray-900`}>{row.productName}</td>
                      <td className={`${TD} font-mono`}>{row.lotNumber ?? "—"}</td>
                      <td className={TD}>{row.lotId ? formatExpiry(row.expiry) : "—"}</td>
                      <td className={`${TD} font-semibold text-gray-900`}>{formatQty(row.sent)}</td>
                      <td className={TD}>
                        <input
                          type="number" min="0" max={row.sent} step="any"
                          aria-label={t("transfers.receive.col_received")}
                          value={v.received}
                          onChange={(e) => setInput(row, { received: e.target.value })}
                          className={`w-24 px-2 py-1 text-sm rounded border outline-none ${qtyInvalid ? "border-red-600" : "border-gray-300"}`}
                        />
                        {qtyInvalid && (
                          <p className="text-[11px] text-red-600 mt-1 max-w-[160px]">
                            {t("transfers.receive.err_range").replace("{sent}", formatQty(row.sent))}
                          </p>
                        )}
                      </td>
                      <td className={TD}>
                        {short && (
                          <>
                            <select
                              aria-label={t("transfers.receive.col_reason")}
                              required
                              value={v.reason}
                              onChange={(e) => setInput(row, { reason: e.target.value })}
                              className={`px-2 py-1 text-sm rounded border outline-none bg-white ${reasonErr ? "border-red-600" : "border-gray-300"}`}
                            >
                              <option value="">{t("transfers.receive.reason_placeholder")}</option>
                              {(row.lotId ? REASONS : NO_LOT_REASONS).map((r) => (
                                <option key={r} value={r}>{t(`transfers.discrepancies.reason.${r}`)}</option>
                              ))}
                            </select>
                            {reasonErr && (
                              <p className="text-[11px] text-red-600 mt-1 max-w-[160px]">
                                {t("errors.RECEIPT_REASON_REQUIRED")}
                              </p>
                            )}
                          </>
                        )}
                      </td>
                      <td className={TD}>
                        {short && (
                          <input
                            type="text" maxLength={NOTE_MAX}
                            aria-label={t("transfers.receive.col_note")}
                            placeholder={t("transfers.receive.note_placeholder")}
                            value={v.note}
                            onChange={(e) => setInput(row, { note: e.target.value })}
                            className="w-44 px-2 py-1 text-sm rounded border border-gray-300 outline-none"
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex gap-2.5">
          <button onClick={onClose} className="flex-1 py-2.5 bg-gray-100 border-0 rounded-md text-sm font-semibold cursor-pointer">
            {t("common.cancel")}
          </button>
          <button
            disabled={submitting || blocked || rows.length === 0 || anyInvalid}
            title={blockedReason}
            onClick={() => void submit()}
            className="flex-[2] py-2.5 bg-eth-forest text-eth-gold border-0 rounded-md text-sm font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? t("common.saving") : t("transfers.receive.submit")}
          </button>
        </div>
      </div>
    </>
  );
}
