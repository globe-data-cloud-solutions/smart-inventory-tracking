"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  clearSyncedTransactions,
  getPendingTransactions,
  updateTransactionStatus,
} from "@/store/offlineQueue";

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
    if (!isOnline || isSyncing) return;
    const pending = await getPendingTransactions();
    if (pending.length === 0) return;

    setIsSyncing(true);
    try {
      const token = getToken();
      const results = await api.post<Array<{ idempotency_key: string; status: string }>>(
        "/api/v1/sync/batch",
        pending.map((tx) => ({
          idempotency_key: tx.idempotencyKey,
          action: tx.action,
          payload: tx.payload,
        })),
        token ?? undefined
      );

      for (const result of results) {
        await updateTransactionStatus(
          result.idempotency_key,
          result.status === "SYNCED" ? "SYNCED" : "CONFLICT"
        );
      }
      await clearSyncedTransactions();
    } finally {
      setIsSyncing(false);
    }
  }, [isOnline, isSyncing]);

  // Auto-sync on reconnect
  useEffect(() => {
    if (isOnline) void sync();
  }, [isOnline, sync]);

  return { isOnline, isSyncing, sync };
}
