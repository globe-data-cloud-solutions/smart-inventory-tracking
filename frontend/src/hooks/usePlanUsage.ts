"use client";

import { useQuery } from "@tanstack/react-query";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { getSession } from "@/lib/demo-auth";

export interface PlanUsageResource {
  used: number;
  limit: number | null;
}

export interface PlanUsage {
  plan_tier: string | null;
  skus: PlanUsageResource;
  users: PlanUsageResource;
  warehouses: PlanUsageResource;
}

// Roles granted plan:view_usage in scripts/seed_permissions.py — kept in sync
// with that grant so this hook never fires a request guaranteed to 403.
const ROLES_WITH_PLAN_VIEW_USAGE = new Set(["TA", "NM"]);

/**
 * GET /api/v1/tenants/me/plan-usage — only for roles holding plan:view_usage
 * (TA, NM). Backs useWriteGuard's atLimit() check.
 */
export function usePlanUsage(): { planUsage: PlanUsage | null; isLoading: boolean } {
  const session = getSession();
  const enabled =
    IS_GATEWAY_MODE && !!session?.tenantId && ROLES_WITH_PLAN_VIEW_USAGE.has(session.role);

  const { data, isLoading } = useQuery<PlanUsage>({
    queryKey: ["plan-usage", session?.tenantId],
    queryFn: () => api.get<PlanUsage>("/api/v1/tenants/me/plan-usage"),
    enabled,
    staleTime: 60_000,
  });

  return { planUsage: data ?? null, isLoading };
}
