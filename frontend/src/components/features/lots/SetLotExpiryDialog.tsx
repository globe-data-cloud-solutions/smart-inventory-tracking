"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useWriteGuard } from "@/hooks/useWriteGuard";
import { expiryErrorMessage } from "./lotsApi";

interface Props {
  lotId: string;
  lotNumber: string;
  productName: string;
  onClose: () => void;
  onSaved: () => void;
}

function todayLocal(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Sets an expiry once on a lot that has none (PATCH /inventory/lots/{id}/expiry). */
export function SetLotExpiryDialog({ lotId, lotNumber, productName, onClose, onSaved }: Props) {
  const guard = useWriteGuard();
  const today = todayLocal();
  const [date, setDate]       = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save() {
    setError("");
    const blocked = guard.reason();
    if (blocked) { setError(blocked); return; }
    if (!date) return;
    if (date < today) { setError(t("errors.EXPIRY_IN_PAST")); return; }
    setLoading(true);
    try {
      await api.patch(`/api/v1/inventory/lots/${lotId}/expiry`, { expiry_date: date });
      onSaved();
    } catch (err: unknown) {
      setError(expiryErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center">
      <div onClick={onClose} className="absolute inset-0 bg-black/35 backdrop-blur-sm" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="lots-expiry-dialog-title"
        data-testid="lots-expiry-dialog"
        className="relative bg-white rounded-md shadow-2xl w-[420px] max-w-[92vw] p-6"
      >
        <p id="lots-expiry-dialog-title" className="font-bold text-base text-gray-900 m-0">
          {t("lots.set_expiry_title")}
        </p>
        <p className="text-xs text-gray-500 mt-0.5 mb-4">
          <span className="font-mono">{lotNumber}</span> · {productName}
        </p>

        <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1" htmlFor="lots-expiry-date">
          {t("lots.set_expiry_date")}
        </label>
        <input
          id="lots-expiry-date"
          data-testid="lots-expiry-date"
          type="date"
          min={today}
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white mb-3"
        />

        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2.5 mb-3">
          {t("lots.set_expiry_warning")}
        </p>

        {error && (
          <div data-testid="lots-expiry-error" className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-3">
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
            data-testid="lots-expiry-save"
            onClick={() => void save()}
            disabled={loading || !date}
            className={`flex-[2] py-2.5 bg-cyan-600 text-white font-bold text-sm rounded border-0 ${
              loading || !date ? "opacity-70 cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            {loading ? t("common.loading") : t("common.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
