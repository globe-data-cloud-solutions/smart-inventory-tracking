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

  const warehouses: DemoWarehouse[] = flattenNodes(orgNodes)
    .filter((n) => n.is_stock_holding)
    .map((n) => ({
      id:       String(n.id),
      name:     n.name,
      type:     "WH" as DemoWarehouse["type"],
      parentId: n.parent_node_id ? String(n.parent_node_id) : null,
      location: n.address ?? undefined,
    }));

  return { warehouses, isLoading };
}
