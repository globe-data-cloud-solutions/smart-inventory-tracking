"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getVisibleTransactions,
  OFFLINE_QUEUE_EVENT,
  type OfflineTransaction,
} from "@/store/offlineQueue";

/** Items still waiting to sync, plus items the server rejected. Re-reads on every queue write. */
export function useOfflineQueue() {
  const [items, setItems] = useState<OfflineTransaction[]>([]);

  const refresh = useCallback(async () => {
    setItems(await getVisibleTransactions());
  }, []);

  useEffect(() => {
    void refresh();
    window.addEventListener(OFFLINE_QUEUE_EVENT, refresh);
    return () => window.removeEventListener(OFFLINE_QUEUE_EVENT, refresh);
  }, [refresh]);

  return { items, refresh };
}
