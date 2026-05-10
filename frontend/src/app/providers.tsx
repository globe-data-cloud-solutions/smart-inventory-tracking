"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { loadLocale, getCurrentLocale } from "@/lib/i18n";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));

  useEffect(() => {
    loadLocale(getCurrentLocale()).catch(() => {
      // Silently fall back to key-as-label if locale fetch fails.
    });
  }, []);

  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
