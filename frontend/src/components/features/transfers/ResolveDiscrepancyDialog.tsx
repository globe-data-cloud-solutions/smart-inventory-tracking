"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useWriteGuard } from "@/hooks/useWriteGuard";
import { formatQty } from "@/lib/utils";
import { errStatus, formatLotDate, type LotApi } from "@/components/features/lots/lotsApi";
import { openDiscrepanciesKey, transferDetailKey } from "./transferQueryKeys";

export type Resolution = "WRITTEN_OFF" | "RETURNED" | "ARRIVED_LATE" | "RECEIVED_AS_LOT";

/** What the dialog needs to know about the discrepancy being settled. */
export interface ResolveTarget {
  transferId: string;
  discrepancyId: string;
  productId: string;
  productName: string;
  /** Source warehouse of the transfer — RECEIVED_AS_LOT draws from one of its lots. */
  fromWarehouseId: string;
  lotId: string | null;
  lotNumber: string | null;
  sent: string;
  received: string;
  missing: string;
  reason: string;
  note: string | null;
}

/** Mirrors _RESOLUTIONS_BY_REASON in transfer_discrepancies.py; the backend decides. */
const OUTCOMES_BY_REASON: Record<string, Resolution[]> = {
  SHORT:     ["WRITTEN_OFF", "RETURNED", "ARRIVED_LATE"],
  DAMAGED:   ["WRITTEN_OFF"],
  WRONG_LOT: ["WRITTEN_OFF", "RETURNED", "RECEIVED_AS_LOT"],
};

export function allowedOutcomes(reason: string, lotId: string | null): Resolution[] {
  return (OUTCOMES_BY_REASON[reason] ?? []).filter((r) => r !== "RECEIVED_AS_LOT" || lotId !== null);
}

const NOTE_MAX = 500;

const RESOLVE_ERROR_CODES = new Set([
  "DISCREPANCY_ALREADY_RESOLVED", "RESOLUTION_NOT_ALLOWED", "RESOLUTION_NOTE_REQUIRED",
  "RESOLUTION_LOT_INVALID", "DISCREPANCY_OUT_OF_SCOPE", "DISCREPANCY_NOT_FOUND",
  "INSUFFICIENT_LOT_STOCK",
]);

/** Translated message for a failed resolve call; never a raw code or backend English. */
function resolveErrorMessage(err: unknown): string {
  const code = (err as { code?: string } | null | undefined)?.code ?? "";
  if (RESOLVE_ERROR_CODES.has(code)) return t(`transfers.discrepancies.errors.${code}`);
  if (errStatus(err) === 403) return t("errors.RBAC_DENIED");
  return t("transfers.discrepancies.errors.GENERIC");
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-wide text-gray-400 m-0">{label}</p>
      <p className="text-sm text-gray-900 font-semibold m-0">{value}</p>
    </div>
  );
}

interface Props {
  target: ResolveTarget;
  onClose: () => void;
  onResolved: () => void;
}

