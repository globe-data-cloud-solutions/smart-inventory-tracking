"use client";

import { t } from "@/lib/i18n";

/**
 * Shown when the positions list fails to load. Without it the page silently
 * showed empty position pickers, which looked like "no positions exist".
 */
export function PositionsLoadError({ onRetry }: { onRetry?: () => void }) {
  return (
    <div
      role="alert"
      data-testid="positions-load-error"
      className="flex items-center gap-3 bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-4"
    >
      <span className="flex-1">{t("positions.load_error")}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="text-xs font-semibold underline shrink-0">
          {t("positions.retry")}
        </button>
      )}
    </div>
  );
}
