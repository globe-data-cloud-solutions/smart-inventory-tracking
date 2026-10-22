// Report data helpers (2026-10-22). Reports are scoped by the server to the
// caller's level; these helpers only build the optional filter query.

import { api } from "@/lib/api";

export const REPORTS_LIVE = !!process.env.NEXT_PUBLIC_API_URL;

export interface ReportLevel {
  level_number: number;
  level_name: string;
}

export interface ReportNode {
  id: string;
  name: string;
  code: string;
  hierarchy_level: number;
  parent_node_id: string | null;
}

export interface ReportFilterOptions {
  levels: ReportLevel[];
  nodes: ReportNode[];
}

export interface LevelNodeFilter {
  level: number | null;
  nodeId: string | null;
}

/** Builds `base?level=..&node_id=..&...`. Level and node go together: the
 *  server rejects a node without its level, so both are sent or neither. */
export function reportPath(
  base: string,
  filter: LevelNodeFilter,
  extra: Record<string, string | null | undefined> = {},
): string {
  const params = new URLSearchParams();
  if (filter.nodeId && filter.level != null) {
    params.set("level", String(filter.level));
    params.set("node_id", filter.nodeId);
  }
  for (const [key, value] of Object.entries(extra)) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export function fetchFilterOptions(): Promise<ReportFilterOptions> {
  return api.get<ReportFilterOptions>("/api/v1/inventory/reports/filter-options");
}

/** A null or empty value shows as a dash, never as a raw id. */
export function dash(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}
