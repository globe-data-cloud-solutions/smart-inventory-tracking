/**
 * Client-side inventory state — tracks live balance adjustments and transfers
 * for the current browser session, scoped strictly to the active tenant.
 *
 * Balance semantics (per STOCKBALANCE.md §8.2):
 *
 *  On Hand   = base + RECEIVE_adj + inbound_RECEIVED_transfers
 *                   − outbound_IN_TRANSIT_transfers − outbound_RECEIVED_transfers
 *
 *  Available = On Hand − ISSUE_adj − outbound_reserved (DRAFT/PENDING_*/APPROVED/ADVISED)
 *
 *  Issued (display)    = ISSUE_adj + outbound_reserved qty
 *  In Transit (display) = outbound_IN_TRANSIT + inbound_IN_TRANSIT qty
 *  Received (display)  = RECEIVE_adj + inbound_RECEIVED qty
 *
 * Tenant isolation:
 *  Every write operation tags the record with the current `tenantSlug`.
 *  Every read operation filters to `currentTenantSlug` only.
 *  Call `setActiveTenant(slug)` from the [org] layout on every org change.
 */

import { create } from "zustand";

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
  issuedDate: string;
  status: TransferStatus;
}

// Statuses where an outbound transfer has physically left the source WH
const OUT_REDUCES_ON_HAND: TransferStatus[] = ["ISSUED", "IN_TRANSIT", "PARTIALLY_RECEIVED", "RECEIVED", "COMPLETED"];
// Statuses where an inbound transfer credits the destination WH On Hand
const IN_CREDITS_ON_HAND: TransferStatus[] = ["RECEIVED", "COMPLETED"];
// Statuses where an outbound transfer reduces Available (reserved but not yet gone)
const OUT_RESERVED: TransferStatus[] = ["DRAFT", "PENDING_REVIEW", "PENDING_APPROVAL", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM", "APPROVED", "ADVISED"];

interface InventoryStore {
  currentTenantSlug: string;
  adjustments: StockAdjustment[];
  transfers: TransferEntry[];

  // ── Tenant scope ──────────────────────────────────────────────────────────
  /** Must be called from the [org] layout whenever the active org changes. */
  setActiveTenant(slug: string): void;

  // ── Mutators ─────────────────────────────────────────────────────────────
  addReceive(productId: string, warehouseId: string, qty: number): void;
  addIssue(productId: string, warehouseId: string, qty: number): void;
  addTransfer(entry: Omit<TransferEntry, "tenantSlug">): void;
  /** No-op if transfer ID is not in the store (e.g. pre-seeded demo records). */
  updateTransferStatus(transferId: string, newStatus: TransferStatus): void;

  // ── Detail helpers (used by expandable cells) ─────────────────────────────
  getReceiveAdjs(productId: string, warehouseId: string): StockAdjustment[];
  getIssueAdjs(productId: string, warehouseId: string): StockAdjustment[];
  getOutboundReserved(productId: string, warehouseId: string): TransferEntry[];
  getOutboundInTransit(productId: string, warehouseId: string): TransferEntry[];
  getInboundInTransit(productId: string, warehouseId: string): TransferEntry[];
  getInboundReceived(productId: string, warehouseId: string): TransferEntry[];

  // ── Column totals ─────────────────────────────────────────────────────────
  getReceivedTotal(productId: string, warehouseId: string): number;
  getIssuedTotal(productId: string, warehouseId: string): number;
  getInTransitTotal(productId: string, warehouseId: string): number;

  // ── Core balances ─────────────────────────────────────────────────────────
  getOnHand(productId: string, warehouseId: string, baseStock: number): number;
  getAvailable(productId: string, warehouseId: string, baseStock: number): number;
}

export const useInventoryStore = create<InventoryStore>()((set, get) => ({
  currentTenantSlug: "",
  adjustments: [],
  transfers: [],

  setActiveTenant: (slug) => set({ currentTenantSlug: slug }),

  addReceive: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [
        ...s.adjustments,
        {
          id: crypto.randomUUID(), tenantSlug: s.currentTenantSlug,
          productId, warehouseId, qty, type: "RECEIVE", createdAt: new Date().toISOString(),
        },
      ],
    })),

  addIssue: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [
        ...s.adjustments,
        {
          id: crypto.randomUUID(), tenantSlug: s.currentTenantSlug,
          productId, warehouseId, qty, type: "ISSUE", createdAt: new Date().toISOString(),
        },
      ],
    })),

  addTransfer: (entry) =>
    set((s) => ({
      transfers: [
        ...s.transfers.filter((t) => t.id !== entry.id),
        { ...entry, tenantSlug: s.currentTenantSlug },
      ],
    })),

  updateTransferStatus: (transferId, newStatus) =>
    set((s) => ({
      transfers: s.transfers.map((t) => (t.id === transferId ? { ...t, status: newStatus } : t)),
    })),

  // ── Detail helpers — always scoped to currentTenantSlug ──────────────────

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

  // ── Totals ────────────────────────────────────────────────────────────────

  getReceivedTotal: (productId, warehouseId) => {
    const s = get();
    return (
      s.getReceiveAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0) +
      s.getInboundReceived(productId, warehouseId).reduce((n, t) => n + t.quantity, 0)
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
    return (
      s.getOutboundInTransit(productId, warehouseId).reduce((n, t) => n + t.quantity, 0) +
      s.getInboundInTransit(productId, warehouseId).reduce((n, t) => n + t.quantity, 0)
    );
  },

  // ── Core balances ─────────────────────────────────────────────────────────

  getOnHand: (productId, warehouseId, baseStock) => {
    const s = get();
    const receiveQty      = s.getReceiveAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0);
    const inboundReceived = s.getInboundReceived(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
    const outboundGone    = s.transfers
      .filter(
        (t) =>
          t.tenantSlug === s.currentTenantSlug &&
          t.productId === productId &&
          t.fromWarehouseId === warehouseId &&
          OUT_REDUCES_ON_HAND.includes(t.status)
      )
      .reduce((n, t) => n + t.quantity, 0);
    return baseStock + receiveQty + inboundReceived - outboundGone;
  },

  getAvailable: (productId, warehouseId, baseStock) => {
    const s        = get();
    const onHand   = s.getOnHand(productId, warehouseId, baseStock);
    const issueQty = s.getIssueAdjs(productId, warehouseId).reduce((n, a) => n + a.qty, 0);
    const reserved = s.getOutboundReserved(productId, warehouseId).reduce((n, t) => n + t.quantity, 0);
    return Math.max(0, onHand - issueQty - reserved);
  },
}));
