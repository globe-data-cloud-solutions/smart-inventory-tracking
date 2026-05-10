"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { loadLocale, getCurrentLocale } from "@/lib/i18n";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));

  useEffect(() => {
    // English is pre-loaded from the static import in i18n.ts.
    // This call only matters when the user has selected am/or.
    const locale = getCurrentLocale();
    if (locale !== "en") {
      loadLocale(locale).catch(() => {});
    }
  }, []);

  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