/** Settles one OPEN receipt discrepancy (POST …/{transfer}/discrepancies/{id}/resolve). */
export function ResolveDiscrepancyDialog({ target, onClose, onResolved }: Props) {
  const guard = useWriteGuard();
  const qc = useQueryClient();
  const outcomes = allowedOutcomes(target.reason, target.lotId);

  const [outcome, setOutcome] = useState<Resolution | "">(outcomes.length === 1 ? (outcomes[0] ?? "") : "");
  const [lotId, setLotId]     = useState("");
  const [note, setNote]       = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The lot that actually arrived is one of the product's lots at the SOURCE warehouse.
  const needsLot = outcome === "RECEIVED_AS_LOT";
  const lotsQuery = useQuery<LotApi[]>({
    queryKey: ["discrepancy-source-lots", target.productId, target.fromWarehouseId],
    queryFn: () => api.get<LotApi[]>(
      `/api/v1/inventory/lots?${new URLSearchParams({
        product_id: target.productId,
        warehouse_id: target.fromWarehouseId,
        limit: "1000",
      }).toString()}`,
    ),
    enabled: needsLot,
    retry: false,
    staleTime: 0,
  });
  const lotChoices = (lotsQuery.data ?? []).filter(
    (l) => l.lot_id.toLowerCase() !== (target.lotId ?? "").toLowerCase(),
  );
  const lotsFailed = needsLot && lotsQuery.isError;
  const lotsEmpty  = needsLot && lotsQuery.isSuccess && lotChoices.length === 0;

  const confirmDisabled =
    loading || outcome === "" || (needsLot && (lotsQuery.isPending || lotsFailed || lotsEmpty || lotId === ""));

  async function confirm() {
    setError("");
    const blocked = guard.reason();
    if (blocked) { setError(blocked); return; }
    if (outcome === "") return;
    const trimmed = note.trim();
    if (outcome === "WRITTEN_OFF" && trimmed === "") {
      setError(t("transfers.discrepancies.errors.RESOLUTION_NOTE_REQUIRED"));
      return;
    }
    const body: { resolution: Resolution; lot_id?: string; note?: string } = { resolution: outcome };
    if (outcome === "RECEIVED_AS_LOT") body.lot_id = lotId;
    if (trimmed !== "") body.note = trimmed;

    setLoading(true);
    try {
      await api.post(
        `/api/v1/inventory/transfers/${target.transferId}/discrepancies/${target.discrepancyId}/resolve`,
        body,
      );
      void qc.invalidateQueries({ queryKey: transferDetailKey(target.transferId) });
      void qc.invalidateQueries({ queryKey: openDiscrepanciesKey() });
      // Resolving can move stock, so balances and lot views are stale too.
      void qc.invalidateQueries({ queryKey: ["inventory-stock"] });
      void qc.invalidateQueries({ queryKey: ["lots-live"] });
      onResolved();
    } catch (err: unknown) {
      console.error("[resolveDiscrepancy] failed:", err);
      setError(resolveErrorMessage(err));
      if ((err as { code?: string } | null)?.code === "DISCREPANCY_ALREADY_RESOLVED") {
        void qc.invalidateQueries({ queryKey: transferDetailKey(target.transferId) });
        void qc.invalidateQueries({ queryKey: openDiscrepanciesKey() });
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[210] flex items-center justify-center">
      <div onClick={onClose} className="absolute inset-0 bg-black/35 backdrop-blur-sm" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="resolve-discrepancy-title"
        data-testid="resolve-discrepancy-dialog"
        className="relative bg-white rounded-md shadow-2xl w-[480px] max-w-[92vw] max-h-[92vh] overflow-y-auto p-6"
      >
        <p id="resolve-discrepancy-title" className="font-bold text-base text-gray-900 m-0">
          {t("transfers.discrepancies.dialog_title")}
        </p>
        <p className="text-xs text-gray-500 mt-0.5 mb-4">
          {target.lotNumber ? <><span className="font-mono">{target.lotNumber}</span> · </> : null}
          {target.productName}
        </p>

        <div className="grid grid-cols-3 gap-3 mb-3">
          <Fact label={t("transfers.discrepancies.col_sent")}     value={formatQty(target.sent)} />
          <Fact label={t("transfers.discrepancies.col_received")} value={formatQty(target.received)} />
          <Fact label={t("transfers.discrepancies.col_missing")}  value={formatQty(target.missing)} />
        </div>
        <div className="mb-4 text-xs text-gray-700">
          <p className="m-0">
            <span className="font-bold">{t("transfers.discrepancies.col_reason")}: </span>
            {t(`transfers.discrepancies.reason.${target.reason}`) === `transfers.discrepancies.reason.${target.reason}`
              ? t("common.unknown")
              : t(`transfers.discrepancies.reason.${target.reason}`)}
          </p>
          {target.note && (
            <p className="m-0 mt-1 break-words">
              <span className="font-bold">{t("transfers.discrepancies.receiver_note")}: </span>
              {target.note}
            </p>
          )}
        </div>

        <fieldset className="border-0 p-0 m-0 mb-3">
          <legend className="text-xs font-bold uppercase tracking-wide text-gray-700 mb-1.5 p-0">
            {t("transfers.discrepancies.outcome_label")}
          </legend>
          {outcomes.map((o) => (
            <label
              key={o}
              className={`flex items-start gap-2 p-2 mb-1.5 rounded border cursor-pointer ${
                outcome === o ? "border-cyan-600 bg-cyan-50" : "border-gray-200"
              }`}
            >
              <input
                type="radio"
                name="resolve-outcome"
                data-testid={`resolve-outcome-${o}`}
                checked={outcome === o}
                onChange={() => { setOutcome(o); setError(""); }}
                className="mt-0.5"
              />
              <span>
                <span className="block text-sm font-semibold text-gray-900">
                  {t(`transfers.discrepancies.resolution.${o}`)}
                </span>
                <span className="block text-[11px] text-gray-500">
                  {t(`transfers.discrepancies.help.${o}`)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>

        {needsLot && (
          <div className="mb-3">
            <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1" htmlFor="resolve-lot">
              {t("transfers.discrepancies.lot_label")}
            </label>
            {lotsQuery.isPending ? (
              <p className="text-xs text-gray-400 m-0">{t("transfers.discrepancies.lots_loading")}</p>
            ) : lotsFailed ? (
              <p data-testid="resolve-lots-error" className="text-xs text-red-600 m-0">{t("transfers.discrepancies.lots_failed")}</p>
            ) : lotsEmpty ? (
              <p data-testid="resolve-lots-none" className="text-xs text-amber-800 m-0">{t("transfers.discrepancies.lots_none")}</p>
            ) : (
              <select
                id="resolve-lot"
                data-testid="resolve-lot"
                value={lotId}
                onChange={(e) => setLotId(e.target.value)}
                className="w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white"
              >
                <option value="">{t("transfers.discrepancies.lot_placeholder")}</option>
                {lotChoices.map((l) => (
                  <option key={l.lot_id} value={l.lot_id}>
                    {t("transfers.discrepancies.lot_option")
                      .replace("{lot}", l.lot_number)
                      .replace("{expiry}", formatLotDate(l.expiry_date))
                      .replace("{qty}", formatQty(l.quantity))}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1" htmlFor="resolve-note">
          {t("transfers.discrepancies.note_label")}
          {outcome === "WRITTEN_OFF" && <span className="text-red-600"> *</span>}
        </label>
        <textarea
          id="resolve-note"
          data-testid="resolve-note"
          value={note}
          maxLength={NOTE_MAX}
          rows={3}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("transfers.discrepancies.note_placeholder")}
          className="w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white mb-1 resize-y"
        />
        <p className="text-[10px] text-gray-400 text-right m-0 mb-3">{note.length}/{NOTE_MAX}</p>

        {error && (
          <div data-testid="resolve-error" className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-3">
            {error}
          </div>
        )}

        <div className="flex gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            data-testid="resolve-confirm"
            onClick={() => void confirm()}
            disabled={confirmDisabled}
            className={`flex-[2] py-2.5 bg-cyan-600 text-white font-bold text-sm rounded border-0 ${
              confirmDisabled ? "opacity-70 cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            {loading ? t("common.loading") : t("common.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
