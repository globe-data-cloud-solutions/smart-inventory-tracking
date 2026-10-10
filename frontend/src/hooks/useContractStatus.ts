"use client";

import { useQuery } from "@tanstack/react-query";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { getSession } from "@/lib/demo-auth";

export type ContractStage = "ACTIVE" | "EXPIRING" | "GRACE" | "READ_ONLY";

export interface ContractStatusOpenRequest {
  id: string;
  created_at: string;
}

export interface ContractStatus {
  stage: ContractStage;
  contract_end: string | null;
  days_left: number | null;
  grace_ends: string | null;
  read_only_since: string | null;
  open_request: ContractStatusOpenRequest | null;
}

/**
 * GET /api/v1/tenants/me/contract-status — tenant users only, never SA.
 * Backs the TA sidebar notice and the grace/read-only top banners in
 * app/[org]/layout.tsx, and the "at limit" reason in useWriteGuard.
 */
export function useContractStatus(): { contractStatus: ContractStatus | null; isLoading: boolean } {
  const session = getSession();
  const enabled = IS_GATEWAY_MODE && !!session?.tenantId && session.role !== "SA";

  const { data, isLoading } = useQuery<ContractStatus>({
    queryKey: ["contract-status", session?.tenantId],
    queryFn: () => api.get<ContractStatus>("/api/v1/tenants/me/contract-status"),
    enabled,
    staleTime: 5 * 60_000,
  });

  return { contractStatus: data ?? null, isLoading };
}
