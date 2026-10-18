"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { usePermission } from "@/lib/permissions";
import { formatQty } from "@/lib/utils";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  TransferDiscrepancies,
  TransferLotSplit,
  hasLotSplit,
  transferDetailKey,
  type TransferDiscrepancyApi,
  type TransferLineApi,
  type TransferLotAllocationApi,
} from "@/components/features/transfers/TransferLotDetails";
import { openDiscrepanciesKey } from "@/components/features/transfers/transferQueryKeys";
import { transferStatusLabel, transferTypeLabel, useTransferTypes } from "@/components/features/transfers/transferLabels";

/* ── GET /api/v1/inventory/transfers/{id} (TransferOrderResponse) ────────── */
interface TransferOrderResponse {
  transfer_id: string;
  transfer_type: string;
  status: string;
  reference_number: string | null;
  from_warehouse_id: string;
  from_warehouse_name: string | null;
  to_warehouse_id: string;
  to_warehouse_name: string | null;
  created_at: string;
  is_self_approved?: boolean;
  current_approval_step?: unknown;
  resolved_approval_steps?: unknown;
  lines?: TransferLineApi[];
  lot_allocations?: TransferLotAllocationApi[];
  discrepancies?: TransferDiscrepancyApi[];
}

type ApiFailure = Error & { status?: number; code?: string };

const STATUS_CLASS: Record<string, string> = {
  DRAFT:                  "bg-gray-100 text-gray-500",
  PENDING_REVIEW:         "bg-violet-100 text-violet-800",
  PENDING_APPROVAL:       "bg-blue-100 text-blue-800",
  PENDING_SOURCE_CONFIRM: "bg-amber-100 text-amber-800",
  PENDING_DEST_CONFIRM:   "bg-amber-100 text-amber-800",
  APPROVED:               "bg-emerald-100 text-emerald-900",
  ADVISED:                "bg-teal-50 text-emerald-600",
  ISSUED:                 "bg-emerald-100 text-emerald-900",
  IN_TRANSIT:             "bg-amber-100 text-amber-800",
  PARTIALLY_RECEIVED:     "bg-yellow-50 text-yellow-900",
  RECEIVED:               "bg-green-100 text-green-800",
  COMPLETED:              "bg-gray-100 text-gray-700",
  REJECTED:               "bg-red-100 text-red-900",
  CANCELLED:              "bg-gray-100 text-gray-400",
};

const TYPE_CLASS: Record<string, string> = {
  PULL:   "bg-blue-100 text-blue-800",
  PUSH:   "bg-amber-100 text-amber-800",
  SISTER: "bg-violet-100 text-violet-800",
};

const TH = "px-2.5 py-1.5 text-left text-[10px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap";
const TD = "px-2.5 py-1.5 text-xs text-gray-700";

function BackLink({ org }: { org: string }) {
  return (
    <Link
      href={`/${org}/transfers`}
      className="inline-block text-sm text-gray-500 no-underline mb-4 hover:text-gray-700 transition-colors"
    >
      {t("transfers.back")}
    </Link>
  );
}

