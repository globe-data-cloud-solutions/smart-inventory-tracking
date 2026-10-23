import { openDB, type IDBPDatabase } from "idb";
import { nanoid } from "nanoid";

export interface OfflineTransaction {
  idempotencyKey: string;
  action: string;
  payload: Record<string, unknown>;
  status: "PENDING" | "SYNCING" | "SYNCED" | "CONFLICT";
  createdAt: string;
  retries: number;
  /** Set when the server rejected the item (CONFLICT): a stable error code, e.g. INSUFFICIENT_STOCK. */
  conflictCode?: string;
}

/** Fired on window after every queue write, so the queue panel can re-read IndexedDB. */
export const OFFLINE_QUEUE_EVENT = "offline-queue-changed";

let _db: IDBPDatabase | null = null;

async function getDb(): Promise<IDBPDatabase> {
  if (_db) return _db;
  _db = await openDB("smart-offline", 1, {
    upgrade(db) {
      db.createObjectStore("queue", { keyPath: "idempotencyKey" });
    },
  });
  return _db;
}

function notifyChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(OFFLINE_QUEUE_EVENT));
  }
}

export function generateIdempotencyKey(
  userId: string,
  action: string,
  productId: string
): string {
  return `${userId}:${action}:${productId}:${Date.now()}:${nanoid(8)}`;
}

export async function enqueueOfflineTransaction(
  tx: Omit<OfflineTransaction, "status" | "createdAt" | "retries" | "conflictCode">
): Promise<void> {
  const db = await getDb();
  await db.put("queue", {
    ...tx,
    status: "PENDING",
    createdAt: new Date().toISOString(),
    retries: 0,
  });
  notifyChanged();
}

/** Items to send on the next sync: PENDING only. CONFLICT items wait for the user. */
export async function getPendingTransactions(): Promise<OfflineTransaction[]> {
  const db = await getDb();
  const all = (await db.getAll("queue")) as OfflineTransaction[];
  return all.filter((t) => t.status === "PENDING");
}

/** Everything the user may need to see: items still waiting and items rejected by the server. */
export async function getVisibleTransactions(): Promise<OfflineTransaction[]> {
  const db = await getDb();
  const all = (await db.getAll("queue")) as OfflineTransaction[];
  return all
    .filter((t) => t.status === "PENDING" || t.status === "CONFLICT" || t.status === "SYNCING")
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export async function updateTransactionStatus(
  idempotencyKey: string,
  status: OfflineTransaction["status"],
  conflictCode?: string
): Promise<void> {
  const db = await getDb();
  const tx = (await db.get("queue", idempotencyKey)) as OfflineTransaction | undefined;
  if (tx) {
    const next: OfflineTransaction = { ...tx, status };
    if (status === "CONFLICT") next.conflictCode = conflictCode ?? "REJECTED";
    else delete next.conflictCode;
    await db.put("queue", next);
    notifyChanged();
  }
}

/** A failed attempt (network down, server error): keep the item PENDING and count the attempt. */
export async function recordRetryAttempt(idempotencyKey: string): Promise<void> {
  const db = await getDb();
  const tx = (await db.get("queue", idempotencyKey)) as OfflineTransaction | undefined;
  if (tx) {
    await db.put("queue", { ...tx, status: "PENDING", retries: tx.retries + 1 });
    notifyChanged();
  }
}

/** The user chose Retry on a CONFLICT item: send it again on the next sync. */
export async function requeueTransaction(idempotencyKey: string): Promise<void> {
  await updateTransactionStatus(idempotencyKey, "PENDING");
}

/** The user chose Discard: removes the item from THIS device only. Nothing is sent to the server. */
export async function discardTransaction(idempotencyKey: string): Promise<void> {
  const db = await getDb();
  await db.delete("queue", idempotencyKey);
  notifyChanged();
}

export async function clearSyncedTransactions(): Promise<void> {
  const db = await getDb();
  const all = (await db.getAll("queue")) as OfflineTransaction[];
  for (const tx of all) {
    if (tx.status === "SYNCED") {
      await db.delete("queue", tx.idempotencyKey);
    }
  }
  notifyChanged();
}
