"use client";

import { useState } from "react";
import { useOfflineQueue } from "@/hooks/useOfflineQueue";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { discardTransaction, requeueTransaction, type OfflineTransaction } from "@/store/offlineQueue";
import { hasKey, t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";

interface QueueProduct {
  id: string;
  name: string;
  sku: string;
}

interface Props {
  products: QueueProduct[];
}

/**
 * Shows movements queued while offline. Hidden when the queue is empty.
 * Items still PENDING sync on reconnect by themselves. CONFLICT items (the server
 * rejected them) need the user: Retry sends them again, Discard removes them from
 * this device only.
 */
export function OfflineQueuePanel({ products }: Props) {
  const { items, refresh } = useOfflineQueue();
  const { sync, isSyncing, isOnline } = useOfflineSync();
  const [confirmKey, setConfirmKey] = useState<string | null>(null);

  if (items.length === 0) return null;

  const conflicts = items.filter((tx) => tx.status === "CONFLICT");
  const productName = (tx: OfflineTransaction): string => {
    const id = String(tx.payload.product_id ?? "");
    const p = products.find((x) => x.id.toLowerCase() === id.toLowerCase());
    return p ? `${p.name} (${p.sku})` : t("offline_queue.unknown_product");
  };
  const reason = (tx: OfflineTransaction): string => {
    const code = tx.conflictCode ?? "";
    return code && hasKey(`errors.${code}`) ? t(`errors.${code}`) : t("offline_queue.conflict_generic");
  };
  const actionLabel = (tx: OfflineTransaction): string =>
    tx.action === "inventory:issue" ? t("offline_queue.action_issue") : t("offline_queue.action_receive");

  async function retry(key: string) {
    await requeueTransaction(key);
    await refresh();
    await sync();
  }

  async function discard(key: string) {
    await discardTransaction(key);
    setConfirmKey(null);
    await refresh();
  }

  return (
    <div className="w-full rounded-md border border-amber-300 bg-amber-50 p-3 text-sm space-y-2" role="status">
      <p className="font-medium">
        {t("offline_queue.waiting").replace("{count}", String(items.length))}
        {!isOnline && <span className="ml-2 font-normal">{t("offline_queue.not_connected")}</span>}
        {isSyncing && <span className="ml-2 font-normal">{t("offline_queue.syncing")}</span>}
      </p>

      {conflicts.length > 0 && (
        <div className="space-y-2">
          <p className="font-medium">{t("offline_queue.conflict_title")}</p>
          {conflicts.map((tx) => (
            <div key={tx.idempotencyKey} className="flex flex-wrap items-center gap-2 justify-between border-t border-amber-200 pt-2">
              <div>
                <div>
                  {actionLabel(tx)} · {productName(tx)} · {formatQty(String(tx.payload.quantity ?? ""))}
                </div>
                <div className="text-xs text-slate-600">{reason(tx)}</div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded border px-2 py-1"
                  onClick={() => void retry(tx.idempotencyKey)}
                  disabled={!isOnline || isSyncing}
                >
                  {t("offline_queue.retry")}
                </button>
                {confirmKey === tx.idempotencyKey ? (
                  <button
                    type="button"
                    className="rounded border border-red-400 px-2 py-1 text-red-700"
                    onClick={() => void discard(tx.idempotencyKey)}
                  >
                    {t("offline_queue.confirm_discard")}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="rounded border px-2 py-1"
                    onClick={() => setConfirmKey(tx.idempotencyKey)}
                  >
                    {t("offline_queue.discard")}
                  </button>
                )}
              </div>
            </div>
          ))}
          <p className="text-xs text-slate-600">{t("offline_queue.discard_hint")}</p>
        </div>
      )}
    </div>
  );
}
