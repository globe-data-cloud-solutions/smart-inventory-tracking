"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";

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
}

export interface TransferReceiptDetail {
  transfer_id: string;
  status: string;
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

export function transferDetailKey(transferId: string): [string, string] {
  return ["transfer-detail", transferId];
}

export function formatExpiry(expiry: string | null): string {
  return expiry ? new Date(expiry).toLocaleDateString() : "—";
}

/** Translated label for a backend code; never the raw code. */
function codeLabel(prefix: string, code: string): string {
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
export function TransferDiscrepancies({ discrepancies }: { discrepancies: TransferDiscrepancyApi[] }) {
  if (discrepancies.length === 0) return null;
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
            </tr>
          </thead>
          <tbody>
            {discrepancies.map((d) => (
              <tr key={d.id} className="border-b border-gray-100">
                <td className={`${TD} font-mono font-semibold`}>{d.lot_number ?? "—"}</td>
                <td className={TD}>{formatQty(d.sent_quantity)}</td>
                <td className={TD}>{formatQty(d.received_quantity)}</td>
                <td className={`${TD} font-semibold text-red-700`}>{formatQty(d.missing_quantity)}</td>
                <td className={TD}>{codeLabel("transfers.discrepancies.reason", d.reason)}</td>
                <td className={`${TD} max-w-[240px] break-words`}>{d.note || "—"}</td>
                <td className={TD}>{codeLabel("transfers.discrepancies.status", d.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Lot split + receipt discrepancies for one transfer, loaded from
 * GET {basePath}/{id}. Used by the expanded row on the transfers list.
 */
export function TransferRowDetails({ transferId, basePath }: { transferId: string; basePath: string }) {
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
      <TransferDiscrepancies discrepancies={data.discrepancies ?? []} />
    </div>
  );
}
