import { create } from "zustand";
import { persist } from "zustand/middleware";

export type AuditCategory = "TRANSFER" | "INVENTORY" | "ADJUSTMENT" | "SYSTEM";

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  tenantSlug: string;
  userEmail: string;
  userName: string;
  role: string;
  action: string;
  category: AuditCategory;
  resourceRef: string;
  resourceType: string;
  /** For TRANSFER: the product name. For INVENTORY: product name. */
  productName?: string;
  /** Formatted qty + unit, e.g. "1,455 Bag" */
  quantityStr?: string;
  /** Source facility / warehouse name. */
  fromWarehouse?: string;
  /** Destination facility / warehouse name. */
  toWarehouse?: string;
  /** Any additional free-form notes. */
  notes?: string;
  /** Source facility name, set when the actor's facility differs from the
   *  transfer's source facility (mirrors backend abac_context.acted_on_behalf_of). */
  actedOnBehalfOf?: string;
}

interface AuditLogStore {
  entries: AuditLogEntry[];
  log(entry: Omit<AuditLogEntry, "id" | "timestamp">): void;
  getForTenant(tenantSlug: string): AuditLogEntry[];
}

export const useAuditStore = create<AuditLogStore>()(
  persist(
    (set, get) => ({
      entries: [],

      log: (entry) =>
        set((s) => ({
          entries: [
            { ...entry, id: crypto.randomUUID(), timestamp: new Date().toISOString() },
            ...s.entries,
          ].slice(0, 1000),
        })),

      getForTenant: (tenantSlug) =>
        get().entries.filter((e) => e.tenantSlug === tenantSlug),
    }),
    {
      name: "smart-audit-log-v1",
      skipHydration: true,
      partialize: (state) => ({ entries: state.entries }),
    }
  )
);
