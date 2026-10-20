"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { t } from "@/lib/i18n";

interface TabHelpBannerProps {
  message: string;
  tip?: string | null;
  storageKey: string;
  dismissible?: boolean;
}

const DISMISS_EXPIRY_MS = 7 * 24 * 60 * 60 * 1000;

function getKey(org: string, storageKey: string): string {
  return `org-setup-help-${org}-${storageKey}`;
}

function isDismissed(org: string, storageKey: string): boolean {
  try {
    const raw = localStorage.getItem(getKey(org, storageKey));
    if (!raw) return false;
    const { dismissedAt } = JSON.parse(raw) as { dismissedAt: number };
    return Date.now() - dismissedAt < DISMISS_EXPIRY_MS;
  } catch {
    return false;
  }
}

function setDismissed(org: string, storageKey: string): void {
  localStorage.setItem(getKey(org, storageKey), JSON.stringify({ dismissedAt: Date.now() }));
}

export function TabHelpBanner({ message, tip, storageKey, dismissible = true }: TabHelpBannerProps) {
  const params = useParams();
  const org = (params?.org as string) ?? "default";

  const [dismissed, setDismissedState] = useState(
    () => dismissible && typeof window !== "undefined" && isDismissed(org, storageKey)
  );

  function handleDismiss() {
    setDismissed(org, storageKey);
    setDismissedState(true);
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
          aria-label={t("common.dismiss")}
        >
          ✕
        </button>
      )}
    </div>
  );
}
