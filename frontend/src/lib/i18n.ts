// English fallback — kept in sync with smart-platform/locales/en.json.
// Imported from the local copy so webpack stays within the frontend project root.
import enFallback from "./locales/en.json";
import { resolveLocale } from "./locales-config";

type Locale = "en" | "am" | "or";

// Pre-populated with English so t() works on the very first render
// without waiting for the async loadLocale call.
let translations: Record<string, unknown> = enFallback as Record<string, unknown>;

export async function loadLocale(locale: Locale): Promise<void> {
  // Language packs served from S3 via CDN, cached by service worker
  const res = await fetch(`/api/locales/${locale}`);
  if (!res.ok) throw new Error(`Failed to load locale: ${locale}`);
  translations = (await res.json()) as Record<string, unknown>;
}

export function t(key: string): string {
  // Dot-notation: 'nav.inventory', 'alerts.low_stock'
  const value = key
    .split(".")
    .reduce(
      (obj: unknown, k) => (obj as Record<string, unknown>)?.[k],
      translations
    );
  return (value as string) ?? key; // missing key returns the key itself, never empty string
}

export function getCurrentLocale(): Locale {
  if (typeof window === "undefined") return "en";
  return resolveLocale(localStorage.getItem("locale"));
}

export function setLocale(locale: Locale): void {
  localStorage.setItem("locale", locale);
}
