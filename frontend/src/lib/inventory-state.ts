/**
 * Client-side inventory state — persisted to localStorage so balances survive
 * browser refreshes. Scoped strictly to the active tenant via currentTenantSlug.
 *
 * WMS column layout (Option A — industry standard, per CLAUDE.md §17):
 *  On Hand        = base + RECEIVE_adj - ISSUE_adj
 *                       + inbound_RECEIVED/COMPLETED.quantity
 *                       + inbound_PARTIALLY_RECEIVED.receivedQuantity
 *                       - outbound_APPROVED/ADVISED/ISSUED/IN_TRANSIT/…/COMPLETED.quantity
 *                         (deduction at APPROVED — reservation converts to hard deduction)
 *
 *  Reserved       = outbound_DRAFT/PENDING_x.quantity
 *                   (ISSUE adjustments are direct On Hand deductions — never a reservation)
 *
 *  In Transit Out = outbound_ISSUED/IN_TRANSIT.quantity
 *                   (informational: stock left On Hand at APPROVED, now physically in transit)
 *
 *  In Transit In  = inbound_IN_TRANSIT.quantity
 *                   + inbound_PARTIALLY_RECEIVED.(quantity - receivedQuantity)
 *
 *  Available      = On Hand - Reserved
 *                   (inTransitOut NOT subtracted — On Hand already captures APPROVED deduction)
 *
 * Column trace (qty = 100, source base = 2000, destination base = 0):
 * ┌──────────────────────┬────────────┬──────────┬────────────────┬──────────────┬───────────┐
 * │ Stage                │ Src OnHand │ Reserved │ Src InTransOut │ Dst InTransIn│ Available │
 * ├──────────────────────┼────────────┼──────────┼────────────────┼──────────────┼───────────┤
 * │ PENDING_APPROVAL     │   2000     │   100    │       0        │      0       │   1900    │
 * │ APPROVED             │   1900     │     0    │       0        │      0       │   1900    │
 * │ ISSUED               │   1900     │     0    │     100        │      0       │   1900    │
 * │ IN_TRANSIT           │   1900     │     0    │     100        │    100       │   1900    │
 * │ RECEIVED src / dst   │   1900     │     0    │       0        │      0       │   1900    │
 * │                      │            │          │                │  dst: +100   │           │
 * └──────────────────────┴────────────┴──────────┴────────────────┴──────────────┴───────────┘
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { IS_GATEWAY_MODE } from "@/lib/api";

export type TransferStatus =
  | "DRAFT"
  | "PENDING_REVIEW"
  | "PENDING_APPROVAL"
  | "PENDING_SOURCE_CONFIRM"
  | "PENDING_DEST_CONFIRM"
  | "APPROVED"
  | "ADVISED"
  | "ISSUED"
  | "IN_TRANSIT"
  | "PARTIALLY_RECEIVED"
  | "RECEIVED"
  | "COMPLETED"
  | "REJECTED"
  | "CANCELLED";

export type AdjustmentType = "RECEIVE" | "ISSUE";

export interface StockAdjustment {
  id: string;
  tenantSlug: string;
  productId: string;
  warehouseId: string;
  qty: number;
  type: AdjustmentType;
  createdAt: string;
}

export interface TransferEntry {
  id: string;
  tenantSlug: string;
  ref: string;
  productId: string;
  fromWarehouseId: string;
  fromWarehouseName: string;
  toWarehouseId: string;
  toWarehouseName: string;
  quantity: number;
  /** Cumulative quantity received so far (for PARTIALLY_RECEIVED status). */
  receivedQuantity?: number;
  issuedDate: string;
  status: TransferStatus;
}

// On Hand at source reduces at APPROVED — the reservation converts to a hard deduction
// when the transfer is approved. All post-APPROVED statuses keep the deduction in place.
const OUT_REDUCES_ON_HAND: TransferStatus[] = [
  "APPROVED", "ADVISED",
  "ISSUED", "IN_TRANSIT", "PARTIALLY_RECEIVED",
  "RECEIVED", "COMPLETED",
];
const IN_CREDITS_ON_HAND: TransferStatus[] = ["RECEIVED", "COMPLETED"];
// Reserved = stock committed but not yet approved (soft hold, no On Hand change yet).
// DRAFT is excluded: a DRAFT transfer carries no stock commitment — it can be discarded
// at any time without consequence (CLAUDE.md §17: DRAFT → Reserved=0).
// APPROVED is excluded: at APPROVED the reservation converts to a deduction in On Hand.
const OUT_RESERVED: TransferStatus[] = [
  "PENDING_REVIEW", "PENDING_APPROVAL",
  "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM",
];

interface InventoryStore {
  currentTenantSlug: string;
  adjustments: StockAdjustment[];
  transfers: TransferEntry[];
  /**
   * Cumulative ISSUE quantities keyed by "tenantSlug:warehouseId:productId".
   * Nested-object spread in addIssue guarantees a new reference on every mutation,
   * which is what Zustand slice selectors need to fire re-renders.
   */
  issues: Record<string, number>;
  /**
   * Cumulative RECEIVE quantities keyed by "tenantSlug:warehouseId:productId".
   * Same immutability contract as issues.
   */
  receives: Record<string, number>;

