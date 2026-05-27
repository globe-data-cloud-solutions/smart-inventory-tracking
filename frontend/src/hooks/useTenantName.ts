"use client";

import { useQuery } from "@tanstack/react-query";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { api } from "@/lib/api";

/**
 * Resolves a human-readable tenant name from an org slug.
 * Checks DEMO_TENANTS first (no API call), then falls back to the API.
 * Returns null while loading; never returns a raw UUID or slug.
 */
export function useTenantName(org: string): string | null {
  const demoName = DEMO_TENANTS.find((t) => t.slug === org || t.id === org)?.name ?? null;

  const { data } = useQuery<{ id: string; name: string }>({
    queryKey: ["tenant-meta", org],
    queryFn: () => api.get<{ id: string; name: string }>(`/api/v1/tenants/${org}`),
    enabled: !demoName && !!org,
    staleTime: 60_000,
    retry: false,
  });

  return demoName ?? data?.name ?? null;
}
