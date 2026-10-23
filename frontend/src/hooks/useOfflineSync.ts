"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  clearSyncedTransactions,
  getPendingTransactions,
  recordRetryAttempt,
  updateTransactionStatus,
  type OfflineTransaction,
} from "@/store/offlineQueue";

/** Must stay at or below the server's MAX_ITEMS_PER_BATCH (200). */
const CHUNK_SIZE = 100;

/**
 * One sync at a time across ALL hook instances on the page. Several components
 * call useOfflineSync(); without this, each would send the same PENDING items.
 */
let inFlight: Promise<void> | null = null;

interface SyncResultRow {
  idempotency_key: string;
  status: "SYNCED" | "CONFLICT" | "ERROR";
  code?: string | null;
}

export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(
    typeof window !== "undefined" ? navigator.onLine : true
  );
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    const handleOnline  = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online",  handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online",  handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const sync = useCallback(async () => {
    if (!isOnline) return;
    if (inFlight) return inFlight;
    inFlight = runSync(setIsSyncing).finally(() => {
      inFlight = null;
    });
    return inFlight;
  }, [isOnline]);

  // Auto-sync on reconnect
  useEffect(() => {
    if (isOnline) void sync();
  }, [isOnline, sync]);

  return { isOnline, isSyncing, sync };
}

async function runSync(setIsSyncing: (v: boolean) => void): Promise<void> {
  const pending = await getPendingTransactions();
  if (pending.length === 0) return;

  setIsSyncing(true);
  try {
    for (let i = 0; i < pending.length; i += CHUNK_SIZE) {
      const chunk: OfflineTransaction[] = pending.slice(i, i + CHUNK_SIZE);
      let results: SyncResultRow[];
      try {
        results = await api.post<SyncResultRow[]>("/api/v1/inventory/sync/batch", {
          items: chunk.map((tx) => ({
            idempotency_key: tx.idempotencyKey,
            action: tx.action,
            payload: tx.payload,
          })),
        });
      } catch {
        // Network or auth failure: nothing was decided, so every item stays PENDING.
        // Stop here; the next reconnect or manual retry tries again.
        return;
      }

      const answered = new Set<string>();
      for (const row of results) {
        answered.add(row.idempotency_key);
        if (row.status === "SYNCED") {
          await updateTransactionStatus(row.idempotency_key, "SYNCED");
        } else if (row.status === "CONFLICT") {
          await updateTransactionStatus(row.idempotency_key, "CONFLICT", row.code ?? undefined);
        } else {
          await recordRetryAttempt(row.idempotency_key);
        }
      }
      // An item the server did not answer for is not known to be posted: keep it.
      for (const tx of chunk) {
        if (!answered.has(tx.idempotencyKey)) await recordRetryAttempt(tx.idempotencyKey);
      }
    }
    await clearSyncedTransactions();
  } finally {
    setIsSyncing(false);
  }
}
