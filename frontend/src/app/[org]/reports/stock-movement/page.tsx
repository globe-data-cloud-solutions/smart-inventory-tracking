"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { formatDate, formatNumber } from "@/lib/format";
import {
  REPORTS_LIVE,
  dash,
  fetchFilterOptions,
  reportPath,
  useReportTenant,
  type LevelNodeFilter,
} from "@/lib/reports";
import ReportFilterBar from "@/components/reports/ReportFilterBar";
import ReportTable, { type ReportColumn } from "@/components/reports/ReportTable";

interface MovementRow {
  transaction_id: string;
  transaction_date: string;
  type: string;
  product_id: string;
  sku: string;
  name: string;
  warehouse_id: string;
  warehouse_name: string | null;
  quantity: number | string;
  unit_cost: number | string | null;
  lot_number: string | null;
}

// Explicit literal keys (not a template string) so check_i18n.sh can see each one.
const TX_TYPE_KEYS: Record<string, string> = {
  RECEIVE: "report.tx_type_receive",
  TRANSFER_OUT: "report.tx_type_transfer_out",
  TRANSFER_IN: "report.tx_type_transfer_in",
  ISSUE: "report.tx_type_issue",
  ADJUSTMENT: "report.tx_type_adjustment",
  RESERVE: "report.tx_type_reserve",
  RELEASE: "report.tx_type_release",
  RETURN: "report.tx_type_return",
  COUNT_VARIANCE: "report.tx_type_count_variance",
  LOT_OPENING: "report.tx_type_lot_opening",
  TRANSIT_OUT: "report.tx_type_transit_out",
  TRANSIT_IN: "report.tx_type_transit_in",
  TRANSIT_CLEAR: "report.tx_type_transit_clear",
  TRANSFER_REVERSAL: "report.tx_type_transfer_reversal",
};

/** Readable label for a transaction type code; an unknown code falls back to the raw code. */
function txTypeLabel(code: string): string {
  const key = TX_TYPE_KEYS[code];
  return key ? t(key) : code;
}

const COLUMNS: ReportColumn<MovementRow>[] = [
  { labelKey: "report.col_transaction_date", render: (r) => formatDate(r.transaction_date) },
  { labelKey: "report.col_type", render: (r) => txTypeLabel(r.type) },
  { labelKey: "report.col_sku", render: (r) => r.sku },
  { labelKey: "report.col_name", render: (r) => r.name },
  { labelKey: "report.col_warehouse", render: (r) => dash(r.warehouse_name) },
  { labelKey: "report.col_lot", render: (r) => dash(r.lot_number) },
  { labelKey: "report.col_quantity", align: "right", render: (r) => formatNumber(r.quantity) },
];

export default function StockMovementReportPage() {
  const { org } = useParams() as { org: string };
  const { tenantId, ready } = useReportTenant(org);
  const [filter, setFilter] = useState<LevelNodeFilter>({ level: null, nodeId: null });
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const options = useQuery({
    queryKey: ["report-filter-options", org, tenantId],
    queryFn: () => fetchFilterOptions(tenantId),
    enabled: REPORTS_LIVE && org !== SA_ORG_SLUG && ready,
    staleTime: 60_000,
  });

  const path = reportPath(
    "/api/v1/inventory/reports/stock-movement",
    filter,
    { date_from: dateFrom || null, date_to: dateTo || null },
    tenantId,
  );
  const rows = useQuery<MovementRow[]>({
    queryKey: ["report-movement", org, tenantId, path],
    queryFn: () => api.get<MovementRow[]>(path),
    enabled: REPORTS_LIVE && org !== SA_ORG_SLUG && ready,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-1">{t("report.stock_movement")}</h2>
      <p className="text-sm text-gray-500 mb-6">{t("report.stock_movement_desc")}</p>
      <ReportFilterBar options={options.data} filter={filter} onChange={setFilter}>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.from_date")}
          <input
            type="date"
            className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.to_date")}
          <input
            type="date"
            className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
      </ReportFilterBar>
      <ReportTable
        columns={COLUMNS}
        rows={rows.data ?? []}
        isLoading={rows.isLoading}
        isError={rows.isError}
        exportName="stock-movement"
      />
    </div>
  );
}
