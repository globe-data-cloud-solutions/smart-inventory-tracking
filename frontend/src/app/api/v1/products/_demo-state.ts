type DemoProduct = {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; tenant_slug: string; created_at: string;
};

declare global {
  // eslint-disable-next-line no-var
  var _smartDemoProducts: DemoProduct[] | undefined;
  // eslint-disable-next-line no-var
  var _smartSkuCounter: number | undefined;
}

if (!globalThis._smartDemoProducts)  globalThis._smartDemoProducts  = [];
if (globalThis._smartSkuCounter === undefined) globalThis._smartSkuCounter = 0;

export const demoProducts: DemoProduct[] = globalThis._smartDemoProducts;

export const demoSkuCounter = {
  peekNumber: () => (globalThis._smartSkuCounter ?? 0) + 1,
  increment:  () => { globalThis._smartSkuCounter = (globalThis._smartSkuCounter ?? 0) + 1; return globalThis._smartSkuCounter; },
};

export function toOrgAbbr(orgSlug: string): string {
  return orgSlug.split("-").map((w) => (w[0] ?? "").toUpperCase()).join("").slice(0, 4);
}

export function buildSku(orgSlug: string, typeCode: string, unit: string, packSize: number, n: number): string {
  return `${toOrgAbbr(orgSlug)}-${typeCode.toUpperCase()}-${unit}${packSize}-${String(n).padStart(4, "0")}`;
}
