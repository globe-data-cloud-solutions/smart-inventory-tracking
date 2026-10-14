/** TanStack Query keys shared by the transfer detail views and the discrepancy screens. */

export function transferDetailKey(transferId: string): [string, string] {
  return ["transfer-detail", transferId];
}

/** GET …/transfers/discrepancies?status=OPEN — the Transfers page panel. */
export function openDiscrepanciesKey(): [string] {
  return ["transfer-discrepancies-open"];
}