  // ── Tenant scope ───────────────────────────────────────────────────────────
  setActiveTenant(slug: string): void;

  // ── Mutators ──────────────────────────────────────────────────────────────
  addReceive(productId: string, warehouseId: string, qty: number): void;
  addIssue(productId: string, warehouseId: string, qty: number): void;
  addTransfer(entry: Omit<TransferEntry, "tenantSlug">): void;
  updateTransferStatus(transferId: string, newStatus: TransferStatus): void;
  /** Record a partial receipt: adds additionalQty to the cumulative received amount. */
  partialReceive(transferId: string, additionalQty: number): void;

  // ── Lookup ─────────────────────────────────────────────────────────────────
  getTransferEntry(transferId: string): TransferEntry | undefined;

  // ── Detail helpers ─────────────────────────────────────────────────────────
  getReceiveAdjs(productId: string, warehouseId: string): StockAdjustment[];
  getIssueAdjs(productId: string, warehouseId: string): StockAdjustment[];
  getOutboundReserved(productId: string, warehouseId: string): TransferEntry[];
  getOutboundInTransit(productId: string, warehouseId: string): TransferEntry[];
  getInboundInTransit(productId: string, warehouseId: string): TransferEntry[];
  getInboundReceived(productId: string, warehouseId: string): TransferEntry[];
  /**
   * Inbound RECEIVED-but-not-yet-COMPLETED transfers — used for the Received
   * display column. COMPLETED transfers are excluded: their stock is already
   * permanently settled into On Hand so they no longer need tracking visibility.
   */
  getInboundJustReceived(productId: string, warehouseId: string): TransferEntry[];
  /** Inbound transfers in PARTIALLY_RECEIVED state (some qty still in transit). */
  getInboundPartial(productId: string, warehouseId: string): TransferEntry[];

  // ── Column totals (WMS Option A layout) ───────────────────────────────────
  /** Outbound DRAFT/PENDING transfers only. ISSUE adjustments reduce On Hand directly, not Reserved. */
  getReservedTotal(productId: string, warehouseId: string): number;
  /** Outbound transfers in ISSUED or IN_TRANSIT state. */
  getInTransitOutTotal(productId: string, warehouseId: string): number;
  /** Inbound IN_TRANSIT transfers + remaining qty from partial receives. */
  getInTransitInTotal(productId: string, warehouseId: string): number;

  // ── Core balances ──────────────────────────────────────────────────────────
  getOnHand(productId: string, warehouseId: string, baseStock: number): number;
  getAvailable(productId: string, warehouseId: string, baseStock: number): number;
}

