"use client";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import { formatExpiry } from "@/components/features/transfers/TransferLotDetails";

/* ── GET /api/v1/inventory/dispatch/preview ──────────────────────────────── */
export interface PreviewLotApi {
  lot_id: string;
  lot_number: string;
  expiry_date: string | null;
  quantity: string;
}

export interface DispatchPreviewApi {
  product_id: string;
  warehouse_id: string;
  quantity: string;
  /** null for a product that is not batch-tracked. */
  strategy: string | null;
  strategy_source: string;
  lines: PreviewLotApi[];
  shortfall: string;
  expired_skipped: PreviewLotApi[];
  available_total: string;
}

/** Read-only: which lots the engine WOULD draw from. Nothing is reserved. */
export function fetchDispatchPreview(
  productId: string,
  warehouseId: string,
  quantity: number | string,
): Promise<DispatchPreviewApi> {
  const qs = new URLSearchParams({
    product_id:   productId,
    warehouse_id: warehouseId,
    quantity:     String(quantity),
  });
  return api.get<DispatchPreviewApi>(`/api/v1/inventory/dispatch/preview?${qs.toString()}`);
}

/** Translated FEFO / FIFO / LIFO label; never the raw code for an unknown strategy. */
export function strategyLabel(strategy: string): string {
  const key = `transfers.preview.strategies.${strategy}`;
  const label = t(key);
  return label === key ? t("common.unknown") : label;
}

export function sumQuantity(lots: PreviewLotApi[]): number {
  return lots.reduce((sum, lot) => sum + Number(lot.quantity), 0);
}

/** Shortfall warning + expired-lots note for a preview; renders nothing when neither applies. */
export function PreviewWarnings({ preview }: { preview: DispatchPreviewApi }) {
  const shortfall = Number(preview.shortfall);
  const expired   = sumQuantity(preview.expired_skipped);
  if (!(shortfall > 0) && preview.expired_skipped.length === 0) return null;
  return (
    <>
      {shortfall > 0 && (
        <p className="text-xs font-semibold text-amber-800 bg-amber-50 border border-amber-200 rounded px-2.5 py-1.5 mt-2">
          ⚠ {t("transfers.preview.shortfall").replace("{qty}", formatQty(shortfall))}
        </p>
      )}
      {preview.expired_skipped.length > 0 && (
        <p className="text-xs text-gray-500 mt-1.5">
          {t("transfers.preview.expired_skipped").replace("{qty}", formatQty(expired))}
        </p>
      )}
    </>
  );
}

/** The engine's suggested lots, one per row: lot number, expiry (if any), quantity. */
export function PreviewLotList({ lots }: { lots: PreviewLotApi[] }) {
  return (
    <ul className="m-0 p-0 list-none">
      {lots.map((lot) => (
        <li key={lot.lot_id} className="flex items-baseline justify-between gap-3 text-xs text-gray-700 py-0.5">
          <span>
            <span className="font-mono font-semibold">{lot.lot_number}</span>
            {lot.expiry_date && (
              <span className="text-gray-500 ml-1.5">
                {t("transfers.preview.expiry").replace("{date}", formatExpiry(lot.expiry_date))}
              </span>
            )}
          </span>
          <span className="font-semibold text-gray-900">{formatQty(lot.quantity)}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Information-only box for the transfer request: the dispatch order and the lots
 * the request would likely draw from. Nothing here is sent with the request.
 */
export function DispatchPreviewInfo({ preview }: { preview: DispatchPreviewApi }) {
  if (!preview.strategy) return null;
  return (
    <div className="bg-blue-50 border border-blue-200 rounded px-3 py-2.5 mb-4">
      <p className="text-xs font-bold text-blue-900 m-0">
        {t("transfers.preview.strategy").replace("{strategy}", strategyLabel(preview.strategy))}
      </p>
      {preview.lines.length > 0 && (
        <>
          <p className="text-xs font-semibold text-gray-700 mt-2 mb-1">{t("transfers.preview.likely_lots")}</p>
          <PreviewLotList lots={preview.lines} />
        </>
      )}
      <PreviewWarnings preview={preview} />
      <p className="text-[11px] text-gray-500 mt-2 mb-0">{t("transfers.preview.note")}</p>
    </div>
  );
}
