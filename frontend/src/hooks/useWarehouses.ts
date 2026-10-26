"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getSession } from "@/lib/demo-auth";
import type { DemoWarehouse } from "@/lib/demo-data";

interface OrgNodeRow {
  id: string;
  name: string;
  address: string | null;
  hierarchy_level: number;
  level_name: string | null;
  is_stock_holding: boolean;
  parent_node_id: string | null;
  children: OrgNodeRow[];
}

function flattenNodes(nodes: OrgNodeRow[]): OrgNodeRow[] {
  const out: OrgNodeRow[] = [];
  function visit(list: OrgNodeRow[]) {
    for (const n of list) { out.push(n); visit(n.children); }
  }
  visit(nodes);
  return out;
}

export function useWarehouses(tenantId?: string): { warehouses: DemoWarehouse[]; isLoading: boolean } {
  const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;
  const session = getSession();
  const tid = tenantId ?? session?.tenantId;

  const { data: orgNodes = [], isLoading } = useQuery<OrgNodeRow[]>({
    queryKey: ["org-nodes", tid],
    queryFn:  () => api.get<OrgNodeRow[]>(`/api/v1/tenants/${tid}/nodes`),
    enabled:  isGatewayMode && !!tid,
    staleTime: 60_000,
  });

  if (!isGatewayMode) {
    return { warehouses: [], isLoading: false };
  }

  const all = flattenNodes(orgNodes);
  const byId = new Map(all.map((n) => [String(n.id), n]));
  // Approval-only nodes (is_stock_holding = false) are left out of the list,
  // so a node's parent link points at its nearest stock-holding ancestor.
  // Without this, ancestor/descendant scopes (PULL sources, PUSH targets)
  // stop at an approval-only node in between.
  function stockParent(n: OrgNodeRow): string | null {
    const seen = new Set<string>();
    let pid = n.parent_node_id ? String(n.parent_node_id) : null;
    while (pid && !seen.has(pid)) {
      seen.add(pid);
      const p = byId.get(pid);
      if (!p) return null;
      if (p.is_stock_holding) return pid;
      pid = p.parent_node_id ? String(p.parent_node_id) : null;
    }
    return null;
  }

  const warehouses: DemoWarehouse[] = all
    .filter((n) => n.is_stock_holding)
    .map((n) => ({
      id:           String(n.id),
      name:         n.name,
      type:         "WH" as DemoWarehouse["type"],
      parentId:     stockParent(n),
      location:     n.address ?? undefined,
      level_number: n.hierarchy_level,
    }));

  return { warehouses, isLoading };
}