export const useInventoryStore = create<InventoryStore>()(
  persist(
    (set, get) => ({
      currentTenantSlug: "",
      adjustments: [],
      transfers: [],
      issues: {},
      receives: {},

      setActiveTenant: (slug) => set({ currentTenantSlug: slug }),

      addReceive: (productId, warehouseId, qty) =>
        set((s) => {
          const key = `${s.currentTenantSlug}:${warehouseId}:${productId}`;
          return {
            adjustments: [
              ...s.adjustments,
              { id: crypto.randomUUID(), tenantSlug: s.currentTenantSlug, productId, warehouseId, qty, type: "RECEIVE" as const, createdAt: new Date().toISOString() },
            ],
            receives: { ...s.receives, [key]: (s.receives[key] ?? 0) + qty },
          };
        }),

      addIssue: (productId, warehouseId, qty) =>
        set((s) => {
          const key = `${s.currentTenantSlug}:${warehouseId}:${productId}`;
          return {
            adjustments: [
              ...s.adjustments,
              { id: crypto.randomUUID(), tenantSlug: s.currentTenantSlug, productId, warehouseId, qty, type: "ISSUE" as const, createdAt: new Date().toISOString() },
            ],
            issues: { ...s.issues, [key]: (s.issues[key] ?? 0) + qty },
          };
        }),

      addTransfer: (entry) =>
        set((s) => ({
          transfers: [...s.transfers.filter((t) => t.id !== entry.id), { ...entry, tenantSlug: s.currentTenantSlug }],
        })),

      updateTransferStatus: (transferId, newStatus) =>
        set((s) => ({
          transfers: s.transfers.map((t) => (t.id === transferId ? { ...t, status: newStatus } : t)),
        })),

      partialReceive: (transferId, additionalQty) =>
        set((s) => ({
          transfers: s.transfers.map((t) =>
            t.id === transferId
              ? { ...t, receivedQuantity: (t.receivedQuantity ?? 0) + additionalQty }
              : t
          ),
        })),

      getTransferEntry: (transferId) =>
        get().transfers.find((t) => t.id === transferId),

      // ── Detail helpers ────────────────────────────────────────────────────

      getReceiveAdjs: (productId, warehouseId) => {
        const { adjustments, currentTenantSlug } = get();
        return adjustments.filter(
          (a) => a.tenantSlug === currentTenantSlug && a.productId === productId && a.warehouseId === warehouseId && a.type === "RECEIVE"
        );
      },

      getIssueAdjs: (productId, warehouseId) => {
        const { adjustments, currentTenantSlug } = get();
        return adjustments.filter(
          (a) => a.tenantSlug === currentTenantSlug && a.productId === productId && a.warehouseId === warehouseId && a.type === "ISSUE"
        );
      },

      getOutboundReserved: (productId, warehouseId) => {
        const { transfers, currentTenantSlug } = get();
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.fromWarehouseId === warehouseId && OUT_RESERVED.includes(t.status)
        );
      },

      getOutboundInTransit: (productId, warehouseId) => {
        const { transfers, currentTenantSlug } = get();
        // ISSUED = stock has been picked/staged at source (deducted from on_hand) but not yet
        // received at destination. Show in In Transit (Out) so the stock doesn't appear to
        // vanish between ISSUED and IN_TRANSIT statuses.
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.fromWarehouseId === warehouseId && (t.status === "ISSUED" || t.status === "IN_TRANSIT")
        );
      },

      getInboundInTransit: (productId, warehouseId) => {
        const { transfers, currentTenantSlug } = get();
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.toWarehouseId === warehouseId && t.status === "IN_TRANSIT"
        );
      },

      getInboundReceived: (productId, warehouseId) => {
        const { transfers, currentTenantSlug } = get();
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.toWarehouseId === warehouseId && IN_CREDITS_ON_HAND.includes(t.status)
        );
      },

      getInboundJustReceived: (productId, warehouseId) => {
        const { transfers, currentTenantSlug } = get();
        // RECEIVED only — COMPLETED is excluded because it is fully settled into On Hand
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.toWarehouseId === warehouseId && t.status === "RECEIVED"
        );
      },

      getInboundPartial: (productId, warehouseId) => {
        const { transfers, currentTenantSlug } = get();
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.toWarehouseId === warehouseId && t.status === "PARTIALLY_RECEIVED"
        );
      },

      // ── Totals ────────────────────────────────────────────────────────────

      getReservedTotal: (productId, warehouseId) => {
        const s = get();
        return s.getOutboundReserved(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
      },

      getInTransitOutTotal: (productId, warehouseId) => {
        const s = get();
        return s.getOutboundInTransit(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
      },

      getInTransitInTotal: (productId, warehouseId) => {
        const s = get();
        const inbound = s.getInboundInTransit(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        const partial = s.getInboundPartial(productId, warehouseId)
          .reduce((n, t) => n + (t.quantity - (t.receivedQuantity ?? 0)), 0);
        return inbound + partial;
      },

      // ── Core balances ─────────────────────────────────────────────────────

      getOnHand: (productId, warehouseId, baseStock) => {
        // In gateway mode the backend is the single source of truth.
        // baseStock already reflects every committed transaction (RECEIVE, ISSUE,
        // TRANSFER_OUT, etc.) via inventory_balances.  Adding Zustand session-time
        // movements on top would double-count any operation the user performed
        // during this session (e.g. a receive that was already committed to the DB).
        if (IS_GATEWAY_MODE) return baseStock;

        const s   = get();
        const key = `${s.currentTenantSlug}:${warehouseId}:${productId}`;
        const receiveQty     = s.receives[key] ?? 0;
        const issueQty       = s.issues[key] ?? 0;
        const inboundFull    = s.getInboundReceived(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        const inboundPartial = s.getInboundPartial(productId, warehouseId).reduce((n, t) => n + (t.receivedQuantity ?? 0), 0);
        const outboundGone   = s.transfers
          .filter((t) => t.tenantSlug === s.currentTenantSlug && t.productId === productId && t.fromWarehouseId === warehouseId && OUT_REDUCES_ON_HAND.includes(t.status))
          .reduce((n, t) => n + t.quantity, 0);
        return baseStock + receiveQty + inboundFull + inboundPartial - outboundGone - issueQty;
      },

      getAvailable: (productId, warehouseId, baseStock) => {
        // In gateway mode, net_available is returned directly by the analytics API
        // (it already subtracts pending_out_qty).  Use baseStock as-is.
        if (IS_GATEWAY_MODE) return Math.max(0, baseStock);

        const s        = get();
        const onHand   = s.getOnHand(productId, warehouseId, baseStock);
        const reserved = s.getOutboundReserved(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        // issueQty already deducted inside getOnHand — do not subtract again.
        // On Hand already reflects the APPROVED deduction — do NOT subtract inTransitOut either.
        return Math.max(0, onHand - reserved);
      },
    }),
    {
      name: "smart-inventory-v2",
      // skipHydration: true prevents Next.js SSR hydration mismatch.
      // The layout calls useInventoryStore.persist.rehydrate() in a useEffect
      // so localStorage data is applied after the initial client render.
      skipHydration: true,
      // Only persist identity. Ephemeral state (issues, receives, transfers, adjustments)
      // is intentionally NOT persisted so a browser refresh always returns to the clean
      // demo baseline. Within a session, SPA navigation keeps the in-memory state intact.
      partialize: (state) => ({
        currentTenantSlug: state.currentTenantSlug,
      }),
    }
  )
);
