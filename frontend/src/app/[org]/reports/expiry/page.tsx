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

interface ExpiryRow {
  product_id: string;
  sku: string;
  name: string;
  warehouse_id: string;
  warehouse_name: string | null;
  lot_number: string | null;
  expiry_date: string;
  quantity: number | string;
  days_to_expiry: number;
}

const WINDOWS = [
  { days: 30, labelKey: "report.window_30" },
  { days: 60, labelKey: "report.window_60" },
  { days: 90, labelKey: "report.window_90" },
];

const COLUMNS: ReportColumn<ExpiryRow>[] = [
  { labelKey: "report.col_sku", render: (r) => r.sku },
  { labelKey: "report.col_name", render: (r) => r.name },
  { labelKey: "report.col_warehouse", render: (r) => dash(r.warehouse_name) },
  { labelKey: "report.col_lot", render: (r) => dash(r.lot_number) },
  { labelKey: "report.col_expiry_date", render: (r) => formatDate(r.expiry_date) },
  { labelKey: "report.col_days_to_expiry", align: "right", render: (r) => formatNumber(r.days_to_expiry) },
  { labelKey: "report.col_quantity", align: "right", render: (r) => formatNumber(r.quantity) },
];

export default function ExpiryReportPage() {
  const { org } = useParams() as { org: string };
  const { tenantId, ready } = useReportTenant(org);
  const [filter, setFilter] = useState<LevelNodeFilter>({ level: null, nodeId: null });
  const [windowDays, setWindowDays] = useState<number>(30);

  const options = useQuery({
    queryKey: ["report-filter-options", org, tenantId],
    queryFn: () => fetchFilterOptions(tenantId),
    enabled: REPORTS_LIVE && org !== SA_ORG_SLUG && ready,
    staleTime: 60_000,
  });

  const path = reportPath(
    "/api/v1/inventory/reports/expiry-alerts",
    filter,
    { window_days: String(windowDays) },
    tenantId,
  );
  const rows = useQuery<ExpiryRow[]>({
    queryKey: ["report-expiry", org, tenantId, path],
    queryFn: () => api.get<ExpiryRow[]>(path),
    enabled: REPORTS_LIVE && org !== SA_ORG_SLUG && ready,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const data = rows.data ?? [];
  const totalQty = data.reduce((sum, r) => sum + Number(r.quantity), 0);

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-1">{t("report.expiry_alerts")}</h2>
      <p className="text-sm text-gray-500 mb-6">{t("report.expiry_alerts_desc")}</p>
      <ReportFilterBar options={options.data} filter={filter} onChange={setFilter}>
        <label className="flex flex-col text-xs text-gray-600 gap-1">
          {t("report.filter_window")}
          <select
            className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
          >
            {WINDOWS.map((w) => (
              <option key={w.days} value={w.days}>
                {t(w.labelKey)}
              </option>
            ))}
          </select>
        </label>
      </ReportFilterBar>
      <ReportTable
        columns={COLUMNS}
        rows={data}
        isLoading={rows.isLoading}
        isError={rows.isError}
        total={data.length > 0 ? formatNumber(totalQty) : undefined}
      />
    </div>
  );
}
