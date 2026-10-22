"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { formatNumber } from "@/lib/format";
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

interface ValuationRow {
  product_id: string;
  sku: string;
  name: string;
  warehouse_id: string;
  warehouse_name: string | null;
  on_hand: number | string;
  unit_cost: number | string;
  total_value: number | string;
}

const COLUMNS: ReportColumn<ValuationRow>[] = [
  { labelKey: "report.col_sku", render: (r) => r.sku },
  { labelKey: "report.col_name", render: (r) => r.name },
  { labelKey: "report.col_warehouse", render: (r) => dash(r.warehouse_name) },
  { labelKey: "report.col_on_hand", align: "right", render: (r) => formatNumber(r.on_hand) },
  { labelKey: "report.col_unit_cost", align: "right", render: (r) => formatNumber(r.unit_cost) },
  { labelKey: "report.col_total_value", align: "right", render: (r) => formatNumber(r.total_value) },
];

export default function ValuationReportPage() {
  const { org } = useParams() as { org: string };
  const { tenantId, ready } = useReportTenant(org);
  const [filter, setFilter] = useState<LevelNodeFilter>({ level: null, nodeId: null });

  const options = useQuery({
    queryKey: ["report-filter-options", org, tenantId],
    queryFn: () => fetchFilterOptions(tenantId),
    enabled: REPORTS_LIVE && org !== SA_ORG_SLUG && ready,
    staleTime: 60_000,
  });

  const path = reportPath("/api/v1/inventory/reports/inventory-valuation", filter, {}, tenantId);
  const rows = useQuery<ValuationRow[]>({
    queryKey: ["report-valuation", org, tenantId, path],
    queryFn: () => api.get<ValuationRow[]>(path),
    enabled: REPORTS_LIVE && org !== SA_ORG_SLUG && ready,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const data = rows.data ?? [];
  const total = data.reduce((sum, r) => sum + Number(r.total_value), 0);

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-1">{t("report.inventory_valuation")}</h2>
      <p className="text-sm text-gray-500 mb-6">{t("report.inv_valuation_desc")}</p>
      <ReportFilterBar options={options.data} filter={filter} onChange={setFilter} />
      <ReportTable
        columns={COLUMNS}
        rows={data}
        isLoading={rows.isLoading}
        isError={rows.isError}
        exportName="valuation"
        total={data.length > 0 ? formatNumber(total) : undefined}
      />
    </div>
  );
}
