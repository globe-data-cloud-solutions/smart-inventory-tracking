// Shared in-memory state for demo product API routes.
// Resets on hot-reload; good enough for demo purposes.

let counter = 0;
const PREFIX = "ETH";

export const demoSkuCounter = {
  peek:      () => `${PREFIX}-${String(counter + 1).padStart(4, "0")}`,
  increment: () => `${PREFIX}-${String(++counter).padStart(4, "0")}`,
};

export const demoProducts: Array<{
  id: string; sku: string; name: string; unit: string;
  pack_size: number; tenant_id: string; created_at: string;
}> = [];
