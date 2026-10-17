"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import { useViewedTenantId } from "@/hooks/useViewedTenantId";
import {
  errStatus, fetchOverrides, fetchOverrideSummary,
  type ComplianceCountsApi, type OverrideLogApi, type OverrideLotApi, type OverrideParams,
  type OverrideStrategy, type OverrideSummaryApi,
} from "./lotsApi";

const PAGE_SIZE = 50;
const DEFAULT_PERIOD_DAYS = 30;

const STRATEGIES: OverrideStrategy[] = ["FEFO", "FIFO", "LIFO"];
const STRATEGY_KEY: Record<string, string> = {
  FEFO: "lots.ov_strategy_fefo",
  FIFO: "lots.ov_strategy_fifo",
  LIFO: "lots.ov_strategy_lifo",
};
const MOVEMENT_KEY: Record<string, string> = {
  TRANSFER: "lots.ov_movement_transfer",
  ISSUE: "lots.ov_movement_issue",
};

interface ProductOption { id: string; sku: string; name: string }

/** Local calendar date as YYYY-MM-DD, `offsetDays` from today. */
function ymd(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** 0.8 → "80%", 0.6667 → "66.7%"; null → "—". */
function formatRate(rate: number | null): string {
  if (rate === null) return "—";
  return `${Math.round(rate * 1000) / 10}%`;
}

function LotList({ lots }: { lots: OverrideLotApi[] }) {
  if (lots.length === 0) return <span className="text-gray-400">—</span>;
  return (
    <ul className="m-0 p-0 list-none">
      {lots.map((l) => (
        <li key={l.lot_id} className="whitespace-nowrap">
          <span className="font-mono font-semibold text-gray-800">{l.lot_number ?? "—"}</span>
          <span className="text-gray-500"> × {formatQty(l.quantity)}</span>
        </li>
      ))}
    </ul>
  );
}

function RateCard({ id, label, counts }: { id: string; label: string; counts: ComplianceCountsApi }) {
  return (
    <div data-testid={`ov-card-${id}`} className="bg-white border border-gray-200 rounded-md px-4 py-3 min-w-[170px]">
      <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 m-0">{label}</p>
      <p data-testid={`ov-card-${id}-value`} className="text-2xl font-extrabold text-[#0f2d1f] m-0 mt-1">
        {formatRate(counts.compliance_rate)}
      </p>
      {counts.compliance_rate === null && (
        <p data-testid={`ov-card-${id}-hint`} className="text-xs text-gray-400 m-0 mt-1">
          {t("lots.ov_no_allocations")}
        </p>
      )}
    </div>
  );
}

function CountCard({ id, label, value }: { id: string; label: string; value: number }) {
  return (
    <div data-testid={`ov-card-${id}`} className="bg-white border border-gray-200 rounded-md px-4 py-3 min-w-[170px]">
      <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 m-0">{label}</p>
      <p data-testid={`ov-card-${id}-value`} className="text-2xl font-extrabold text-[#0f2d1f] m-0 mt-1">
        {value.toLocaleString()}
      </p>
    </div>
  );
}

/** Lot override log and FEFO compliance summary (report:dispatch_summary). */
export function OverridesView({ org, warehouseId }: { org: string; warehouseId: string }) {
  const [dateFrom, setDateFrom]   = useState(() => ymd(-(DEFAULT_PERIOD_DAYS - 1)));
  const [dateTo, setDateTo]       = useState(() => ymd(0));
  const [productId, setProductId] = useState("");
  const [strategy, setStrategy]   = useState<OverrideStrategy | "">("");
  const [offset, setOffset]       = useState(0);

  const viewed = useViewedTenantId(org);
  const scopeTenantId = viewed.isSA ? viewed.tenantId : undefined;

  const rangeInvalid = !dateFrom || !dateTo || dateFrom > dateTo;
  const params: OverrideParams = { dateFrom, dateTo, warehouseId, productId, strategy, limit: PAGE_SIZE, offset };

  const productsQuery = useQuery<ProductOption[]>({
    queryKey: ["lot-override-products", org],
    queryFn: () => api.get<ProductOption[]>("/api/v1/products/"),
    retry: false,
    staleTime: 60_000,
  });
  const products = useMemo(
    () => [...(productsQuery.data ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [productsQuery.data],
  );

  const summaryQuery = useQuery<OverrideSummaryApi>({
    queryKey: ["lot-override-summary", org, warehouseId, dateFrom, dateTo, scopeTenantId],
    queryFn: () => fetchOverrideSummary(params, scopeTenantId),
    enabled: !rangeInvalid && viewed.ready,
    retry: false,
    staleTime: 0,
  });

  const listQuery = useQuery<OverrideLogApi>({
    queryKey: ["lot-overrides", org, warehouseId, dateFrom, dateTo, productId, strategy, offset, scopeTenantId],
    queryFn: () => fetchOverrides(params, scopeTenantId),
    enabled: !rangeInvalid && viewed.ready,
    retry: false,
    staleTime: 0,
  });

  const denied = errStatus(listQuery.error) === 403 || errStatus(summaryQuery.error) === 403;
  const failed = !denied && (listQuery.isError || summaryQuery.isError);
  const summary = summaryQuery.data;
  const list = listQuery.data;
  const total = list?.total ?? 0;
  const rows = list?.rows ?? [];

  // Any filter change returns to the first page.
  function change<T>(set: (v: T) => void) {
    return (v: T) => { set(v); setOffset(0); };
  }
  const onFrom     = change(setDateFrom);
  const onTo       = change(setDateTo);
  const onProduct  = change(setProductId);
  const onStrategy = change(setStrategy);

  const fieldCls = "px-2.5 py-1.5 text-sm border border-gray-300 rounded outline-none bg-white";
  const labelCls = "block text-[11px] font-bold uppercase tracking-wide text-gray-500 mb-1";

  return (
    <div data-testid="ov-view">
      <div className="flex gap-3 mb-6 flex-wrap items-end">
        <div>
          <label htmlFor="ov-from" className={labelCls}>{t("lots.ov_from")}</label>
          <input id="ov-from" data-testid="ov-from" type="date" value={dateFrom} max={dateTo || undefined}
            onChange={(e) => onFrom(e.target.value)} className={fieldCls} />
        </div>
        <div>
          <label htmlFor="ov-to" className={labelCls}>{t("lots.ov_to")}</label>
          <input id="ov-to" data-testid="ov-to" type="date" value={dateTo} min={dateFrom || undefined}
            onChange={(e) => onTo(e.target.value)} className={fieldCls} />
        </div>
        <div>
          <label htmlFor="ov-product" className={labelCls}>{t("lots.ov_product")}</label>
          <select id="ov-product" data-testid="ov-product" value={productId}
            onChange={(e) => onProduct(e.target.value)} className={`${fieldCls} max-w-[260px]`}>
            <option value="">{t("lots.ov_all_products")}</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name} · {p.sku}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="ov-strategy" className={labelCls}>{t("lots.ov_strategy")}</label>
          <select id="ov-strategy" data-testid="ov-strategy" value={strategy}
            onChange={(e) => onStrategy(e.target.value as OverrideStrategy | "")} className={fieldCls}>
            <option value="">{t("lots.ov_all_strategies")}</option>
            {STRATEGIES.map((s) => (
              <option key={s} value={s}>{t(STRATEGY_KEY[s]!)}</option>
            ))}
          </select>
        </div>
      </div>

      {rangeInvalid && (
        <p data-testid="ov-range-error" role="alert" className="text-sm text-red-600 mb-4">
          {t("lots.ov_range_error")}
        </p>
      )}

      {denied && (
        <div data-testid="ov-denied" className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-600 text-sm">
          {t("lots.ov_access_denied")}
        </div>
      )}

      {failed && (
        <div data-testid="ov-load-error" className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-4">
          {t("lots.ov_load_error")}
        </div>
      )}

      {!denied && summary && (
        <div data-testid="ov-summary" className="flex gap-3 flex-wrap mb-6">
          <RateCard id="overall" label={t("lots.ov_card_overall")} counts={summary.overall} />
          <RateCard id="fefo" label={t("lots.ov_card_fefo")} counts={summary.fefo} />
          <CountCard id="decisions" label={t("lots.ov_card_decisions")} value={summary.overall.decisions} />
          <CountCard id="overrides" label={t("lots.ov_card_overrides")} value={summary.overall.overridden} />
        </div>
      )}

      {!denied && !rangeInvalid && listQuery.isLoading && (
        <div className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-400 text-sm">
          {t("common.loading")}
        </div>
      )}

      {!denied && list && rows.length === 0 && (
        <div data-testid="ov-empty" className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-400 text-sm">
          {t("lots.ov_empty")}
        </div>
      )}

      {!denied && rows.length > 0 && (
        <>
          <div className="bg-white border border-gray-200 rounded-md overflow-x-auto">
            <table data-testid="ov-table" className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-gray-50">
                  {["lots.ov_col_when", "lots.ov_col_who", "lots.ov_col_product", "lots.ov_col_warehouse",
                    "lots.ov_col_strategy", "lots.ov_col_movement", "lots.ov_col_suggested",
                    "lots.ov_col_chosen", "lots.ov_col_reason"].map((key) => (
                    <th key={key} className="px-3.5 py-2.5 text-left text-[11px] font-bold text-gray-400 uppercase tracking-wide whitespace-nowrap">
                      {t(key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} data-testid="ov-row" className="border-t border-gray-100 align-top">
                    <td className="px-3.5 py-2.5 text-gray-600 whitespace-nowrap">{new Date(r.created_at).toLocaleString()}</td>
                    <td className="px-3.5 py-2.5 text-gray-700">{r.overridden_by ?? "—"}</td>
                    <td className="px-3.5 py-2.5">
                      <span className="font-semibold text-gray-800">{r.product.name}</span>
                      <span className="text-gray-400"> · {r.product.sku}</span>
                    </td>
                    <td className="px-3.5 py-2.5 text-gray-700">{r.warehouse.name ?? "—"}</td>
                    <td data-testid="ov-cell-strategy" className="px-3.5 py-2.5 text-gray-700 whitespace-nowrap">
                      {STRATEGY_KEY[r.strategy] ? t(STRATEGY_KEY[r.strategy]!) : r.strategy}
                    </td>
                    <td data-testid="ov-cell-movement" className="px-3.5 py-2.5 text-gray-700 whitespace-nowrap">
                      {MOVEMENT_KEY[r.movement_type] ? t(MOVEMENT_KEY[r.movement_type]!) : r.movement_type}
                    </td>
                    <td className="px-3.5 py-2.5"><LotList lots={r.suggested} /></td>
                    <td className="px-3.5 py-2.5"><LotList lots={r.chosen} /></td>
                    <td className="px-3.5 py-2.5 text-gray-700">{r.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center gap-3 mt-4 text-sm text-gray-600">
            <button
              type="button"
              data-testid="ov-prev"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className={`px-3 py-1.5 rounded border border-gray-200 bg-gray-100 text-xs font-bold ${
                offset === 0 ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
              }`}
            >
              {t("common.previous")}
            </button>
            <span data-testid="ov-range">
              {t("lots.ov_showing")
                .replace("{from}", String(offset + 1))
                .replace("{to}", String(offset + rows.length))
                .replace("{total}", String(total))}
            </span>
            <button
              type="button"
              data-testid="ov-next"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className={`px-3 py-1.5 rounded border border-gray-200 bg-gray-100 text-xs font-bold ${
                offset + PAGE_SIZE >= total ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
              }`}
            >
              {t("common.next")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
