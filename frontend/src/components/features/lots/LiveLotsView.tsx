"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";
import { useFeatures } from "@/hooks/useFeatures";
import { useTenantName } from "@/hooks/useTenantName";
import { formatQty } from "@/lib/utils";
import { usePermission } from "@/lib/permissions";
import { ExpirySummary } from "./ExpirySummary";
import { NearExpirySetting } from "./NearExpirySetting";
import { OverridesView } from "./OverridesView";
import { SetLotExpiryDialog } from "./SetLotExpiryDialog";
import {
  errStatus, expiryRelative, fetchExpiryAlerts, fetchLots, formatLotDate,
  type ExpiryAlertType, type ExpiryAlertsApi, type LotApi,
} from "./lotsApi";

type StatusFilter = "ALL" | "ACTIVE" | "EXPIRING" | "EXPIRED" | "DEPLETED";
type PageView = "lots" | "overrides";

const STATUS_FILTERS: Array<{ value: StatusFilter; labelKey: string; testId: string }> = [
  { value: "ALL",      labelKey: "lots.filter_all",           testId: "lots-filter-all" },
  { value: "ACTIVE",   labelKey: "lots.filter_active",        testId: "lots-filter-active" },
  { value: "EXPIRING", labelKey: "lots.filter_expiring_soon", testId: "lots-filter-expiring" },
  { value: "EXPIRED",  labelKey: "lots.filter_expired",       testId: "lots-filter-expired" },
  { value: "DEPLETED", labelKey: "lots.filter_depleted",      testId: "lots-filter-depleted" },
];

const BADGE_CLASS = {
  active:   "bg-green-100 text-green-800",
  expiring: "bg-amber-100 text-amber-800",
  expired:  "bg-red-100 text-red-900",
  depleted: "bg-gray-100 text-gray-500",
} as const;

function badgeFor(lot: LotApi): { cls: string; labelKey: string } {
  if (lot.status === "DEPLETED") return { cls: BADGE_CLASS.depleted, labelKey: "lots.status_depleted" };
  if (lot.status === "EXPIRED")  return { cls: BADGE_CLASS.expired,  labelKey: "lots.status_expired" };
  if (lot.expiring_soon)         return { cls: BADGE_CLASS.expiring, labelKey: "lots.status_expiring_soon" };
  return { cls: BADGE_CLASS.active, labelKey: "lots.status_active" };
}

const lotKey = (lotId: string, warehouseId: string) => `${lotId.toLowerCase()}|${warehouseId.toLowerCase()}`;

