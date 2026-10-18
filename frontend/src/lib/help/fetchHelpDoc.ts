import { getCurrentLocale } from "@/lib/i18n";

/** Fetches a help markdown file in the current locale, falling back to English. */
export async function fetchHelpDoc(file: string): Promise<string> {
  const locale = getCurrentLocale();
  if (locale !== "en") {
    const res = await fetch(`/help/${locale}/${file}`);
    if (res.ok) return res.text();
  }
  const res = await fetch(`/help/${file}`);
  if (!res.ok) throw new Error("fetch failed");
  return res.text();
}
