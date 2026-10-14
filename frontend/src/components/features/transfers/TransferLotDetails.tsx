"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import { ResolveDiscrepancyDialog, type ResolveTarget } from "./ResolveDiscrepancyDialog";
import { transferDetailKey } from "./transferQueryKeys";

export { transferDetailKey };

/* ── GET /{transfers base path}/{id} — the parts the receive side reads ──── */
export interface TransferLineApi {
  line_id: string;
  product_id: string;
  product_name: string;
  sku: string;
  quantity: string;
  uom: string;
}

export interface TransferLotAllocationApi {
  line_id: string;
  product_id: string;
  lot_id: string;
  lot_number: string | null;
  expiry_date: string | null;
  quantity: string;
  is_override: boolean;
}

export interface TransferDiscrepancyApi {
  id: string;
  transfer_line_id: string;
  product_id: string;
  lot_id: string | null;
  lot_number: string | null;
  sent_quantity: string;
  received_quantity: string;
  missing_quantity: string;
  reason: string;
  note: string | null;
  status: string;
  created_at: string;
  // Set once the row is RESOLVED.
  resolution?: string | null;
  resolved_lot_id?: string | null;
  resolved_lot_number?: string | null;
  resolution_note?: string | null;
  resolved_by?: string | null;
  resolved_at?: string | null;
}

/** GET …/transfers/discrepancies — a discrepancy with the transfer it belongs to. */
export interface TransferDiscrepancyListItemApi extends TransferDiscrepancyApi {
  transfer_order_id: string;
  transfer_type: string;
  from_warehouse_id: string;
  to_warehouse_id: string;
}

export interface TransferReceiptDetail {
  transfer_id: string;
  status: string;
  from_warehouse_id?: string;
  lines?: TransferLineApi[];
  lot_allocations?: TransferLotAllocationApi[];
  discrepancies?: TransferDiscrepancyApi[];
}

/** Lots are allocated at approval — the split exists from APPROVED onward. */
const LOT_SPLIT_STATUSES = new Set([
  "APPROVED", "ADVISED", "ISSUED", "IN_TRANSIT", "PARTIALLY_RECEIVED", "RECEIVED", "COMPLETED",
]);

export function hasLotSplit(status: string): boolean {
  return LOT_SPLIT_STATUSES.has(status);
}

export function formatExpiry(expiry: string | null): string {
  return expiry ? new Date(expiry).toLocaleDateString() : "—";
}

/** Translated label for a backend code; never the raw code. */
export function codeLabel(prefix: string, code: string): string {
  const key = `${prefix}.${code}`;
  const label = t(key);
  return label === key ? t("common.unknown") : label;
}

const TH = "px-2.5 py-1.5 text-left text-[10px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap";
const TD = "px-2.5 py-1.5 text-xs text-gray-700";

