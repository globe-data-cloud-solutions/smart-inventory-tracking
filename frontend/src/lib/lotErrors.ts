import { t } from "@/lib/i18n";

/**
 * Every lot / dispatch-engine error code the backend returns (Receive, Issue,
 * Adjustment, opening balance, transfer approval, lot settings, lot expiry).
 * Each one has a translated errors.<CODE> entry in all locale files.
 */
export const LOT_ERROR_CODES: ReadonlySet<string> = new Set([
  "LOT_REQUIRED",
  "LOT_NOT_TRACKED",
  "LOT_INPUT_CONFLICT",
  "LOT_NUMBER_REQUIRED",
  "LOT_NUMBER_GENERATION_FAILED",
  "LOT_NOT_FOUND",
  "LOT_NOT_IN_WAREHOUSE",
  "LOT_EXPIRED",
  "LOT_EXPIRY_MISMATCH",
  "LOT_EXPIRY_ALREADY_SET",
  "LOT_CONVERSION_MISMATCH",
  "LOT_SELECTION_NOT_ALLOWED",
  "INSUFFICIENT_LOT_STOCK",
  "SELECTION_QTY_MISMATCH",
  "OVERRIDE_REASON_REQUIRED",
  "OVERRIDE_NOT_PERMITTED",
  "EXPIRY_REQUIRED",
  "EXPIRY_IN_PAST",
  "EXPIRY_NEEDS_BATCH",
  "EXPIRY_TRACKING_OFF",
]);

/** The backend error code carried by an API error ("" when there is none). */
export function apiErrorCode(err: unknown): string {
  return (err as { code?: string } | null | undefined)?.code ?? "";
}

/** Translated message for a lot error, or null when err is not one. */
export function lotErrorMessage(err: unknown): string | null {
  const code = apiErrorCode(err);
  return LOT_ERROR_CODES.has(code) ? t(`errors.${code}`) : null;
}

/**
 * True when the API rejected the request with a 422 on the quantity_delta field
 * (FastAPI validation: {"detail": [{"loc": ["body", "quantity_delta"], ...}]}).
 */
export function isQuantityDeltaError(err: unknown): boolean {
  const e = err as { status?: number; detail?: unknown } | null | undefined;
  if (e?.status !== 422 || !Array.isArray(e.detail)) return false;
  return e.detail.some(
    (d) => Array.isArray((d as { loc?: unknown }).loc) && (d as { loc: unknown[] }).loc.includes("quantity_delta"),
  );
}
