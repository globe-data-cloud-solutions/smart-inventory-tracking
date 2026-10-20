"use client";

import { t } from "@/lib/i18n";

const inputCls = "w-full px-2.5 py-2 text-sm border border-gray-300 rounded outline-none bg-white";

interface LotFieldsProps {
  lotNumber: string;
  expiryDate: string;
  autoLot: boolean;
  expiryRequired: boolean;
  onLotNumberChange: (val: string) => void;
  onExpiryDateChange: (val: string) => void;
  onAutoLotChange: (val: boolean) => void;
}

export function LotFields({
  lotNumber, expiryDate, autoLot, expiryRequired,
  onLotNumberChange, onExpiryDateChange, onAutoLotChange,
}: LotFieldsProps) {
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <div className="mb-4">
        <label className="flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={autoLot}
            onChange={(e) => onAutoLotChange(e.target.checked)}
          />
          {t("receive_panel.auto_lot_checkbox")}
        </label>
      </div>
      <div className="mb-4">
        <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
          {t("inventory.receive.lot_number")}
        </label>
        <input
          type="text"
          value={lotNumber}
          disabled={autoLot}
          onChange={(e) => onLotNumberChange(e.target.value)}
          // i18n-ignore: example lot code
          placeholder="e.g. LOT-2026-001"
          className={`${inputCls} ${autoLot ? "bg-gray-100 text-gray-500 cursor-not-allowed" : ""}`}
        />
      </div>
      <div className="mb-4">
        <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
          {t("inventory.receive.expiry_date")}
          {!expiryRequired && (
            <span className="text-[11px] font-normal normal-case text-gray-400 ml-1.5">
              ({t("receive_panel.optional")})
            </span>
          )}
        </label>
        <input
          type="date"
          min={today}
          value={expiryDate}
          onChange={(e) => onExpiryDateChange(e.target.value)}
          className={inputCls}
          required={expiryRequired}
        />
      </div>
    </>
  );
}
