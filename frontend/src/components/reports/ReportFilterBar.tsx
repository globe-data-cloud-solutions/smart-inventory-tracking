"use client";

import type { ReactNode } from "react";
import { t } from "@/lib/i18n";
import type { ReportFilterOptions, LevelNodeFilter } from "@/lib/reports";

interface Props {
  options: ReportFilterOptions | undefined;
  filter: LevelNodeFilter;
  onChange: (next: LevelNodeFilter) => void;
  children?: ReactNode;
}

const selectClass =
  "border border-gray-300 rounded px-2 py-1.5 text-sm bg-white focus:outline-none focus:border-eth-forest";

export default function ReportFilterBar({ options, filter, onChange, children }: Props) {
  const levels = options?.levels ?? [];
  const nodesAtLevel =
    filter.level == null
      ? []
      : (options?.nodes ?? []).filter((n) => n.hierarchy_level === filter.level);

  return (
    <div className="flex flex-wrap items-end gap-3 mb-4">
      <label className="flex flex-col text-xs text-gray-600 gap-1">
        {t("report.filter_level")}
        <select
          className={selectClass}
          value={filter.level ?? ""}
          onChange={(e) => {
            const level = e.target.value === "" ? null : Number(e.target.value);
            onChange({ level, nodeId: null });
          }}
        >
          <option value="">{t("report.all_levels")}</option>
          {levels.map((lv) => (
            <option key={lv.level_number} value={lv.level_number}>
              {lv.level_name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col text-xs text-gray-600 gap-1">
        {t("report.filter_node")}
        <select
          className={selectClass}
          disabled={filter.level == null}
          value={filter.nodeId ?? ""}
          onChange={(e) => onChange({ level: filter.level, nodeId: e.target.value || null })}
        >
          <option value="">{t("report.all_nodes")}</option>
          {nodesAtLevel.map((n) => (
            <option key={n.id} value={n.id}>
              {n.name}
              {n.code ? ` (${n.code})` : ""}
            </option>
          ))}
        </select>
      </label>

      {children}
    </div>
  );
}
