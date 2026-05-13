// Shared in-memory state for demo product API routes.
// Resets on hot-reload; acceptable for demo use.

let counter = 0;

export const demoSkuCounter = {
  peekNumber: () => counter + 1,
  increment:  () => ++counter,
};

export const demoProducts: Array<{
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; tenant_slug: string; created_at: string;
}> = [];

// Derive org abbreviation from slug: "addis-water" → "AW"
export function toOrgAbbr(orgSlug: string): string {
  return orgSlug
    .split("-")
    .map((w) => (w[0] ?? "").toUpperCase())
    .join("")
    .slice(0, 4);
}

// Build SKU from components: AW + WTR + KG + 4 + 1 → "AW-WTR-KG4-0001"
export function buildSku(orgSlug: string, typeCode: string, unit: string, packSize: number, n: number): string {
  const abbr = toOrgAbbr(orgSlug);
  return `${abbr}-${typeCode.toUpperCase()}-${unit}${packSize}-${String(n).padStart(4, "0")}`;
}
