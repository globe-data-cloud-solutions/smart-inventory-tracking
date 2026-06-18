"use client";

import { useState } from "react";

interface TabHelpBannerProps {
  message: string;
  tip?: string | null;
  storageKey: string;
  dismissible?: boolean;
}

export function TabHelpBanner({ message, tip, storageKey, dismissible = true }: TabHelpBannerProps) {
  const fullKey = `org-setup-help-${storageKey}`;
  const [dismissed, setDismissed] = useState(
    () => dismissible && typeof window !== "undefined" && sessionStorage.getItem(fullKey) === "dismissed"
  );

  function handleDismiss() {
    sessionStorage.setItem(fullKey, "dismissed");
    setDismissed(true);
  }

  if (dismissed) return null;

  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border-l-4 border-blue-300 bg-blue-50 px-4 py-3 text-sm text-blue-900">
      <span className="mt-0.5 shrink-0 text-blue-400">ℹ️</span>

      <div className="flex-1">
        <p>{message}</p>
        {tip && (
          <p className="mt-1 text-blue-700">
            💡 {tip}
          </p>
        )}
      </div>

      {dismissible && (
        <button
          type="button"
          onClick={handleDismiss}
          className="shrink-0 text-blue-400 hover:text-blue-600"
          aria-label="Dismiss"
        >
          ✕
        </button>
      )}
    </div>
  );
}
