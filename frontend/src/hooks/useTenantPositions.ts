"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface TenantPosition {
  id: string;
  title: string;
  role_code: string;
  level_number: number;
  level_name: string;
  node_id: string;
  node_name: string;
  display_label: string;
  reports_to_position_id: string | null;
  reports_to_title: string | null;
}

/**
 * Tenant-wide flat list of active positions, with enough context (node + level)
 * to disambiguate same-titled positions at different facilities.
 *
 * Use this instead of hardcoded role-code lists for any dropdown that lets a
 * user pick "who" (a position) — e.g. transfer/adjustment approval routing.
 */
export function useTenantPositions(tenantId: string): {
  positions: TenantPosition[];
  isLoading: boolean;
} {
  const { data: positions = [], isLoading } = useQuery<TenantPosition[]>({
    queryKey: ["tenant-positions-flat", tenantId],
    queryFn: () => api.get<TenantPosition[]>(`/api/v1/tenants/${tenantId}/positions/flat`),
    staleTime: 30_000,
    enabled: !!tenantId,
  });

  return { positions, isLoading };
}
