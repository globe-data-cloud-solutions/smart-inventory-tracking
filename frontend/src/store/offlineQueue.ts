import { openDB, type IDBPDatabase } from "idb";
import { nanoid } from "nanoid";

export interface OfflineTransaction {
  idempotencyKey: string;
  action: string;
  payload: Record<string, unknown>;
  status: "PENDING" | "SYNCING" | "SYNCED" | "CONFLICT";
  createdAt: string;
  retries: number;
}

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

export function generateIdempotencyKey(
  userId: string,
  action: string,
  productId: string
): string {
  return `${userId}:${action}:${productId}:${Date.now()}:${nanoid(8)}`;
}

export async function enqueueOfflineTransaction(
  tx: Omit<OfflineTransaction, "status" | "createdAt" | "retries">
): Promise<void> {
  const db = await getDb();
  await db.put("queue", {
    ...tx,
    status: "PENDING",
    createdAt: new Date().toISOString(),
    retries: 0,
  });
}

export async function getPendingTransactions(): Promise<OfflineTransaction[]> {
  const db = await getDb();
  const all = await db.getAll("queue");
  return (all as OfflineTransaction[]).filter((t) => t.status === "PENDING");
}

export async function updateTransactionStatus(
  idempotencyKey: string,
  status: OfflineTransaction["status"]
): Promise<void> {
  const db = await getDb();
  const tx = (await db.get("queue", idempotencyKey)) as OfflineTransaction | undefined;
  if (tx) {
    await db.put("queue", { ...tx, status });
  }
}

export async function clearSyncedTransactions(): Promise<void> {
  const db = await getDb();
  const all = (await db.getAll("queue")) as OfflineTransaction[];
  for (const tx of all) {
    if (tx.status === "SYNCED") {
      await db.delete("queue", tx.idempotencyKey);
    }
  }
}
