"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { loadLocale, getCurrentLocale } from "@/lib/i18n";

const LOCALE_TIMEOUT_MS = 3000;

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  }));
  const [localeReady, setLocaleReady] = useState(false);

  useEffect(() => {
    // English is pre-loaded from the static import in i18n.ts.
    // For am/or, hold rendering until the pack has loaded so t() never
    // returns English for the first paint. A timer releases the gate
    // anyway (English fallback) if the fetch hangs.
    const locale = getCurrentLocale();
    if (locale === "en") {
      setLocaleReady(true);
      return;
    }
    const timer = setTimeout(() => setLocaleReady(true), LOCALE_TIMEOUT_MS);
    loadLocale(locale)
      .then(() => {
        document.documentElement.lang = locale;
      })
      .catch(() => {})
      .finally(() => setLocaleReady(true));
    return () => clearTimeout(timer);
  }, []);

  return (
    <QueryClientProvider client={qc}>
      {localeReady ? children : null}
    </QueryClientProvider>
  );
}
