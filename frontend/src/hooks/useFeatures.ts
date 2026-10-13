"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface FeatureFlags {
  lotTracking: boolean;
}

export function useFeatures(): FeatureFlags {
  const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;

  const { data } = useQuery<{ lot_tracking: boolean }>({
    queryKey: ["features"],
    queryFn: async () => {
      const r = await api.get<unknown>("/api/v1/inventory/features");
      return ((r as { data?: unknown }).data ?? r) as { lot_tracking: boolean };
    },
    enabled: isGatewayMode,
    staleTime: 10 * 60_000,
  });

  if (!isGatewayMode) return { lotTracking: false };
  return { lotTracking: data?.lot_tracking ?? false };
}
