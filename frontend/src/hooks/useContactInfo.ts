"use client";

import { useQuery } from "@tanstack/react-query";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { ContactInfo } from "@/lib/billing-types";

/**
 * GET /api/v1/tenants/public/contact — unauthenticated, public.
 * Demo mode (no backend) has no real contact record, so the query is
 * disabled there and every caller treats a missing result as "not configured"
 * rather than inventing placeholder contact details.
 */
export function useContactInfo(): { contact: ContactInfo | null; isLoading: boolean } {
  const { data, isLoading } = useQuery<ContactInfo>({
    queryKey: ["public-contact"],
    queryFn: () => api.get<ContactInfo>("/api/v1/tenants/public/contact"),
    enabled: IS_GATEWAY_MODE,
    staleTime: 5 * 60_000,
  });

  return { contact: data ?? null, isLoading: IS_GATEWAY_MODE && isLoading };
}