/* ── Lot split: which lots (and how much of each) make up the transfer ───── */
export function TransferLotSplit({
  lines,
  allocations,
}: {
  lines: TransferLineApi[];
  allocations: TransferLotAllocationApi[];
}) {
  const productByLine = new Map(lines.map((l) => [l.line_id.toLowerCase(), l.product_name]));
  return (
    <div>
      <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-1.5">
        {t("transfers.lots.title")}
      </p>
      {allocations.length === 0 ? (
        <p className="text-xs text-gray-400 italic">{t("transfers.lots.none")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="border-collapse bg-white border border-gray-200 rounded">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className={TH}>{t("transfers.lots.col_product")}</th>
                <th className={TH}>{t("transfers.lots.col_lot")}</th>
                <th className={TH}>{t("transfers.lots.col_expiry")}</th>
                <th className={TH}>{t("transfers.lots.col_quantity")}</th>
              </tr>
            </thead>
            <tbody>
              {allocations.map((a) => (
                <tr key={`${a.line_id}:${a.lot_id}`} className="border-b border-gray-100">
                  <td className={TD}>{productByLine.get(a.line_id.toLowerCase()) ?? "—"}</td>
                  <td className={`${TD} font-mono font-semibold`}>{a.lot_number ?? "—"}</td>
                  <td className={TD}>{formatExpiry(a.expiry_date)}</td>
                  <td className={`${TD} font-semibold text-gray-900`}>{formatQty(a.quantity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Receipt discrepancies: what came up short at receipt ────────────────── */
export function TransferDiscrepancies({
  discrepancies,
  transferId,
  fromWarehouseId,
  lines = [],
  canResolve = false,
  onResolved,
}: {
  discrepancies: TransferDiscrepancyApi[];
  /** The resolve props are optional: callers that omit them get a read-only table. */
  transferId?: string;
  fromWarehouseId?: string;
  lines?: TransferLineApi[];
  canResolve?: boolean;
  onResolved?: () => void;
}) {
  const [resolving, setResolving] = useState<ResolveTarget | null>(null);
  if (discrepancies.length === 0) return null;

  const productNameById = new Map(lines.map((l) => [l.product_id.toLowerCase(), l.product_name]));
  // The dialog loads lots at the source warehouse, so the action needs it.
  const showAction = canResolve && !!transferId && !!fromWarehouseId;

  return (
    <div>
      <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-1.5">
        {t("transfers.discrepancies.title")}
      </p>
      <div className="overflow-x-auto">
        <table className="border-collapse bg-white border border-gray-200 rounded">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className={TH}>{t("transfers.discrepancies.col_lot")}</th>
              <th className={TH}>{t("transfers.discrepancies.col_sent")}</th>
              <th className={TH}>{t("transfers.discrepancies.col_received")}</th>
              <th className={TH}>{t("transfers.discrepancies.col_missing")}</th>
              <th className={TH}>{t("transfers.discrepancies.col_reason")}</th>
              <th className={TH}>{t("transfers.discrepancies.col_note")}</th>
              <th className={TH}>{t("transfers.discrepancies.col_status")}</th>
              {showAction && <th className={TH}>{t("transfers.discrepancies.col_action")}</th>}
            </tr>
          </thead>
          <tbody>
            {discrepancies.map((d) => {
              const productName = productNameById.get(d.product_id.toLowerCase()) ?? "—";
              return (
                <tr key={d.id} className="border-b border-gray-100" data-testid={`discrepancy-row-${d.id}`}>
                  <td className={`${TD} font-mono font-semibold`}>{d.lot_number ?? "—"}</td>
                  <td className={TD}>{formatQty(d.sent_quantity)}</td>
                  <td className={TD}>{formatQty(d.received_quantity)}</td>
                  <td className={`${TD} font-semibold text-red-700`}>{formatQty(d.missing_quantity)}</td>
                  <td className={TD}>{codeLabel("transfers.discrepancies.reason", d.reason)}</td>
                  <td className={`${TD} max-w-[240px] break-words`}>
                    {d.note || "—"}
                    {d.status === "RESOLVED" && d.resolution_note && (
                      <span className="block mt-0.5 text-[11px] text-gray-500">
                        {t("transfers.discrepancies.resolution_note_label")}: {d.resolution_note}
                      </span>
                    )}
                  </td>
                  <td className={TD}>
                    {codeLabel("transfers.discrepancies.status", d.status)}
                    {d.status === "RESOLVED" && d.resolution && (
                      <span className="block mt-0.5 text-[11px] text-gray-500">
                        {codeLabel("transfers.discrepancies.resolution", d.resolution)}
                        {d.resolution === "RECEIVED_AS_LOT" && d.resolved_lot_number && (
                          <span className="font-mono"> · {d.resolved_lot_number}</span>
                        )}
                      </span>
                    )}
                  </td>
                  {showAction && (
                    <td className={TD}>
                      {d.status === "OPEN" && (
                        <button
                          type="button"
                          data-testid={`discrepancy-resolve-${d.id}`}
                          onClick={() => setResolving({
                            transferId: transferId ?? "",
                            discrepancyId: d.id,
                            productId: d.product_id,
                            productName,
                            fromWarehouseId: fromWarehouseId ?? "",
                            lotId: d.lot_id,
                            lotNumber: d.lot_number,
                            sent: d.sent_quantity,
                            received: d.received_quantity,
                            missing: d.missing_quantity,
                            reason: d.reason,
                            note: d.note,
                          })}
                          className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border border-cyan-200 bg-cyan-50 text-cyan-800 cursor-pointer"
                        >
                          {t("transfers.discrepancies.resolve")}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {resolving && (
        <ResolveDiscrepancyDialog
          target={resolving}
          onClose={() => setResolving(null)}
          onResolved={() => { setResolving(null); onResolved?.(); }}
        />
      )}
    </div>
  );
}

/**
 * Lot split + receipt discrepancies for one transfer, loaded from
 * GET {basePath}/{id}. Used by the expanded row on the transfers list.
 */
export function TransferRowDetails({
  transferId,
  basePath,
  canResolve,
  onResolved,
}: {
  transferId: string;
  basePath: string;
  canResolve: boolean;
  onResolved: () => void;
}) {
  const { data, isLoading, isError } = useQuery<TransferReceiptDetail>({
    queryKey: transferDetailKey(transferId),
    queryFn:  () => api.get<TransferReceiptDetail>(`${basePath}/${transferId}`),
    staleTime: 0,
  });

  if (isLoading) return <p className="text-xs text-gray-400">{t("common.loading")}</p>;
  if (isError || !data) return <p className="text-xs text-red-600">{t("transfers.receive.load_failed")}</p>;

  return (
    <div className="flex gap-8 flex-wrap items-start">
      {hasLotSplit(data.status) && (
        <TransferLotSplit lines={data.lines ?? []} allocations={data.lot_allocations ?? []} />
      )}
      <TransferDiscrepancies
        discrepancies={data.discrepancies ?? []}
        transferId={transferId}
        fromWarehouseId={data.from_warehouse_id}
        lines={data.lines ?? []}
        canResolve={canResolve}
        onResolved={onResolved}
      />
    </div>
  );
}
