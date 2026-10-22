"use client";

import { useMemo, useState } from "react";
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

interface DispatchRow {
  transfer_order_id: string;
  dispatched_on: string;
  from_warehouse_id: string;
  from_warehouse_name: string | null;
  to_warehouse_id: string;
  to_warehouse_name: string | null;
  product_id: string;
  sku: string;
  name: string;
  quantity_dispatched: number | string;
  lots_used: number;
  overrides: number;
}

interface ProductOption {
  id: string;
  sku: string;
  name: string;
}

const COLUMNS: ReportColumn<DispatchRow>[] = [
  { labelKey: "report.col_dispatched_on", render: (r) => formatDate(r.dispatched_on) },
  { labelKey: "report.col_from", render: (r) => dash(r.from_warehouse_name) },
  { labelKey: "report.col_to", render: (r) => dash(r.to_warehouse_name) },
  { labelKey: "report.col_sku", render: (r) => r.sku },
  { labelKey: "report.col_name", render: (r) => r.name },
  { labelKey: "report.col_quantity_dispatched", align: "right", render: (r) => formatNumber(r.quantity_dispatched) },
  { labelKey: "report.col_lots_used", align: "right", render: (r) => formatNumber(r.lots_used) },
  { labelKey: "report.col_overrides", align: "right", render: (r) => formatNumber(r.overrides) },
];

export default function DispatchReportPage() {
  const { org } = useParams() as { org: string };
  const { tenantId, ready } = useReportTenant(org);
  const enabled = REPORTS_LIVE && org !== SA_ORG_SLUG && ready;

  const [filter, setFilter] = useState<LevelNodeFilter>({ level: null, nodeId: null });
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [productId, setProductId] = useState("");
  const [dispatchId, setDispatchId] = useState("");

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

  const dateExtra = { date_from: dateFrom || null, date_to: dateTo || null, product_id: productId || null };

  // The dispatch dropdown lists dispatches for the other filters, so picking one
  // does not hide the rest.
  const listPath = reportPath("/api/v1/inventory/reports/dispatch-summary", filter, dateExtra, tenantId);
  const dispatchList = useQuery<DispatchRow[]>({
    queryKey: ["report-dispatch-list", org, tenantId, listPath],
    queryFn: () => api.get<DispatchRow[]>(listPath),
    enabled,
  });

  const rowsPath = reportPath(
    "/api/v1/inventory/reports/dispatch-summary",
    filter,
    { ...dateExtra, transfer_order_id: dispatchId || null },
    tenantId,
  );
  const rows = useQuery<DispatchRow[]>({
    queryKey: ["report-dispatch", org, tenantId, rowsPath],
    queryFn: () => api.get<DispatchRow[]>(rowsPath),
    enabled,
  });

  const dispatchOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of dispatchList.data ?? []) {
      if (!seen.has(r.transfer_order_id)) {
        seen.set(
          r.transfer_order_id,
          `${formatDate(r.dispatched_on)} · ${dash(r.from_warehouse_name)} → ${dash(r.to_warehouse_name)}`,
        );
      }
    }
    return Array.from(seen.entries());
  }, [dispatchList.data]);

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const selectClass = "border border-gray-300 rounded px-2 py-1.5 text-sm bg-white";

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-1">{t("report.dispatch_summary")}</h2>
      <p className="text-sm text-gray-500 mb-6">{t("report.dispatch_desc")}</p>
      <ReportFilterBar options={options.data} filter={filter} onChange={setFilter}>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.filter_product")}
          <select className={selectClass} value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">{t("report.all_products")}</option>
            {(products.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} · {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.filter_dispatch")}
          <select className={selectClass} value={dispatchId} onChange={(e) => setDispatchId(e.target.value)}>
            <option value="">{t("report.all_dispatches")}</option>
            {dispatchOptions.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
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
      <ReportTable columns={COLUMNS} rows={rows.data ?? []} isLoading={rows.isLoading} isError={rows.isError}
        exportName="dispatch-summary"
      />
    </div>
  );
}
