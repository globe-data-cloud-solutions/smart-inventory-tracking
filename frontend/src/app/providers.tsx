"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { loadLocale, getCurrentLocale } from "@/lib/i18n";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));

  useEffect(() => {
    // Always load the locale from the API so in-app additions stay in sync.
    // English is pre-loaded from the static import in i18n.ts so the first
    // render never shows raw keys, and this call refreshes it if keys changed.
    loadLocale(getCurrentLocale()).catch(() => {});
  }, []);

  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