/** Gateway-mode lots view: real lot balances, expiry summary and the set-expiry action. */
export function LiveLotsView({ org }: { org: string }) {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const tenantName = useTenantName(org);
  const user = getSession();
  const { lotTracking } = useFeatures();

  // Facility-scoped roles only ever see their own warehouse (same scoping as the dashboard).
  const warehouseId = user?.warehouseId ?? "";
  const canSetExpiry = user?.role === "TA" || user?.role === "NM";
  const canEditWindow = usePermission("tenant:configure", user?.role ?? "");
  const canSeeOverrides = usePermission("report:dispatch_summary", user?.role ?? "");

  const [search, setSearch]             = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [alertFilter, setAlertFilter]   = useState<ExpiryAlertType | null>(null);
  const [dialogLot, setDialogLot]       = useState<LotApi | null>(null);
  const [saved, setSaved]               = useState(false);
  const [view, setView]                 = useState<PageView>("lots");

  // useFeatures() has no loading flag — read the shared query state so the
  // "enable batch tracking" hint does not flash while the flag is still loading.
  const featuresState = qc.getQueryState(["features"]);
  const featuresLoading = !featuresState || featuresState.status === "pending";

  const includeDepleted = statusFilter === "DEPLETED";

  const lotsQuery = useQuery<LotApi[]>({
    queryKey: ["lots-live", org, warehouseId, includeDepleted],
    queryFn: () => fetchLots(warehouseId, includeDepleted),
    enabled: lotTracking,
    staleTime: 0,
    refetchOnMount: true,
  });

  const alertsQuery = useQuery<ExpiryAlertsApi>({
    queryKey: ["lots-expiry-alerts", org, warehouseId],
    queryFn: () => fetchExpiryAlerts(warehouseId),
    enabled: lotTracking,
    retry: false,
    staleTime: 0,
    refetchOnMount: true,
  });

  const alerts = alertsQuery.data;
  const alertsForbidden = errStatus(alertsQuery.error) === 403;

  // ?view=expiry → preselect the most urgent non-empty chip, once.
  const preselected = useRef(false);
  const wantsExpiryView = searchParams.get("view") === "expiry";
  useEffect(() => {
    if (preselected.current || !wantsExpiryView || !alerts) return;
    preselected.current = true;
    if (alerts.counts.expired > 0) setAlertFilter("EXPIRED");
    else if (alerts.counts.expiring > 0) setAlertFilter("EXPIRING");
    else setAlertFilter("NO_EXPIRY");
  }, [wantsExpiryView, alerts]);

  const noExpiryLotIds = useMemo(() => {
    const s = new Set<string>();
    for (const it of alerts?.items ?? []) if (it.alert_type === "NO_EXPIRY") s.add(it.lot_id.toLowerCase());
    return s;
  }, [alerts]);

  const alertKeys = useMemo(() => {
    const s = new Set<string>();
    if (!alertFilter) return s;
    for (const it of alerts?.items ?? []) {
      if (it.alert_type === alertFilter) s.add(lotKey(it.lot_id, it.warehouse_id));
    }
    return s;
  }, [alerts, alertFilter]);

  const lots = useMemo(() => lotsQuery.data ?? [], [lotsQuery.data]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return lots.filter((l) => {
      if (q && !(l.lot_number.toLowerCase().includes(q)
        || l.product_name.toLowerCase().includes(q)
        || l.product_sku.toLowerCase().includes(q))) return false;
      if (alertFilter) return alertKeys.has(lotKey(l.lot_id, l.warehouse_id));
      switch (statusFilter) {
        case "ACTIVE":   return l.status === "ACTIVE";
        case "EXPIRING": return l.expiring_soon && l.status !== "EXPIRED";
        case "EXPIRED":  return l.status === "EXPIRED";
        case "DEPLETED": return l.status === "DEPLETED";
        default:         return true;
      }
    });
  }, [lots, search, statusFilter, alertFilter, alertKeys]);

  function pickStatus(s: StatusFilter) {
    setAlertFilter(null);
    setStatusFilter(s);
  }

  function pickAlert(type: ExpiryAlertType | null) {
    setStatusFilter("ALL");
    setAlertFilter(type);
  }

  function onSaved() {
    setDialogLot(null);
    setSaved(true);
    void qc.invalidateQueries({ queryKey: ["lots-live"] });
    void qc.invalidateQueries({ queryKey: ["lots-expiry-alerts"] });
  }

  const header = (
    <div className="mb-6">
      <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("lots.title")}</h2>
      <p className="text-sm text-gray-500 mt-1">{tenantName ?? org} · {t("lots.subtitle")}</p>
    </div>
  );

  if (!lotTracking) {
    return (
      <div className="p-8">
        {header}
        {!featuresLoading && (
          <div className="bg-white border border-gray-200 rounded-md p-12 text-center">
            <p className="text-gray-700 font-semibold mb-2">{t("lots.no_records")}</p>
            <p className="text-sm text-gray-400">{t("lots.enable_batch_hint")}</p>
          </div>
        )}
      </div>
    );
  }

  const noLotsAtAll = !lotsQuery.isLoading && !lotsQuery.isError && lots.length === 0
    && !search.trim() && statusFilter === "ALL" && !alertFilter;

  const viewSwitch = canSeeOverrides ? (
    <div role="group" aria-label={t("lots.view_switch_label")} className="flex gap-1.5 mb-6">
      {([
        { value: "lots" as const,      labelKey: "lots.view_lots",      testId: "lots-view-lots" },
        { value: "overrides" as const, labelKey: "lots.view_overrides", testId: "lots-view-overrides" },
      ]).map((v) => (
        <button
          key={v.value}
          type="button"
          data-testid={v.testId}
          aria-pressed={view === v.value}
          onClick={() => setView(v.value)}
          className={`text-sm font-bold px-4 py-1.5 rounded-md cursor-pointer border-2 transition-all ${
            view === v.value
              ? "bg-[#0f2d1f] text-white border-[#0f2d1f]"
              : "bg-white text-gray-600 border-gray-200 hover:border-gray-300"
          }`}
        >
          {t(v.labelKey)}
        </button>
      ))}
    </div>
  ) : null;

  if (canSeeOverrides && view === "overrides") {
    return (
      <div className="p-8">
        {header}
        {viewSwitch}
        <OverridesView org={org} warehouseId={warehouseId} />
      </div>
    );
  }

  return (
    <div className="p-8">
      {header}

      {viewSwitch}

      <NearExpirySetting org={org} canEdit={canEditWindow} />

      {alerts && !alertsForbidden && (
        <ExpirySummary data={alerts} active={alertFilter} onSelect={pickAlert} />
      )}
      {alertsQuery.isError && !alertsForbidden && (
        <p data-testid="lots-expiry-summary-error" className="text-xs text-red-600 mb-4">
          {t("lots.summary_error")}
        </p>
      )}

      {saved && (
        <div data-testid="lots-expiry-success" className="mb-4 px-4 py-3 rounded-md text-sm font-semibold bg-green-50 text-green-800 border border-green-200">
          {t("lots.set_expiry_success")}
        </div>
      )}

      <div className="flex gap-3 mb-6 flex-wrap items-center">
        <div className="relative flex-1 min-w-[240px]">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
          <input
            type="text"
            data-testid="lots-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("lots.search_placeholder")}
            className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-md outline-none"
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {STATUS_FILTERS.map((f) => {
            const active = !alertFilter && statusFilter === f.value;
            return (
              <button
                key={f.value}
                type="button"
                data-testid={f.testId}
                aria-pressed={active}
                onClick={() => pickStatus(f.value)}
                className={`text-xs font-bold px-3 py-1 rounded-full cursor-pointer border-2 transition-all ${
                  active
                    ? "bg-gray-100 text-gray-700 border-[#0f2d1f]"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                }`}
              >
                {t(f.labelKey)}
              </button>
            );
          })}
        </div>
      </div>

      {lotsQuery.isError ? (
        <div data-testid="lots-load-error" className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600">
          {t("lots.load_error")}
        </div>
      ) : lotsQuery.isLoading ? (
        <div className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-400 text-sm">
          {t("common.loading")}
        </div>
      ) : filtered.length === 0 ? (
        <div data-testid="lots-empty" className="bg-white border border-gray-200 rounded-md p-12 text-center text-gray-400 text-sm">
          <p className={noLotsAtAll ? "mb-2" : "m-0"}>{t("lots.no_results")}</p>
          {noLotsAtAll && <p className="m-0">{t("lots.enable_batch_hint")}</p>}
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-md overflow-x-auto">
          <table data-testid="lots-table" className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50">
                {["lots.lot_number", "lots.product", "lots.warehouse", "lots.quantity", "lots.expiry", "lots.received", "lots.status"].map((key) => (
                  <th key={key} className="px-3.5 py-2.5 text-left text-[11px] font-bold text-gray-400 uppercase tracking-wide whitespace-nowrap">
                    {t(key)}
                  </th>
                ))}
                <th className="px-3.5 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((l) => {
                const badge = badgeFor(l);
                const canSet = canSetExpiry && noExpiryLotIds.has(l.lot_id.toLowerCase());
                return (
                  <tr key={lotKey(l.lot_id, l.warehouse_id)} data-testid={`lots-row-${l.lot_number}`} className="border-t border-gray-100">
                    <td className="px-3.5 py-2.5 font-mono font-bold text-gray-800 whitespace-nowrap">
                      {l.lot_number}
                      {l.is_opening && (
                        <span className="ml-2 text-[10px] font-bold bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded font-sans">
                          {t("lots.opening_tag")}
                        </span>
                      )}
                    </td>
                    <td className="px-3.5 py-2.5">
                      <span className="font-semibold text-gray-800">{l.product_name}</span>
                      <span className="block text-xs text-gray-400">{l.product_sku}</span>
                    </td>
                    <td className="px-3.5 py-2.5 text-gray-700">{l.warehouse_name}</td>
                    <td className="px-3.5 py-2.5 font-bold text-eth-forest">{formatQty(l.quantity)}</td>
                    <td className="px-3.5 py-2.5 whitespace-nowrap">
                      {l.expiry_date && <span className="text-gray-800">{formatLotDate(l.expiry_date)}</span>}
                      <span className={`block text-xs ${l.status === "EXPIRED" ? "text-red-600" : "text-gray-400"}`}>
                        {expiryRelative(l.days_to_expiry)}
                      </span>
                    </td>
                    <td className="px-3.5 py-2.5 text-gray-500 whitespace-nowrap">{formatLotDate(l.first_received_at)}</td>
                    <td className="px-3.5 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded whitespace-nowrap ${badge.cls}`}>
                        {t(badge.labelKey)}
                      </span>
                    </td>
                    <td className="px-3.5 py-2.5 text-right">
                      {canSet && (
                        <button
                          type="button"
                          data-testid={`lots-set-expiry-${l.lot_number}`}
                          onClick={() => { setSaved(false); setDialogLot(l); }}
                          className="text-xs font-bold px-3 py-1.5 rounded bg-cyan-600 text-white border-0 cursor-pointer whitespace-nowrap"
                        >
                          {t("lots.set_expiry")}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {dialogLot && (
        <SetLotExpiryDialog
          lotId={dialogLot.lot_id}
          lotNumber={dialogLot.lot_number}
          productName={dialogLot.product_name}
          onClose={() => setDialogLot(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}
