"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "@/lib/i18n";
import { useWriteGuard } from "@/hooks/useWriteGuard";
import { useViewedTenantId } from "@/hooks/useViewedTenantId";
import {
  NEAR_EXPIRY_MAX_DAYS, NEAR_EXPIRY_MIN_DAYS, errStatus, fetchExpirySettings, updateExpirySettings,
  type ExpirySettingsApi,
} from "./lotsApi";

interface Props {
  org: string;
  canEdit: boolean;
}

/**
 * "Near-expiry window: N days" with an inline editor for the tenant admin.
 * A role without report:expiry_alerts gets 403 on the read and sees nothing.
 */
export function NearExpirySetting({ org, canEdit }: Props) {
  const qc = useQueryClient();
  const guard = useWriteGuard();
  const viewed = useViewedTenantId(org);
  const scopeTenantId = viewed.isSA ? viewed.tenantId : undefined;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState("");
  const [error, setError]     = useState("");
  const [saving, setSaving]   = useState(false);
  const [saved, setSaved]     = useState(false);

  const settingsQuery = useQuery<ExpirySettingsApi>({
    queryKey: ["lots-expiry-settings", org, scopeTenantId],
    queryFn: () => fetchExpirySettings(scopeTenantId),
    enabled: viewed.ready,
    retry: false,
    staleTime: 0,
    refetchOnMount: true,
  });

  const days = settingsQuery.data?.near_expiry_days;
  // 403 (no report:expiry_alerts) or any other failure: no line, no error.
  if (days === undefined) return null;

  function startEdit() {
    setDraft(String(days));
    setError("");
    setSaved(false);
    setEditing(true);
  }

  function cancel() {
    setEditing(false);
    setError("");
  }

  async function save() {
    setError("");
    const blocked = guard.reason();
    if (blocked) { setError(blocked); return; }

    const trimmed = draft.trim();
    const n = Number(trimmed);
    if (!/^\d+$/.test(trimmed) || n < NEAR_EXPIRY_MIN_DAYS || n > NEAR_EXPIRY_MAX_DAYS) {
      setError(t("lots.window_range_error"));
      return;
    }

    setSaving(true);
    try {
      const out = await updateExpirySettings(n, scopeTenantId);
      qc.setQueryData<ExpirySettingsApi>(["lots-expiry-settings", org, scopeTenantId], out);
      setEditing(false);
      setSaved(true);
      // The lots table, the expiry chips and the dashboard rows all count with this window.
      void qc.invalidateQueries({ queryKey: ["lots-live"] });
      void qc.invalidateQueries({ queryKey: ["lots-expiry-alerts"] });
      void qc.invalidateQueries({ queryKey: ["dashboard-expiry-alerts"] });
    } catch (err: unknown) {
      setError(errStatus(err) === 422 ? t("lots.window_range_error") : t("lots.window_save_error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div data-testid="lots-window" className="mb-4 flex flex-wrap items-center gap-3 text-sm text-gray-700">
      {!editing ? (
        <>
          <span data-testid="lots-window-text" className="font-medium">
            {t("lots.window_label").replace("{days}", String(days))}
          </span>
          {canEdit && (
            <button
              type="button"
              data-testid="lots-window-edit"
              onClick={startEdit}
              className="text-xs font-bold px-3 py-1 rounded bg-gray-100 border border-gray-200 text-gray-700 cursor-pointer"
            >
              {t("common.edit")}
            </button>
          )}
          {saved && (
            <span data-testid="lots-window-saved" className="text-xs font-semibold text-green-800">
              {t("lots.window_saved")}
            </span>
          )}
        </>
      ) : (
        <>
          <label htmlFor="lots-window-input" className="font-medium">{t("lots.window_input_label")}</label>
          <input
            id="lots-window-input"
            data-testid="lots-window-input"
            type="number"
            inputMode="numeric"
            min={NEAR_EXPIRY_MIN_DAYS}
            max={NEAR_EXPIRY_MAX_DAYS}
            step={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-24 px-2.5 py-1.5 text-sm border border-gray-300 rounded outline-none bg-white"
          />
          <button
            type="button"
            data-testid="lots-window-save"
            onClick={() => void save()}
            disabled={saving}
            className={`text-xs font-bold px-3 py-1.5 rounded bg-cyan-600 text-white border-0 ${
              saving ? "opacity-70 cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            {saving ? t("common.loading") : t("common.save")}
          </button>
          <button
            type="button"
            data-testid="lots-window-cancel"
            onClick={cancel}
            disabled={saving}
            className="text-xs font-bold px-3 py-1.5 rounded bg-gray-100 border border-gray-200 text-gray-700 cursor-pointer"
          >
            {t("common.cancel")}
          </button>
        </>
      )}
      {error && (
        <span data-testid="lots-window-error" role="alert" className="w-full text-xs text-red-600">
          {error}
        </span>
      )}
    </div>
  );
}
