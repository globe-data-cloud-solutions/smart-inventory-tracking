/**
 * Client-side inventory state — persisted to localStorage so balances survive
 * browser refreshes. Scoped strictly to the active tenant via currentTenantSlug.
 *
 * Balance semantics:
 *  On Hand   = base + RECEIVE_adj + inbound_RECEIVED/COMPLETED.quantity
 *                   + inbound_PARTIALLY_RECEIVED.receivedQuantity
 *                   - outbound_ISSUED/IN_TRANSIT/PARTIALLY_RECEIVED/RECEIVED/COMPLETED.quantity
 *
 *  Available = On Hand - ISSUE_adj - outbound_reserved
 *              (reserved = DRAFT/PENDING_x/APPROVED/ADVISED)
 *
 *  In Transit (display) =
 *    outbound_IN_TRANSIT.quantity
 *    + inbound_IN_TRANSIT.quantity
 *    + inbound_PARTIALLY_RECEIVED.(quantity - receivedQuantity)
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

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

const OUT_REDUCES_ON_HAND: TransferStatus[] = [
  "ISSUED", "IN_TRANSIT", "PARTIALLY_RECEIVED", "RECEIVED", "COMPLETED",
];
const IN_CREDITS_ON_HAND: TransferStatus[] = ["RECEIVED", "COMPLETED"];
const OUT_RESERVED: TransferStatus[] = [
  "DRAFT", "PENDING_REVIEW", "PENDING_APPROVAL",
  "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM",
  "APPROVED", "ADVISED",
];

interface InventoryStore {
  currentTenantSlug: string;
  adjustments: StockAdjustment[];
  transfers: TransferEntry[];

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

  // ── Column totals ──────────────────────────────────────────────────────────
  getReceivedTotal(productId: string, warehouseId: string): number;
  getIssuedTotal(productId: string, warehouseId: string): number;
  /** Includes remaining qty from partial receives. */
  getInTransitTotal(productId: string, warehouseId: string): number;

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

      setActiveTenant: (slug) => set({ currentTenantSlug: slug }),

      addReceive: (productId, warehouseId, qty) =>
        set((s) => ({
          adjustments: [
            ...s.adjustments,
            { id: crypto.randomUUID(), tenantSlug: s.currentTenantSlug, productId, warehouseId, qty, type: "RECEIVE", createdAt: new Date().toISOString() },
          ],
        })),

      addIssue: (productId, warehouseId, qty) =>
        set((s) => ({
          adjustments: [
            ...s.adjustments,
            { id: crypto.randomUUID(), tenantSlug: s.currentTenantSlug, productId, warehouseId, qty, type: "ISSUE", createdAt: new Date().toISOString() },
          ],
        })),

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
        return transfers.filter(
          (t) => t.tenantSlug === currentTenantSlug && t.productId === productId && t.fromWarehouseId === warehouseId && t.status === "IN_TRANSIT"
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

      getReceivedTotal: (productId, warehouseId) => {
        const s = get();
        return (
          s.getReceiveAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0) +
          // Use getInboundJustReceived (not getInboundReceived) so COMPLETED
          // transfers no longer appear in the Received display column — their
          // stock is permanently settled into On Hand.
          s.getInboundJustReceived(productId, warehouseId).reduce((n, t) => n + t.quantity, 0) +
          s.getInboundPartial(productId, warehouseId).reduce((n, t) => n + (t.receivedQuantity ?? 0), 0)
        );
      },

      getIssuedTotal: (productId, warehouseId) => {
        const s = get();
        return (
          s.getIssueAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0) +
          s.getOutboundReserved(productId, warehouseId).reduce((n, t) => n + t.quantity, 0)
        );
      },

      getInTransitTotal: (productId, warehouseId) => {
        const s = get();
        const outbound   = s.getOutboundInTransit(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        const inbound    = s.getInboundInTransit(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        // Remaining from partial receives (not yet fully received)
        const partial    = s.getInboundPartial(productId, warehouseId)
          .reduce((n, t) => n + (t.quantity - (t.receivedQuantity ?? 0)), 0);
        return outbound + inbound + partial;
      },

      // ── Core balances ─────────────────────────────────────────────────────

      getOnHand: (productId, warehouseId, baseStock) => {
        const s = get();
        const receiveQty      = s.getReceiveAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0);
        const inboundFull     = s.getInboundReceived(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        const inboundPartial  = s.getInboundPartial(productId, warehouseId).reduce((n, t) => n + (t.receivedQuantity ?? 0), 0);
        const outboundGone    = s.transfers
          .filter((t) => t.tenantSlug === s.currentTenantSlug && t.productId === productId && t.fromWarehouseId === warehouseId && OUT_REDUCES_ON_HAND.includes(t.status))
          .reduce((n, t) => n + t.quantity, 0);
        return baseStock + receiveQty + inboundFull + inboundPartial - outboundGone;
      },

      getAvailable: (productId, warehouseId, baseStock) => {
        const s        = get();
        const onHand   = s.getOnHand(productId, warehouseId, baseStock);
        const issueQty = s.getIssueAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0);
        const reserved = s.getOutboundReserved(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
        return Math.max(0, onHand - issueQty - reserved);
      },
    }),
    {
      name: "smart-inventory-v2",
      // skipHydration: true prevents Next.js SSR hydration mismatch.
      // The layout calls useInventoryStore.persist.rehydrate() in a useEffect
      // so localStorage data is applied after the initial client render.
      skipHydration: true,
      partialize: (state) => ({
        currentTenantSlug: state.currentTenantSlug,
        adjustments: state.adjustments,
        transfers: state.transfers,
      }),
    }
  )
);
