/** TanStack Query keys shared by the transfer detail views and the discrepancy screens. */

export function transferDetailKey(transferId: string): [string, string] {
  return ["transfer-detail", transferId];
}

/** GET /tenants/{id}/transfer-types — same key the Add Product panel and Org Setup use. */
export function transferTypesKey(tenantId: string): [string, string] {
  return ["transfer-types", tenantId];
}

/** GET …/transfers/discrepancies?status=OPEN — the Transfers page panel. */
export function openDiscrepanciesKey(): [string] {
  return ["transfer-discrepancies-open"];
}
