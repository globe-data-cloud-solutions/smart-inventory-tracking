"use client";

import { t } from "@/lib/i18n";
import type { ExpiryAlertType, ExpiryAlertsApi } from "./lotsApi";

interface Props {
  data: ExpiryAlertsApi;
  active: ExpiryAlertType | null;
  onSelect: (type: ExpiryAlertType | null) => void;
}

const CHIPS: Array<{
  type: ExpiryAlertType; testId: string; labelKey: string; tone: string; count: (d: ExpiryAlertsApi) => number;
}> = [
  { type: "EXPIRED",   testId: "lots-chip-expired",   labelKey: "lots.chip_expired",   tone: "bg-red-50 text-red-800 border-red-200",       count: (d) => d.counts.expired },
  { type: "EXPIRING",  testId: "lots-chip-expiring",  labelKey: "lots.chip_expiring",  tone: "bg-amber-50 text-amber-800 border-amber-200", count: (d) => d.counts.expiring },
  { type: "NO_EXPIRY", testId: "lots-chip-no-expiry", labelKey: "lots.chip_no_expiry", tone: "bg-gray-50 text-gray-700 border-gray-300",    count: (d) => d.counts.no_expiry },
];

/** Three expiry count chips; clicking one filters the lots table to those lots. */
export function ExpirySummary({ data, active, onSelect }: Props) {
  return (
    <div data-testid="lots-expiry-summary" className="flex gap-3 flex-wrap mb-6">
      {CHIPS.map((c) => {
        const selected = active === c.type;
        return (
          <button
            key={c.type}
            type="button"
            data-testid={c.testId}
            aria-pressed={selected}
            onClick={() => onSelect(selected ? null : c.type)}
            className={`px-4 py-2 rounded-md border-2 text-sm cursor-pointer transition-all ${c.tone} ${
              selected ? "border-[#0f2d1f]" : ""
            }`}
          >
            <span className="font-extrabold text-lg mr-2">{c.count(data).toLocaleString()}</span>
            <span className="font-medium">
              {t(c.labelKey).replace("{days}", String(data.window_days))}
            </span>
          </button>
        );
      })}
    </div>
  );
}
