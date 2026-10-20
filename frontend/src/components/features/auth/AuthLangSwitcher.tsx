"use client";

import { useEffect, useState } from "react";
import { getCurrentLocale, loadLocale, setLocale, t } from "@/lib/i18n";
import { ENABLED_LOCALES } from "@/lib/locales-config";

type Locale = "en" | "am" | "or";

/** Language picker for public (pre-session) pages — signup, verify-email.
 * Endonyms (EN/AM/OR) stay literal, matching the [org] layout's LangSwitcher. */
export function AuthLangSwitcher() {
  const [current, setCurrent] = useState<Locale>("en");

  useEffect(() => {
    setCurrent(getCurrentLocale());
  }, []);

  async function switchLocale(loc: Locale) {
    if (loc === current) return;
    setLocale(loc);
    try {
      await loadLocale(loc);
    } catch {
      /* fallback to key */
    }
    setCurrent(loc);
    window.location.reload();
  }

  return (
    <div className="flex gap-0.5 bg-gray-100 rounded p-0.5">
      {ENABLED_LOCALES.map((loc) => (
        <button
          key={loc}
          type="button"
          onClick={() => void switchLocale(loc)}
          className={`text-[11px] font-bold px-2 py-0.5 rounded border-0 cursor-pointer transition-all ${
            current === loc
              ? "bg-brand-600 text-white"
              : "bg-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          {t(`lang.${loc}`)}
        </button>
      ))}
    </div>
  );
}
