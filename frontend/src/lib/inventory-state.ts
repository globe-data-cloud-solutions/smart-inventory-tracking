/**
 * Client-side inventory state — tracks live balance adjustments and pending
 * in-transit transfers for the current session.
 *
 * Adjustment types:
 *   RECEIVE       — stock added via ReceiveStockPanel (increases On Hand)
 *   ISSUE         — stock dispatched via IssueStockPanel: sales, damage, etc. (reduces Available)
 *   TRANSFER_OUT  — stock shipped to another warehouse via NewTransferPanel (reduces On Hand)
 *
 * Balance semantics (per STOCKBALANCE.md §8.2):
 *   On Hand   = base + RECEIVE − TRANSFER_OUT   (physical stock present in building)
 *   Issued    = sum of ISSUE transactions        (dispatched to customers / written off)
 *   Available = On Hand − Issued                 (can be committed to new orders)
 *   Pending   = incoming in-transit transfers (tracked separately in pendingTransfers)
 */

import { create } from "zustand";

export type AdjustmentType = "RECEIVE" | "ISSUE" | "TRANSFER_OUT";

export interface StockAdjustment {
  id: string;
  productId: string;
  warehouseId: string;
  qty: number;
  type: AdjustmentType;
  createdAt: string;
}

export interface PendingTransfer {
  id: string;
  ref: string;
  productId: string;
  fromWarehouseId: string;
  fromWarehouseName: string;
  toWarehouseId: string;
  quantity: number;
  issuedDate: string;
}

interface InventoryStore {
  adjustments: StockAdjustment[];
  pendingTransfers: PendingTransfer[];

  /** Stock received from supplier, production, or donation */
  addReceive(productId: string, warehouseId: string, qty: number): void;
  /** Stock issued outbound: sales, internal use, damage, expiry */
  addIssue(productId: string, warehouseId: string, qty: number): void;
  /** Stock shipped to another warehouse (reduces On Hand on source) */
  addTransferOut(productId: string, warehouseId: string, qty: number): void;
  /** Add an in-transit transfer visible on the destination's Pending column */
  addPending(t: PendingTransfer): void;
  /** Transfer received — clears pending and credits On Hand on destination */
  completePending(transferId: string, toWarehouseId: string, productId: string, qty: number): void;

  // ── Derived getters ──────────────────────────────────────────────────────
  /** base + RECEIVE − TRANSFER_OUT = physical stock in this warehouse */
  getOnHand(productId: string, warehouseId: string, baseStock: number): number;
  /** Sum of outbound ISSUE transactions (sales / write-offs) */
  getIssued(productId: string, warehouseId: string): number;
  /** Sum of received RECEIVE transactions this session */
  getReceived(productId: string, warehouseId: string): number;
  /** On Hand − Issued = stock that can be committed to new orders */
  getAvailable(productId: string, warehouseId: string, baseStock: number): number;
  /** In-transit transfers incoming to this warehouse */
  getPending(productId: string, toWarehouseId: string): PendingTransfer[];
}

export const useInventoryStore = create<InventoryStore>()((set, get) => ({
  adjustments: [],
  pendingTransfers: [],

  addReceive: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId, qty, type: "RECEIVE", createdAt: new Date().toISOString() }],
    })),

  addIssue: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId, qty, type: "ISSUE", createdAt: new Date().toISOString() }],
    })),

  addTransferOut: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId, qty, type: "TRANSFER_OUT", createdAt: new Date().toISOString() }],
    })),

  addPending: (t) =>
    set((s) => ({
      pendingTransfers: [...s.pendingTransfers.filter((x) => x.id !== t.id), t],
    })),

  completePending: (transferId, toWarehouseId, productId, qty) =>
    set((s) => ({
      pendingTransfers: s.pendingTransfers.filter((t) => t.id !== transferId),
      adjustments: [...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId: toWarehouseId, qty, type: "RECEIVE", createdAt: new Date().toISOString() }],
    })),

  getOnHand: (productId, warehouseId, baseStock) => {
    const adjs = get().adjustments.filter(
      (a) => a.productId === productId && a.warehouseId === warehouseId
    );
    const inflow  = adjs.filter((a) => a.type === "RECEIVE").reduce((s, a) => s + a.qty, 0);
    const outflow = adjs.filter((a) => a.type === "TRANSFER_OUT").reduce((s, a) => s + a.qty, 0);
    return baseStock + inflow - outflow;
  },

  getIssued: (productId, warehouseId) =>
    get()
      .adjustments.filter((a) => a.productId === productId && a.warehouseId === warehouseId && a.type === "ISSUE")
      .reduce((s, a) => s + a.qty, 0),

  getReceived: (productId, warehouseId) =>
    get()
      .adjustments.filter((a) => a.productId === productId && a.warehouseId === warehouseId && a.type === "RECEIVE")
      .reduce((s, a) => s + a.qty, 0),

  getAvailable: (productId, warehouseId, baseStock) => {
    const onHand = get().getOnHand(productId, warehouseId, baseStock);
    const issued = get().getIssued(productId, warehouseId);
    return Math.max(0, onHand - issued);
  },

  getPending: (productId, toWarehouseId) =>
    get().pendingTransfers.filter(
      (t) => t.productId === productId && t.toWarehouseId === toWarehouseId
    ),
}));
