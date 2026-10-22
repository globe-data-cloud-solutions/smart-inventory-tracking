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

interface ProductOption {
  id: string;
  sku: string;
  name: string;
}

interface LotHeader {
  lot_number: string;
  product_id: string;
  sku: string;
  name: string;
  expiry_date: string | null;
  first_received_at: string;
}

interface LotBalanceRow {
  warehouse_id: string;
  warehouse_name: string | null;
  quantity: number | string;
}

interface LotHistoryRow {
  transaction_id: string;
  transaction_date: string;
  type: string;
  warehouse_id: string;
  warehouse_name: string | null;
  quantity: number | string;
  created_at: string;
}

interface LotTrace {
  lot: LotHeader;
  balances: LotBalanceRow[];
  history: LotHistoryRow[];
}

const BALANCE_COLUMNS: ReportColumn<LotBalanceRow>[] = [
  { labelKey: "report.col_warehouse", render: (r) => dash(r.warehouse_name) },
  { labelKey: "report.col_balance", align: "right", render: (r) => formatNumber(r.quantity) },
];

// Transaction types are shown as their readable labels (same map as Stock Movement).
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

function txTypeLabel(code: string): string {
  const key = Object.prototype.hasOwnProperty.call(TX_TYPE_KEYS, code) ? TX_TYPE_KEYS[code] : undefined;
  return key ? t(key) : code;
}

const HISTORY_COLUMNS: ReportColumn<LotHistoryRow>[] = [
  { labelKey: "report.col_transaction_date", render: (r) => formatDate(r.transaction_date) },
  { labelKey: "report.col_type", render: (r) => txTypeLabel(r.type) },
  { labelKey: "report.col_warehouse", render: (r) => dash(r.warehouse_name) },
  { labelKey: "report.col_quantity", align: "right", render: (r) => formatNumber(r.quantity) },
];

export default function LotTraceReportPage() {
  const { org } = useParams() as { org: string };
  const { tenantId, ready } = useReportTenant(org);
  const enabled = REPORTS_LIVE && org !== SA_ORG_SLUG && ready;

  const [filter, setFilter] = useState<LevelNodeFilter>({ level: null, nodeId: null });
  const [productId, setProductId] = useState("");
  const [lotNumber, setLotNumber] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const options = useQuery({
    queryKey: ["report-filter-options", org, tenantId],
    queryFn: () => fetchFilterOptions(tenantId),
    enabled,
    staleTime: 60_000,
  });

  const products = useQuery<ProductOption[]>({
    queryKey: ["report-products", org, tenantId],
    queryFn: () => api.get<ProductOption[]>("/api/v1/products/"),
    enabled,
    staleTime: 60_000,
  });

  const lot = lotNumber.trim();
  const ready_to_query = enabled && !!productId && lot.length > 0;
  const path = reportPath(
    "/api/v1/inventory/reports/lot-trace",
    filter,
    {
      product_id: productId || null,
      lot_number: lot || null,
      date_from: dateFrom || null,
      date_to: dateTo || null,
    },
    tenantId,
  );
  const trace = useQuery<LotTrace, Error & { code?: string }>({
    queryKey: ["report-lot-trace", org, tenantId, path],
    queryFn: () => api.get<LotTrace>(path),
    enabled: ready_to_query,
    retry: false,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const selectClass = "border border-gray-300 rounded px-2 py-1.5 text-sm bg-white";
  const data = trace.data;

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-1">{t("report.lot_trace")}</h2>
      <p className="text-sm text-gray-500 mb-6">{t("report.lot_trace_desc")}</p>

      <ReportFilterBar options={options.data} filter={filter} onChange={setFilter}>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.filter_product")}
          <select className={selectClass} value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">{t("report.choose_product")}</option>
            {(products.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} · {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.filter_lot_number")}
          <input
            className={selectClass}
            value={lotNumber}
            maxLength={100}
            onChange={(e) => setLotNumber(e.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.from_date")}
          <input type="date" className={selectClass} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.to_date")}
          <input type="date" className={selectClass} value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
      </ReportFilterBar>

      {!ready_to_query && <p className="text-sm text-gray-500">{t("report.lot_prompt")}</p>}

      {ready_to_query && trace.isError && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-4 mb-4">
          {trace.error?.code === "LOT_NOT_FOUND" ? t("errors.LOT_NOT_FOUND") : t("report.error_load")}
        </p>
      )}

      {data && (
        <>
          <div className="bg-white border border-gray-200 rounded p-4 mb-6 text-sm grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <p className="text-xs text-gray-500 m-0">{t("report.col_name")}</p>
              <p className="m-0 font-semibold">{data.lot.sku} · {data.lot.name}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 m-0">{t("report.filter_lot_number")}</p>
              <p className="m-0 font-semibold">{data.lot.lot_number}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 m-0">{t("report.lot_expiry")}</p>
              <p className="m-0 font-semibold">{data.lot.expiry_date ? formatDate(data.lot.expiry_date) : "—"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 m-0">{t("report.lot_first_received")}</p>
              <p className="m-0 font-semibold">{formatDate(data.lot.first_received_at)}</p>
            </div>
          </div>

          <h3 className="text-sm font-semibold text-gray-700 mb-2">{t("report.lot_balances")}</h3>
          <div className="mb-6">
            <ReportTable columns={BALANCE_COLUMNS} rows={data.balances} isLoading={false} isError={false} />
          </div>

          <h3 className="text-sm font-semibold text-gray-700 mb-2">{t("report.lot_history")}</h3>
          <ReportTable columns={HISTORY_COLUMNS} rows={data.history} isLoading={false} isError={false} />
        </>
      )}
    </div>
  );
}
