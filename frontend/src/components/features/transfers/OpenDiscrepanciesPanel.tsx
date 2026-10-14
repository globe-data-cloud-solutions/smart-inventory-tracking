"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import { ResolveDiscrepancyDialog, type ResolveTarget } from "./ResolveDiscrepancyDialog";
import { codeLabel, type TransferDiscrepancyListItemApi } from "./TransferLotDetails";
import { openDiscrepanciesKey } from "./transferQueryKeys";

const TH = "px-3 py-2 text-left text-[10px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap";
const TD = "px-3 py-2 text-xs text-gray-700";

/** Same short reference the Transfers list shows (first 8 chars of the id). */
function shortRef(transferId: string): string {
  return transferId.slice(0, 8).toUpperCase();
}

/**
 * Collapsible list of every OPEN receipt discrepancy the caller can see
 * (GET {basePath}/discrepancies?status=OPEN — the backend scopes by node).
 * Renders nothing when there are none or the call fails.
 */
export function OpenDiscrepanciesPanel({
  org,
  basePath,
  canResolve,
  productName,
  onResolved,
}: {
  org: string;
  basePath: string;
  canResolve: boolean;
  /** Resolves a product id to its name; undefined when the page cannot. */
  productName: (productId: string) => string | undefined;
  onResolved: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [resolving, setResolving] = useState<ResolveTarget | null>(null);

  const { data, isError, error } = useQuery<TransferDiscrepancyListItemApi[]>({
    queryKey: openDiscrepanciesKey(),
    queryFn: () => api.get<TransferDiscrepancyListItemApi[]>(`${basePath}/discrepancies?status=OPEN`),
    retry: false,
    staleTime: 0,
  });

  if (isError) {
    console.error("[OpenDiscrepanciesPanel] list failed:", error);
    return null;
  }
  const rows = data ?? [];
  if (rows.length === 0) return null;

  return (
    <div data-testid="open-discrepancies-panel" className="mb-6 bg-white border border-amber-200 rounded overflow-hidden">
      <button
        type="button"
        data-testid="open-discrepancies-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 bg-amber-50 border-0 text-left cursor-pointer text-sm font-bold text-amber-900"
      >
        <span className="text-xs">{open ? "▾" : "▸"}</span>
        {t("transfers.discrepancies.panel_title").replace("{count}", String(rows.length))}
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className={TH}>{t("transfers.discrepancies.col_transfer")}</th>
                <th className={TH}>{t("transfers.discrepancies.col_product")}</th>
                <th className={TH}>{t("transfers.discrepancies.col_lot")}</th>
                <th className={TH}>{t("transfers.discrepancies.col_missing")}</th>
                <th className={TH}>{t("transfers.discrepancies.col_reason")}</th>
                <th className={TH}>{t("transfers.discrepancies.col_received_on")}</th>
                {canResolve && <th className={TH}>{t("transfers.discrepancies.col_action")}</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const name = productName(d.product_id) ?? "—";
                return (
                  <tr key={d.id} className="border-b border-gray-100" data-testid={`open-discrepancy-${d.id}`}>
                    <td className={`${TD} font-mono font-semibold whitespace-nowrap`}>
                      <Link href={`/${org}/transfers/${d.transfer_order_id}`} className="no-underline text-eth-forest">
                        {shortRef(d.transfer_order_id)} →
                      </Link>
                    </td>
                    <td className={TD}>{name}</td>
                    <td className={`${TD} font-mono`}>{d.lot_number ?? "—"}</td>
                    <td className={`${TD} font-semibold text-red-700`}>{formatQty(d.missing_quantity)}</td>
                    <td className={TD}>{codeLabel("transfers.discrepancies.reason", d.reason)}</td>
                    <td className={`${TD} whitespace-nowrap`}>{new Date(d.created_at).toLocaleDateString()}</td>
                    {canResolve && (
                      <td className={TD}>
                        <button
                          type="button"
                          data-testid={`open-discrepancy-resolve-${d.id}`}
                          onClick={() => setResolving({
                            transferId: d.transfer_order_id,
                            discrepancyId: d.id,
                            productId: d.product_id,
                            productName: name,
                            fromWarehouseId: d.from_warehouse_id,
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
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {resolving && (
        <ResolveDiscrepancyDialog
          target={resolving}
          onClose={() => setResolving(null)}
          onResolved={() => { setResolving(null); onResolved(); }}
        />
      )}
    </div>
  );
}