/* ── Main page ───────────────────────────────────────────────────────────── */
export default function TransferDetailPage() {
  const { org, id } = useParams() as { org: string; id: string };
  const user = getSession();
  const qc = useQueryClient();
  const [toast, setToast] = useState("");

  const { data: transfer, isLoading, error } = useQuery<TransferOrderResponse, ApiFailure>({
    queryKey: transferDetailKey(id),
    queryFn:  () => api.get<TransferOrderResponse>(`/api/v1/inventory/transfers/${id}`),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 15000,
    // 404 / 403 are answers, not blips — show them straight away.
    retry: (count, err) => !(err.status === 404 || err.status === 403) && count < 2,
  });

  const canResolve = usePermission("transfer:resolve_discrepancy", user?.role ?? "");
  // The tenant's own name for the transfer type (same query as the list page).
  const transferTypes = useTransferTypes(user?.tenantId ?? "");

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("transfers.select_tenant")}</p>;
  if (!user) return <p className="p-8 text-gray-500">{t("transfers.not_found")}</p>;

  if (isLoading) {
    return <div className="p-12 text-center text-gray-400">{t("transfers.loading")}</div>;
  }

  if (error || !transfer) {
    let message = t("transfers.view.load_failed");
    if (error?.status === 404) message = t("transfers.view.not_found");
    else if (error?.status === 403 && error.code === "TRANSFER_OUT_OF_SCOPE") message = t("transfers.view.out_of_scope");
    return (
      <div className="p-8">
        <BackLink org={org} />
        <p className="text-red-600 text-sm">{message}</p>
      </div>
    );
  }

  function onResolved() {
    void qc.invalidateQueries({ queryKey: ["transfers", org] });
    void qc.invalidateQueries({ queryKey: openDiscrepanciesKey() });
    setToast(t("transfers.discrepancies.toast_resolved"));
    setTimeout(() => setToast(""), 5000);
  }

  const lines = transfer.lines ?? [];
  const typeLabel = transferTypeLabel(transfer.transfer_type, transferTypes);
  const statusLabel = transferStatusLabel(transfer.status);
  const createdAt = formatDateTime(transfer.created_at);
  const title = transfer.reference_number
    ?? t("transfers.view.untitled")
         .replace("{type}", typeLabel)
         .replace("{date}", formatDate(transfer.created_at));

  const detailFields = [
    { label: t("transfers.detail.from"),    value: transfer.from_warehouse_name ?? "—" },
    { label: t("transfers.detail.to"),      value: transfer.to_warehouse_name ?? "—" },
    { label: t("transfers.detail.created"), value: createdAt },
  ];

  return (
    <div className="p-8">
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0f2d1f] text-[#FCDD09] font-bold text-sm px-5 py-2.5 rounded-md shadow-lg max-w-sm">
          {toast}
        </div>
      )}

      <BackLink org={org} />

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden max-w-[800px]">
        <div className="h-1 bg-[#1B4332]" />

        {/* Header */}
        <div className="px-6 py-5 bg-[#0f2d1f] flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="font-mono text-lg font-bold text-[#FCDD09] m-0">{title}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${TYPE_CLASS[transfer.transfer_type] ?? "bg-gray-100 text-gray-600"}`}>
                {typeLabel}
              </span>
              {transfer.is_self_approved && (
                <span
                  title={t("transfers.self_approved_hint")}
                  className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-teal-100 text-teal-800 whitespace-nowrap"
                >
                  {t("transfers.self_approved")}
                </span>
              )}
            </div>
          </div>
          <span className={`text-sm font-bold px-3.5 py-1.5 rounded-full ${STATUS_CLASS[transfer.status] ?? "bg-gray-100 text-gray-500"}`}>
            {statusLabel}
          </span>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
            {detailFields.map(({ label, value }) => (
              <div key={label} className="px-3.5 py-2.5 bg-gray-50 rounded-md border border-gray-200">
                <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 m-0">{label}</p>
                <p className="text-sm font-semibold text-gray-900 mt-1 mb-0">{value}</p>
              </div>
            ))}
          </div>

          {/* Lines */}
          <div className="mb-6">
            <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-1.5">
              {t("transfers.view.lines_title")}
            </p>
            {lines.length === 0 ? (
              <p className="text-xs text-gray-400 italic">{t("transfers.view.no_lines")}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="border-collapse bg-white border border-gray-200 rounded">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className={TH}>{t("transfers.view.col_product")}</th>
                      <th className={TH}>{t("transfers.view.col_sku")}</th>
                      <th className={TH}>{t("transfers.view.col_quantity")}</th>
                      <th className={TH}>{t("transfers.view.col_unit")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => (
                      <tr key={l.line_id} className="border-b border-gray-100">
                        <td className={TD}>{l.product_name}</td>
                        <td className={`${TD} font-mono`}>{l.sku}</td>
                        <td className={`${TD} font-semibold text-gray-900`}>{formatQty(l.quantity)}</td>
                        <td className={TD}>{l.uom}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Lot split (from APPROVED onward) */}
          {hasLotSplit(transfer.status) && (
            <div className="mb-6">
              <TransferLotSplit lines={lines} allocations={transfer.lot_allocations ?? []} />
            </div>
          )}

          {/* Receipt discrepancies, with Resolve for the roles that may */}
          {(transfer.discrepancies?.length ?? 0) > 0 && (
            <div className="mb-2">
              <TransferDiscrepancies
                discrepancies={transfer.discrepancies ?? []}
                transferId={id}
                fromWarehouseId={transfer.from_warehouse_id}
                lines={lines}
                canResolve={canResolve}
                onResolved={onResolved}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
