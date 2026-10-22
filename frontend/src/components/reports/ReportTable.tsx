"use client";

import type { ReactNode } from "react";
import { t } from "@/lib/i18n";
import { downloadCsv, exportFileName, toCsv } from "@/lib/reportExport";

export interface ReportColumn<Row> {
  labelKey: string;
  align?: "left" | "right";
  render: (row: Row) => ReactNode;
}

interface Props<Row> {
  columns: ReportColumn<Row>[];
  rows: Row[];
  isLoading: boolean;
  isError: boolean;
  /** Optional footer total, rendered in the last column. */
  total?: ReactNode;
  /** Base name for the CSV download. Omit to hide the export buttons. */
  exportName?: string;
}

/** The text a cell shows, for CSV. Cells render plain strings or numbers. */
function cellText<Row>(column: ReportColumn<Row>, row: Row): string | number {
  const value = column.render(row);
  return typeof value === "string" || typeof value === "number" ? value : "";
}

export default function ReportTable<Row>({
  columns,
  rows,
  isLoading,
  isError,
  total,
  exportName,
}: Props<Row>) {
  if (isError) {
    return <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-4">{t("report.error_load")}</p>;
  }
  if (isLoading) {
    return <p className="text-sm text-gray-500">{t("common.loading")}</p>;
  }
  if (rows.length === 0) {
    return <p className="text-sm text-gray-500">{t("report.empty")}</p>;
  }

  const exportCsv = () => {
    const csv = toCsv(
      columns.map((c) => t(c.labelKey)),
      rows.map((row) => columns.map((c) => cellText(c, row))),
    );
    downloadCsv(exportFileName(exportName ?? "report"), csv);
  };

  return (
    <div>
      {exportName && (
        <div className="flex justify-end gap-2 mb-2 print:hidden">
          <button
            type="button"
            onClick={exportCsv}
            className="text-sm border border-gray-300 rounded px-3 py-1.5 bg-white hover:border-eth-forest"
          >
            {t("report.export_csv")}
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="text-sm border border-gray-300 rounded px-3 py-1.5 bg-white hover:border-eth-forest"
          >
            {t("report.print_pdf")}
          </button>
        </div>
      )}
    <div className="overflow-x-auto bg-white border border-gray-200 rounded">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            {columns.map((c) => (
              <th
                key={c.labelKey}
                className={`px-3 py-2 font-semibold ${c.align === "right" ? "text-right" : "text-left"}`}
              >
                {t(c.labelKey)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-gray-100">
              {columns.map((c) => (
                <td
                  key={c.labelKey}
                  className={`px-3 py-2 ${c.align === "right" ? "text-right tabular-nums" : "text-left"}`}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {total !== undefined && (
          <tfoot className="border-t-2 border-gray-300 font-semibold">
            <tr>
              <td className="px-3 py-2 text-left" colSpan={columns.length - 1}>
                {t("report.total")}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{total}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
    </div>
  );
}
