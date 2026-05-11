/**
 * Client-side inventory state — tracks live balance adjustments and pending
 * in-transit transfers for the current session.
 *
 * Uses Zustand (in-memory, no SSR). State resets on full page reload.
 * In production this would be derived from the real inventory_transactions
 * ledger via the API.
 */

import { create } from "zustand";

export interface StockAdjustment {
  id: string;
  productId: string;
  warehouseId: string;
  qty: number;
  type: "RECEIVE" | "ISSUE";
  createdAt: string;
}

export interface PendingTransfer {
  /** Matches the transfer record id from the transfers API */
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

  addReceive(productId: string, warehouseId: string, qty: number): void;
  addIssue(productId: string, warehouseId: string, qty: number): void;
  addPending(t: PendingTransfer): void;
  completePending(transferId: string, toWarehouseId: string, productId: string, qty: number): void;

  getNetAdjustment(productId: string, warehouseId: string): number;
  getReceived(productId: string, warehouseId: string): number;
  getIssued(productId: string, warehouseId: string): number;
  getPending(productId: string, toWarehouseId: string): PendingTransfer[];
}

export const useInventoryStore = create<InventoryStore>()((set, get) => ({
  adjustments: [],
  pendingTransfers: [],

  addReceive: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [
        ...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId, qty, type: "RECEIVE", createdAt: new Date().toISOString() },
      ],
    })),

  addIssue: (productId, warehouseId, qty) =>
    set((s) => ({
      adjustments: [
        ...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId, qty, type: "ISSUE", createdAt: new Date().toISOString() },
      ],
    })),

  addPending: (t) =>
    set((s) => ({
      pendingTransfers: [...s.pendingTransfers.filter((x) => x.id !== t.id), t],
    })),

  completePending: (transferId, toWarehouseId, productId, qty) =>
    set((s) => ({
      pendingTransfers: s.pendingTransfers.filter((t) => t.id !== transferId),
      adjustments: [
        ...s.adjustments,
        { id: crypto.randomUUID(), productId, warehouseId: toWarehouseId, qty, type: "RECEIVE", createdAt: new Date().toISOString() },
      ],
    })),

  getNetAdjustment: (productId, warehouseId) =>
    get()
      .adjustments.filter((a) => a.productId === productId && a.warehouseId === warehouseId)
      .reduce((sum, a) => sum + (a.type === "RECEIVE" ? a.qty : -a.qty), 0),

  getReceived: (productId, warehouseId) =>
    get()
      .adjustments.filter((a) => a.productId === productId && a.warehouseId === warehouseId && a.type === "RECEIVE")
      .reduce((sum, a) => sum + a.qty, 0),

  getIssued: (productId, warehouseId) =>
    get()
      .adjustments.filter((a) => a.productId === productId && a.warehouseId === warehouseId && a.type === "ISSUE")
      .reduce((sum, a) => sum + a.qty, 0),

  getPending: (productId, toWarehouseId) =>
    get().pendingTransfers.filter((t) => t.productId === productId && t.toWarehouseId === toWarehouseId),
}));
