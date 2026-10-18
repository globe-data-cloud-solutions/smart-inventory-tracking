// Which languages users may pick. Oromo is enabled only once or.json is fully
// translated — see CLAUDE.md §4 and docs/claude/frontend-patterns.md §12 (RB-6).
export type LocaleCode = "en" | "am" | "or";

export const ALL_LOCALES: { code: LocaleCode; label: string }[] = [
  { code: "en", label: "English" },
  { code: "am", label: "አማርኛ" },
  { code: "or", label: "Afaan Oromoo" },
];

function parseEnabledLocales(): LocaleCode[] {
  const raw = process.env.NEXT_PUBLIC_ENABLED_LOCALES ?? "en,am";
  const known = new Set(ALL_LOCALES.map((l) => l.code));
  const codes = raw
    .split(",")
    .map((c) => c.trim())
    .filter((c): c is LocaleCode => known.has(c as LocaleCode));
  if (!codes.includes("en")) codes.unshift("en");
  return Array.from(new Set(codes));
}

export const ENABLED_LOCALES: LocaleCode[] = parseEnabledLocales();

export function isEnabledLocale(code: string): code is LocaleCode {
  return (ENABLED_LOCALES as string[]).includes(code);
}

export function resolveLocale(code: string | null | undefined): LocaleCode {
  if (code && isEnabledLocale(code)) return code;
  return "en";
}
