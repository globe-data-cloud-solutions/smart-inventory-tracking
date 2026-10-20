// Locale-aware date/number formatting (CLAUDE.md §4 i18n; docs/claude/frontend-patterns.md §12).
// Dates/times always render on the Gregorian calendar in both languages — the Ethiopian
// calendar is a possible later option, not built here. Numbers use one grouping style
// ("en-US") in both languages; only the calendar/month names differ by locale.
import { getCurrentLocale } from "@/lib/i18n";

function dateLocale(): string {
  return getCurrentLocale() === "am" ? "am-ET" : "en-US";
}

function toDate(value: Date | string | number | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

export function formatNumber(n: number | string | null | undefined, opts?: Intl.NumberFormatOptions): string {
  if (n === null || n === undefined || n === "") return "—";
  const num = typeof n === "number" ? n : Number(n);
  if (!isFinite(num)) return "—";
  return new Intl.NumberFormat("en-US", opts).format(num);
}

// Default option sets mirror what the plain toLocale*String() calls they replace rendered
// (numeric date; numeric date+time with seconds; numeric time with seconds) so a call site
// that passes no opts keeps its prior English output.
const DEFAULT_DATE: Intl.DateTimeFormatOptions = { year: "numeric", month: "numeric", day: "numeric" };
const DEFAULT_DATETIME: Intl.DateTimeFormatOptions = {
  year: "numeric", month: "numeric", day: "numeric",
  hour: "numeric", minute: "numeric", second: "numeric",
};
const DEFAULT_TIME: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "numeric", second: "numeric" };

export function formatDate(value: Date | string | number | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  const d = toDate(value);
  if (!d) return "—";
  return new Intl.DateTimeFormat(dateLocale(), { ...DEFAULT_DATE, ...opts, calendar: "gregory" }).format(d);
}

export function formatDateTime(value: Date | string | number | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  const d = toDate(value);
  if (!d) return "—";
  return new Intl.DateTimeFormat(dateLocale(), { ...DEFAULT_DATETIME, ...opts, calendar: "gregory" }).format(d);
}

export function formatTime(value: Date | string | number | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  const d = toDate(value);
  if (!d) return "—";
  return new Intl.DateTimeFormat(dateLocale(), { ...DEFAULT_TIME, ...opts, calendar: "gregory" }).format(d);
}
