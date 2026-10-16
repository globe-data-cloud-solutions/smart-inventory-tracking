"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";

/**
 * The tenant whose data the current page shows.
 * SA's JWT carries no tenant_id, so on another tenant's page (org !== SA_ORG_SLUG)
 * the UUID is resolved from the org slug; `ready` stays false until it is known.
 * Every other role is scoped by its own session. `isSA` tells the caller whether
 * the id has to be sent as ?tenant_id= (the backend ignores it for non-SA).
 */
export function useViewedTenantId(org: string): {
  tenantId: string | undefined;
  ready: boolean;
  isSA: boolean;
} {
  const session = getSession();
  const isSA = session?.role === "SA";
  const isSAViewing = isSA && org !== SA_ORG_SLUG;

  const { data: tenantMeta } = useQuery<{ id: string; name: string }>({
    queryKey: ["tenant-meta", org],
    queryFn: () => api.get<{ id: string; name: string }>(`/api/v1/tenants/${org}`),
    enabled: isSAViewing && !!org,
    staleTime: 60_000,
    retry: false,
  });

  if (isSAViewing) {
    return { tenantId: tenantMeta?.id, ready: !!tenantMeta?.id, isSA };
  }
  return { tenantId: session?.tenantId, ready: true, isSA };
}
