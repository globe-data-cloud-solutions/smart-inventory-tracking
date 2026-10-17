"use client";

import { useEffect } from "react";
import { NOTIFY_TIMEOUT_MS, useNotifyStore } from "@/lib/notify";
import { t } from "@/lib/i18n";

const KIND_CLS = {
  success: "bg-emerald-600 text-white",
  warning: "bg-amber-500 text-white",
  error:   "bg-red-600 text-white",
} as const;

export function GlobalToast() {
  const notice  = useNotifyStore((s) => s.notice);
  const dismiss = useNotifyStore((s) => s.dismiss);

  useEffect(() => {
    if (!notice) return;
    const ms = NOTIFY_TIMEOUT_MS[notice.kind];
    if (ms == null) return;
    const id = setTimeout(dismiss, ms);
    return () => clearTimeout(id);
  }, [notice, dismiss]);

  if (!notice) return null;
  return (
    <div
      key={notice.id}
      data-testid="global-toast"
      data-kind={notice.kind}
      role={notice.kind === "error" ? "alert" : "status"}
      className={`fixed top-4 left-1/2 -translate-x-1/2 z-[9999] max-w-[90vw] flex items-start gap-3 px-5 py-3 rounded-md text-sm font-semibold shadow-xl ${KIND_CLS[notice.kind]}`}
    >
      <span className="break-words">{notice.message}</span>
      <button
        type="button"
        onClick={dismiss}
        aria-label={t("common.close")}
        className="bg-transparent border-0 text-white/80 text-base leading-none cursor-pointer p-0 shrink-0"
      >
        ✕
      </button>
    </div>
  );
}
