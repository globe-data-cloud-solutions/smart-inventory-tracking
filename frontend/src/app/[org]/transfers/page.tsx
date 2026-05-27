"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoProduct, type DemoWarehouse } from "@/lib/demo-data";
import { NewTransferPanel } from "@/components/features/transfers/NewTransferPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type TransferType = "PULL" | "PUSH" | "SISTER";

type TransferStatus =
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

interface ApiProduct {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; created_at: string;
  category?: string; on_hand?: number; reorder_point?: number; warehouse_id?: string | null;
}

interface ApiStockRow {
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  warehouse_type: string | null;
  current_stock: number;
}

interface RawApiTransferLine {
  product_id: string;
  product_name: string;
  sku: string;
  quantity: string;
  uom: string;
}

interface RawApiTransfer {
  transfer_id: string;
  transfer_type: TransferType;
  status: TransferStatus;
  from_warehouse_id: string;
  from_warehouse_name: string;
  to_warehouse_id: string;
  to_warehouse_name: string;
  lines: RawApiTransferLine[];
  created_by?: string;
  created_at: string;
  updated_at?: string;
}

interface ApiTransfer {
  id: string;
  ref: string;
  transfer_type: TransferType;
  product_id: string;
  product_name: string;
  from_warehouse_id: string;
  from_warehouse_name: string;
  to_warehouse_id: string;
  to_warehouse_name: string;
  quantity: number;
  notes: string;
  status: TransferStatus;
  created_at: string;
}

function normalizeTransfer(raw: RawApiTransfer): ApiTransfer {
  const line = raw.lines[0];
  return {
    id:                 raw.transfer_id,
    ref:                raw.transfer_id.slice(0, 8).toUpperCase(),
    transfer_type:      raw.transfer_type,
    product_id:         line?.product_id ?? "",
    product_name:       line?.product_name ?? "",
    from_warehouse_id:  raw.from_warehouse_id,
    from_warehouse_name: raw.from_warehouse_name,
    to_warehouse_id:    raw.to_warehouse_id,
    to_warehouse_name:  raw.to_warehouse_name,
    quantity:           parseFloat(line?.quantity ?? "0"),
    notes:              "",
    status:             raw.status,
    created_at:         raw.created_at,
  };
}

/**
 * Returns all descendant warehouse IDs for a given facility (breadth-first via parentId).
 * MWH nodes at the apex of the hierarchy have no declared children in the current demo
 * data, so this primarily handles RWH→WH→SUB_WH chains.
 */
function getAuthorityScope(warehouseId: string, warehouses: DemoWarehouse[]): string[] {
  const scope = new Set<string>([warehouseId]);
  function addDescendants(parentId: string) {
    for (const wh of warehouses) {
      if (wh.parentId === parentId && !scope.has(wh.id)) {
        scope.add(wh.id);
        addDescendants(wh.id);
      }
    }
  }
  addDescendants(warehouseId);
  return Array.from(scope);
}

/**
 * Filters the transfer list to only those the current user should see.
 *
 * Visibility rules (per CLAUDE.md §13 ABAC + IMTS hierarchy):
 *   TA / SA         → all transfers (platform / tenant admin)
 *   RM / LM / AU   → all transfers (no specific facility assignment)
 *   NM at MWH      → all transfers (apex of supply hierarchy)
 *   NM / WM at RWH → transfers involving that RWH and all its descendant WHs
 *   WM at WH/SUB_WH → only transfers where that WH is source or destination
 */
function scopeTransfers(
  transfers: ApiTransfer[],
  role: string,
  warehouseId: string | undefined,
  warehouses: DemoWarehouse[]
): ApiTransfer[] {
  // Roles without a specific facility see all transfers in the tenant
  if (["TA", "SA", "RM", "LM", "AU"].includes(role)) return transfers;
  if (!warehouseId) return transfers;

  // Every facility-bound user (WM, NM at specific facility) sees:
  //   own facility + all descendants in the parentId hierarchy
  // e.g. Harar MWH → [harar, diredawa, hawassa]
  //      Dire Dawa RWH → [diredawa, hawassa]
  //      Kombolcha WH  → [kombolcha]
  const scope = getAuthorityScope(warehouseId, warehouses);
  return transfers.filter(
    (t) => scope.includes(t.from_warehouse_id) || scope.includes(t.to_warehouse_id)
  );
}

interface Action {
  next: TransferStatus;
  label: string;
  color: string;
  requiresQty?: boolean; // true for PARTIALLY_RECEIVED — opens qty input
}

const STATUS_CLASS: Record<TransferStatus, string> = {
  DRAFT:                  "bg-gray-100  text-gray-500",
  PENDING_REVIEW:         "bg-violet-100 text-violet-800",
  PENDING_APPROVAL:       "bg-blue-100   text-blue-800",
  PENDING_SOURCE_CONFIRM: "bg-amber-100  text-amber-800",
  PENDING_DEST_CONFIRM:   "bg-amber-100  text-amber-800",
  APPROVED:               "bg-emerald-100 text-emerald-900",
  ADVISED:                "bg-teal-50    text-emerald-600",
  ISSUED:                 "bg-emerald-100 text-emerald-900",
  IN_TRANSIT:             "bg-amber-100  text-amber-800",
  PARTIALLY_RECEIVED:     "bg-yellow-50  text-yellow-900",
  RECEIVED:               "bg-green-100  text-green-800",
  COMPLETED:              "bg-gray-100   text-gray-700",
  REJECTED:               "bg-red-100    text-red-900",
  CANCELLED:              "bg-gray-100   text-gray-400",
};

const TYPE_CLASS: Record<TransferType, { cls: string; label: string }> = {
  PULL:   { cls: "bg-blue-100   text-blue-800",   label: "PULL"   },
  PUSH:   { cls: "bg-amber-100  text-amber-800",  label: "PUSH"   },
  SISTER: { cls: "bg-violet-100 text-violet-800", label: "SISTER" },
};

/**
 * Returns the action buttons available to this user for a specific transfer.
 *
 * userWH / fromWH / toWH are used for SISTER context-awareness:
 *   - Destination WM (userWH === toWH)  : submits the request + re-confirms after source agrees
 *   - Source WM      (userWH === fromWH): confirms they can supply + issues stock after approval
 */
function getAvailableActions(
  role: string,
  type: TransferType,
  status: TransferStatus,
  userWH?: string,
  fromWH?: string,
  toWH?: string,
): Action[] {
  const approve:    Action = { next: "APPROVED",               label: "Approve",              color: "#059669" };
  const reject:     Action = { next: "REJECTED",               label: "Reject",               color: "#991B1B" };
  const cancel:     Action = { next: "CANCELLED",              label: "Cancel",               color: "#991B1B" };
  const issue:      Action = { next: "ISSUED",                 label: "Issue",                color: "#065F46" };
  const dispatch:   Action = { next: "IN_TRANSIT",             label: "Dispatch",             color: "#92400E" };
  const advise:     Action = { next: "ADVISED",                label: "Advise",               color: "#059669" };
  const partRecv:   Action = { next: "PARTIALLY_RECEIVED",     label: "Partial Receive",      color: "#713F12", requiresQty: true };
  const markRecv:   Action = { next: "RECEIVED",               label: "Mark Received",        color: "#059669" };
  const complete:   Action = { next: "COMPLETED",              label: "Complete",             color: "#374151" };
  const review:     Action = { next: "PENDING_REVIEW",         label: "Submit for Review",    color: "#5B21B6" };
  const toApproval: Action = { next: "PENDING_APPROVAL",       label: "Send for Approval",    color: "#1E40AF" };
  // SISTER-specific labels: destination submits request; source confirms supply
  const submitReq:  Action = { next: "PENDING_SOURCE_CONFIRM", label: "Submit Request",       color: "#5B21B6" };
  const confirmSup: Action = { next: "PENDING_DEST_CONFIRM",   label: "Confirm Supply",       color: "#059669" };
  const confirmInt: Action = { next: "PENDING_APPROVAL",       label: "Confirm & Escalate",   color: "#1E40AF" };

  // TA and SA see all valid next statuses for the type
  if (role === "TA" || role === "SA") {
    if (type === "PULL") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:              [review, cancel],
        PENDING_REVIEW:     [toApproval, reject, cancel],
        PENDING_APPROVAL:   [approve, reject, cancel],
        APPROVED:           [issue, cancel],
        ISSUED:             [dispatch],
        IN_TRANSIT:         [partRecv, markRecv],
        PARTIALLY_RECEIVED: [markRecv],
        RECEIVED:           [complete],
      };
      return map[status] ?? [];
    }
    if (type === "PUSH") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:            [toApproval, cancel],
        PENDING_APPROVAL: [approve, reject, cancel],
        APPROVED:         [advise, issue, cancel],
        ADVISED:          [issue, cancel],
        ISSUED:           [dispatch],
        IN_TRANSIT:       [partRecv, markRecv],
        PARTIALLY_RECEIVED: [markRecv],
        RECEIVED:         [complete],
      };
      return map[status] ?? [];
    }
    if (type === "SISTER") {
      // TA/SA see the full machine — all steps in order
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:                  [submitReq, cancel],
        PENDING_SOURCE_CONFIRM: [confirmSup, reject, cancel],
        PENDING_DEST_CONFIRM:   [confirmInt, reject, cancel],
        PENDING_APPROVAL:       [approve, reject, cancel],
        APPROVED:               [issue, cancel],
        ISSUED:                 [dispatch],
        IN_TRANSIT:             [partRecv, markRecv],
        PARTIALLY_RECEIVED:     [markRecv],
        RECEIVED:               [complete],
      };
      return map[status] ?? [];
    }
    return [];
  }

  // WM — compare UUIDs case-insensitively: session warehouseId vs DB from/to_warehouse_id
  // may differ in casing depending on how the JWT was issued vs how Postgres serializes UUIDs.
  if (role === "WM") {
    const uWH = userWH?.toLowerCase();
    const isDestWM = !!uWH && uWH === toWH?.toLowerCase();
    const isSrcWM  = !!uWH && uWH === fromWH?.toLowerCase();

    if (type === "PULL") {
      if (isDestWM) {
        const map: Partial<Record<TransferStatus, Action[]>> = {
          DRAFT:              [review, cancel],
          IN_TRANSIT:         [partRecv, markRecv],
          PARTIALLY_RECEIVED: [markRecv],
          RECEIVED:           [complete],
        };
        return map[status] ?? [];
      }
      if (isSrcWM) {
        const map: Partial<Record<TransferStatus, Action[]>> = {
          APPROVED: [issue, cancel],
          ISSUED:   [dispatch],
        };
        return map[status] ?? [];
      }
      return [];
    }
    if (type === "PUSH") {
      if (isDestWM) {
        const map: Partial<Record<TransferStatus, Action[]>> = {
          IN_TRANSIT:         [partRecv, markRecv],
          PARTIALLY_RECEIVED: [markRecv],
          RECEIVED:           [complete],
        };
        return map[status] ?? [];
      }
      if (isSrcWM) {
        const map: Partial<Record<TransferStatus, Action[]>> = {
          APPROVED: [advise, issue, cancel],
          ADVISED:  [issue, cancel],
          ISSUED:   [dispatch],
        };
        return map[status] ?? [];
      }
      return [];
    }
    if (type === "SISTER") {
      if (isDestWM) {
        // Destination (requestor) WM: submits request, re-confirms intent, receives
        const map: Partial<Record<TransferStatus, Action[]>> = {
          DRAFT:                [submitReq, cancel],    // submit request to source
          PENDING_DEST_CONFIRM: [confirmInt, reject, cancel],  // confirm still want it
          IN_TRANSIT:           [partRecv, markRecv],
          PARTIALLY_RECEIVED:   [markRecv],
          RECEIVED:             [complete],
        };
        return map[status] ?? [];
      }
      if (isSrcWM) {
        // Source WM: confirms supply, then issues stock after approval
        const map: Partial<Record<TransferStatus, Action[]>> = {
          PENDING_SOURCE_CONFIRM: [confirmSup, reject, cancel],  // confirm can supply
          APPROVED:               [issue, cancel],
          ISSUED:                 [dispatch],
        };
        return map[status] ?? [];
      }
      // User is not directly involved (RM/LM view — handled elsewhere)
      return [];
    }
    return [];
  }

  // RM
  if (role === "RM") {
    if (type === "PULL") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        PENDING_REVIEW:   [toApproval, reject, cancel],
        PENDING_APPROVAL: [approve, reject, cancel],
      };
      return map[status] ?? [];
    }
    if (type === "PUSH") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:            [toApproval, cancel],
        PENDING_APPROVAL: [approve, reject, cancel],
        APPROVED:         [issue, cancel],
      };
      return map[status] ?? [];
    }
    if (type === "SISTER") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        PENDING_APPROVAL: [approve, reject, cancel],
      };
      return map[status] ?? [];
    }
    return [];
  }

  // NM
  if (role === "NM") {
    if (type === "PULL") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        PENDING_REVIEW:   [toApproval, reject, cancel],
        PENDING_APPROVAL: [approve, reject, cancel],
        APPROVED:         [issue, cancel],
        ISSUED:           [dispatch],
      };
      return map[status] ?? [];
    }
    if (type === "PUSH") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:            [toApproval, cancel],
        PENDING_APPROVAL: [approve, reject, cancel],
        APPROVED:         [advise, issue, cancel],
        ADVISED:          [issue, cancel],
        ISSUED:           [dispatch],
      };
      return map[status] ?? [];
    }
    if (type === "SISTER") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        PENDING_APPROVAL: [approve, reject, cancel],
      };
      return map[status] ?? [];
    }
    return [];
  }

  // LM
  if (role === "LM") {
    if (type === "PULL") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        APPROVED: [issue, cancel],
        ISSUED:   [dispatch],
      };
      return map[status] ?? [];
    }
    if (type === "PUSH") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        APPROVED: [advise, issue, cancel],
        ADVISED:  [issue, cancel],
        ISSUED:   [dispatch],
      };
      return map[status] ?? [];
    }
    if (type === "SISTER") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        APPROVED: [issue, cancel],
        ISSUED:   [dispatch],
      };
      return map[status] ?? [];
    }
    return [];
  }

  return [];
}

const COLS = ["Reference", "Type", "From", "To", "Product", "Qty", "Status", "Date", "Actions"];

export default function TransfersPage() {
  const { org } = useParams() as { org: string };
  const user = getSession();
  const qc   = useQueryClient();
  const { isOnline } = useOfflineSync();
  const { updateTransferStatus, partialReceive, getTransferEntry, addTransfer } = useInventoryStore();
  const logAudit = useAuditStore((s) => s.log);
  const [transitioning, setTransitioning] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting]   = useState(false);
  const [confirmModal, setConfirmModal] = useState<{
    id: string; next: TransferStatus; label: string; transfer: ApiTransfer;
    requiresQty?: boolean;
  } | null>(null);
  const [partialQtyInput, setPartialQtyInput] = useState("");
  const [partialQtyErr, setPartialQtyErr] = useState("");
  const [toast, setToast] = useState("");

  const { data: allTransfers = [], isLoading: transfersLoading } = useQuery<ApiTransfer[]>({
    queryKey: ["transfers", org],
    queryFn:  () =>
      api.get<RawApiTransfer[]>("/api/v1/inventory/transfers")
        .then((rows) => rows.map(normalizeTransfer)),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 15000,
  });

  // Fetch API-created products for the transfer panel product dropdown.
  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 30_000,
  });

  // Real warehouse data from the inventory analytics endpoint.
  // When this returns non-empty data, we are in gateway mode (real backend, real UUIDs).
  // In gateway mode, warehouse dropdowns must use real UUIDs — not the demo slug IDs
  // in tenant.warehouses — otherwise the backend rejects warehouse_id as invalid UUID.
  const { data: stockData = [] } = useQuery<ApiStockRow[]>({
    queryKey: ["analytics-stock", org],
    queryFn:  () => api.get<ApiStockRow[]>("/api/v1/inventory/analytics/stock"),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 30000,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("dashboard.tenants_heading")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!user) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const isGatewayMode = stockData.length > 0;

  // DB warehouse_type enum → frontend DemoWarehouse type mapping.
  // DB uses FACTORY|REGIONAL|RETAIL|SUBCENTER; frontend uses MWH|RWH|WH|SUB_WH.
  function mapWarehouseType(dbType: string | null): DemoWarehouse["type"] {
    const MAP: Record<string, DemoWarehouse["type"]> = {
      FACTORY: "MWH", REGIONAL: "RWH", RETAIL: "WH", SUBCENTER: "SUB_WH",
    };
    return MAP[dbType ?? ""] ?? "WH";
  }

  // Build a deduplicated warehouse list from analytics data (real UUIDs + types).
  // parentId is not available from analytics — hierarchy scoping falls back to "show all"
  // in the dropdowns, which is acceptable since ABAC enforcement is on the backend.
  const gatewayWarehouseMap = new Map<string, DemoWarehouse>();
  for (const row of stockData) {
    if (!gatewayWarehouseMap.has(row.warehouse_id)) {
      gatewayWarehouseMap.set(row.warehouse_id, {
        id:       row.warehouse_id,
        name:     row.warehouse_name,
        type:     mapWarehouseType(row.warehouse_type),
        parentId: null,
        location: "",
        manager:  "",
      });
    }
  }
  const gatewayWarehouses: DemoWarehouse[] = Array.from(gatewayWarehouseMap.values());

  // Build stockByProductId from analytics/stock data: productId → { warehouseId: currentStock }
  // This is the source of truth for balances in gateway mode — the products API does not
  // return on_hand or warehouse_id.
  const stockByProductId = new Map<string, Record<string, number>>();
  for (const row of stockData) {
    const existing = stockByProductId.get(row.product_id) ?? {};
    existing[row.warehouse_id] = Number(row.current_stock);
    stockByProductId.set(row.product_id, existing);
  }

  // Gateway mode: use only real API products (demo slugs are not valid UUIDs in the DB).
  // Demo mode: merge demo catalog + API products so the dropdown shows all products.
  const tenantProductIds = new Set((tenant?.products ?? []).map((p) => p.id));
  const mergedProducts: DemoProduct[] = isGatewayMode
    ? apiProducts.map((p) => ({
        id:            p.id,
        sku:           p.sku,
        name:          p.name,
        category:      p.category ?? p.type_code,
        unit:          p.unit,
        batchTracking: false,
        reorderPoint:  p.reorder_point ?? 0,
        stock:         stockByProductId.get(p.id) ?? {},
      }))
    : [
        ...(tenant?.products ?? []),
        ...apiProducts
          .filter((p) => !tenantProductIds.has(p.id))
          .map((p) => ({
            id:            p.id,
            sku:           p.sku,
            name:          p.name,
            category:      p.category ?? p.type_code,
            unit:          p.unit,
            batchTracking: false,
            reorderPoint:  p.reorder_point ?? 0,
            stock:         stockByProductId.get(p.id) ?? {},
          })),
      ];

  const effectiveWarehouses = isGatewayMode ? gatewayWarehouses : (tenant?.warehouses ?? []);

  // Apply hierarchy + role scoping
  const scopedTransfers = scopeTransfers(allTransfers, user.role, user.warehouseId, effectiveWarehouses);

  // Bug 4: terminal statuses drop to the Audit Log; only active transfers shown here
  const TERMINAL: TransferStatus[] = ["COMPLETED", "CANCELLED", "REJECTED"];
  const visibleTransfers = scopedTransfers.filter((t) => !TERMINAL.includes(t.status));
  const archivedCount = scopedTransfers.filter((t) => TERMINAL.includes(t.status)).length;

  async function doTransition(id: string, next: TransferStatus, partialQty?: number) {
    if (!user) return;
    if (isSubmitting) return;  // prevent double-submit
    if (!isOnline) {
      setConfirmModal(null);
      setToast("Transfer status changes require an internet connection. Please reconnect and try again.");
      setTimeout(() => setToast(""), 5000);
      return;
    }
    const transfer = allTransfers.find((t) => t.id === id);
    setIsSubmitting(true);
    setTransitioning(id);
    setConfirmModal(null);
    try {
      // ── Pre-fetch fresh status ──────────────────────────────────────────────
      // The TanStack Query cache can be up to 15 s stale. Another user may have
      // advanced the transfer since the action button was rendered, which would
      // send the wrong next_status and receive a 422. Fetching the single transfer
      // before the PATCH lets us detect this early and show a helpful message.
      //
      // Validation: compare fresh.status vs cached status only (status-equality
      // check). Re-running getAvailableActions() with fresh warehouse IDs was
      // causing false negatives when the session UUID and DB UUID differed in
      // case, incorrectly blocking the Issue (APPROVED → ISSUED) transition.
      interface FreshTransfer {
        transfer_id: string;
        transfer_type: TransferType;
        status: TransferStatus;
        from_warehouse_id: string;
        to_warehouse_id: string;
        created_at: string;
      }
      let freshStatus: TransferStatus = transfer?.status ?? next;
      try {
        const fresh = await api.get<FreshTransfer>(`/api/v1/inventory/transfers/${id}`);
        freshStatus = fresh.status;
        console.log("[doTransition] pre-fetch", { id, next, freshStatus: fresh.status, cachedStatus: transfer?.status });

        // Case-insensitive comparison — DB may return different casing than the cached value
        if (fresh.status.toUpperCase() !== (transfer?.status ?? "").toUpperCase()) {
          // Status changed since the button was shown — abort and let user retry
          await qc.invalidateQueries({ queryKey: ["transfers", org] });
          setToast(`Status changed to ${freshStatus.replace(/_/g, " ")} — list refreshed. Please try again.`);
          setTimeout(() => setToast(""), 5000);
          return;
        }
      } catch (prefetchErr) {
        // GET failed (network issue or 4xx) — let the PATCH proceed and handle any error below
        console.warn("[doTransition] pre-fetch GET failed:", prefetchErr);
      }
      // ───────────────────────────────────────────────────────────────────────

      console.log("[doTransition] sending PATCH:", { id, next_status: next, cachedStatus: transfer?.status });
      await api.patch(`/api/v1/inventory/transfers/${id}`, { next_status: next });

      // FIX 4: Optimistic update — reflect new status in the table immediately,
      // before the background refetch arrives.
      qc.setQueryData<ApiTransfer[]>(
        ["transfers", org],
        (old) => old?.map((t) => (t.id === id ? { ...t, status: next } : t)),
      );
      await qc.invalidateQueries({ queryKey: ["transfers", org] });
      // Refresh inventory balances immediately so On Hand / Available on the
      // Inventory page reflect the new ledger state without waiting for the 30 s poll.
      void qc.invalidateQueries({ queryKey: ["inventory-stock", org] });

      if (transfer && !getTransferEntry(id)) {
        addTransfer({
          id:                transfer.id,
          ref:               transfer.ref,
          productId:         transfer.product_id,
          fromWarehouseId:   transfer.from_warehouse_id,
          fromWarehouseName: transfer.from_warehouse_name,
          toWarehouseId:     transfer.to_warehouse_id,
          toWarehouseName:   transfer.to_warehouse_name,
          quantity:          transfer.quantity,
          issuedDate:        transfer.created_at,
          status:            transfer.status,
        });
      }
      updateTransferStatus(id, next);
      if (next === "PARTIALLY_RECEIVED" && partialQty) {
        partialReceive(id, partialQty);
      }
      logAudit({
        tenantSlug:    org,
        userEmail:     user.email,
        userName:      user.name,
        role:          user.role,
        action:        `transfer:${next}`,
        category:      "TRANSFER",
        resourceRef:   transfer?.ref ?? id,
        resourceType:  "TransferOrder",
        productName:   transfer?.product_name,
        quantityStr:   transfer ? `${transfer.quantity.toLocaleString()} ${transfer.product_name ? "units" : ""}` : undefined,
        fromWarehouse: transfer?.from_warehouse_name,
        toWarehouse:   transfer?.to_warehouse_name,
        notes:         partialQty ? `Batch received: ${partialQty.toLocaleString()} units` : undefined,
      });
      setToast(`Status updated to ${next.replace(/_/g, " ")}`);
      setTimeout(() => setToast(""), 3000);
    } catch (err: unknown) {
      const apiErr = err as { status?: number; message?: string; code?: string };
      const is422  = apiErr.status === 422;
      const code   = apiErr.code ?? "";
      const msg    = apiErr.message ?? "Transition failed.";
      // Log full error so browser console shows the exact backend code + message
      console.error("[doTransition] transition failed:", { id, next, status: apiErr.status, code, message: msg, raw: err });
      const toastMsg = is422
        ? `Invalid transition${code ? ` (${code})` : ""} — refreshing status…`
        : (msg.length <= 80 ? msg : "Transition failed — check permissions.");
      setToast(toastMsg);
      setTimeout(() => setToast(""), 5000);
      // Always refresh on error so the UI reflects the actual backend state
      void qc.invalidateQueries({ queryKey: ["transfers", org] });
    } finally {
      setTransitioning(null);
      setIsSubmitting(false);
    }
  }

  const stats = {
    draft:      visibleTransfers.filter((t) => t.status === "DRAFT").length,
    inTransit:  visibleTransfers.filter((t) => ["IN_TRANSIT", "PARTIALLY_RECEIVED"].includes(t.status)).length,
    pending:    visibleTransfers.filter((t) => ["PENDING_REVIEW", "PENDING_APPROVAL", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM"].includes(t.status)).length,
    approved:   visibleTransfers.filter((t) => ["APPROVED", "ADVISED", "ISSUED"].includes(t.status)).length,
  };

  return (
    <div className="p-8">
      {toast && (
        <div className="fixed bottom-6 right-6 z-[200] bg-eth-forest text-eth-gold font-bold text-sm px-5 py-2.5 rounded-md shadow-xl">
          {toast}
        </div>
      )}

      {confirmModal && (
        <>
          <div onClick={() => setConfirmModal(null)} className="fixed inset-0 bg-black/40 z-[200]" />
          <div className={`fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg p-8 z-[201] shadow-2xl ${confirmModal.requiresQty ? "w-[400px]" : "w-[340px]"}`}>
            <p className="font-bold text-base text-gray-900 mb-2">
              {confirmModal.requiresQty ? t("transfers.partial_receive") : t("transfers.confirm_action")}
            </p>
            <p className="text-sm text-gray-500 mb-4">
              {confirmModal.label} — {t("transfers.status_will_change")} <strong>{confirmModal.next.replace(/_/g, " ")}</strong>.
            </p>

            {confirmModal.requiresQty && (() => {
              const storeEntry   = getTransferEntry(confirmModal.id);
              const alreadyRecvd = storeEntry?.receivedQuantity ?? 0;
              const total        = confirmModal.transfer.quantity;
              const remaining    = total - alreadyRecvd;
              return (
                <div className="bg-gray-50 rounded-md px-3.5 py-3 mb-4">
                  <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                    <span>{t("transfers.total_qty")}</span><strong className="text-gray-900">{total.toLocaleString()}</strong>
                  </div>
                  {alreadyRecvd > 0 && (
                    <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                      <span>{t("transfers.prev_received")}</span><strong className="text-emerald-600">{alreadyRecvd.toLocaleString()}</strong>
                    </div>
                  )}
                  <div className="flex justify-between text-xs text-gray-500 mb-2.5">
                    <span>{t("transfers.still_in_transit")}</span><strong className="text-amber-800">{remaining.toLocaleString()}</strong>
                  </div>
                  <label className="block text-[11px] font-bold uppercase tracking-wide text-gray-700 mb-1">
                    {t("transfers.qty_this_batch")}
                  </label>
                  <input
                    type="number" min="1" max={remaining}
                    value={partialQtyInput}
                    onChange={(e) => { setPartialQtyInput(e.target.value); setPartialQtyErr(""); }}
                    placeholder={`1 – ${remaining.toLocaleString()}`}
                    autoFocus
                    className={`w-full px-2.5 py-2 text-sm rounded border outline-none ${partialQtyErr ? "border-red-600" : "border-gray-300"}`}
                  />
                  {partialQtyErr && <p className="text-[11px] text-red-600 mt-1">{partialQtyErr}</p>}
                </div>
              );
            })()}

            <div className="flex gap-2.5">
              <button onClick={() => { setConfirmModal(null); setPartialQtyErr(""); }} className="flex-1 py-2.5 bg-gray-100 border-0 rounded-md text-sm font-semibold cursor-pointer">
                {t("common.cancel")}
              </button>
              <button
                disabled={isSubmitting}
                onClick={() => {
                  if (confirmModal.requiresQty) {
                    const storeEntry = getTransferEntry(confirmModal.id);
                    const remaining  = confirmModal.transfer.quantity - (storeEntry?.receivedQuantity ?? 0);
                    const qty        = parseFloat(partialQtyInput);
                    if (!qty || qty <= 0 || qty > remaining) { setPartialQtyErr(`Enter a quantity between 1 and ${remaining.toLocaleString()}`); return; }
                    void doTransition(confirmModal.id, confirmModal.next, qty);
                  } else {
                    void doTransition(confirmModal.id, confirmModal.next);
                  }
                }}
                className="flex-[2] py-2.5 bg-eth-forest text-eth-gold border-0 rounded-md text-sm font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? t("common.loading") : t("common.confirm")}
              </button>
            </div>
          </div>
        </>
      )}

      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("nav.inventory")} — {t("transfers.transfers_heading")}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {tenant?.name ?? org} · {visibleTransfers.length} {t("transfers.active_label")}{user.warehouseId && !["TA","SA","RM","LM"].includes(user.role) ? ` · ${user.warehouseName ?? effectiveWarehouses.find((w) => w.id === user.warehouseId)?.name ?? t("transfers.your_warehouse")}` : ""}
            {archivedCount > 0 && (
              <span className="ml-2.5 text-[11px] text-gray-400">
                {archivedCount} {t("transfers.archived")} → <a href={`/${org}/audit-log`} className="text-eth-forest font-semibold no-underline">{t("audit.title")}</a>
              </span>
            )}
          </p>
        </div>
        <NewTransferPanel products={mergedProducts} warehouses={effectiveWarehouses} orgSlug={org} />
      </div>

      <div className="flex gap-2.5 mb-6 flex-wrap">
        {[
          { label: t("status.DRAFT"),      count: stats.draft,     cls: "bg-gray-100   text-gray-700"    },
          { label: t("transfers.pending"),  count: stats.pending,   cls: "bg-violet-100 text-violet-800"  },
          { label: t("status.APPROVED"),    count: stats.approved,  cls: "bg-emerald-100 text-emerald-900" },
          { label: t("status.IN_TRANSIT"),  count: stats.inTransit, cls: "bg-amber-100  text-amber-800"   },
        ].map((s) => (
          <div key={s.label} className={`text-xs font-bold px-3 py-1 rounded-full ${s.cls}`}>
            {s.label}: {s.count}
          </div>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {COLS.map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {transfersLoading && Array.from({ length: 4 }).map((_, i) => (
                <tr key={`skel-${i}`} className={`border-b border-gray-100 ${i % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  {COLS.map((c) => (
                    <td key={c} className="px-3 py-3">
                      <div className="h-3 rounded bg-gray-200 animate-pulse" style={{ width: `${55 + (i * 13 + c.length * 7) % 35}%` }} />
                    </td>
                  ))}
                </tr>
              ))}
              {!transfersLoading && visibleTransfers.map((txn, idx) => {
                const sCls = STATUS_CLASS[txn.status] ?? "bg-gray-100 text-gray-500";
                const tb   = TYPE_CLASS[txn.transfer_type] ?? { cls: "bg-gray-100 text-gray-500", label: txn.transfer_type };
                const acts = getAvailableActions(user.role, txn.transfer_type, txn.status, user.warehouseId, txn.from_warehouse_id, txn.to_warehouse_id);
                const busy = transitioning === txn.id;
                return (
                  <tr key={txn.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-3 py-2.5">
                      <Link href={`/${org}/transfers/${txn.id}`} className="font-mono text-xs font-semibold no-underline" style={{ color: tenant?.color ?? "#1B4332" }}>
                        {txn.ref} →
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${tb.cls}`}>{tb.label}</span>
                    </td>
                    <td className="px-3 py-2.5 text-gray-700 text-sm">{txn.from_warehouse_name}</td>
                    <td className="px-3 py-2.5 text-gray-700 text-sm">{txn.to_warehouse_name}</td>
                    <td className="px-3 py-2.5 text-gray-500 text-sm">{txn.product_name}</td>
                    <td className="px-3 py-2.5 font-semibold text-gray-900 text-sm">
                      {Number(txn.quantity ?? 0).toLocaleString()}
                      {txn.status === "PARTIALLY_RECEIVED" && (() => {
                        const e = getTransferEntry(txn.id); const rcvd = e?.receivedQuantity ?? 0;
                        return rcvd > 0 ? <span className="block text-[10px] font-medium text-amber-800">{rcvd.toLocaleString()} rcvd · {(Number(txn.quantity ?? 0) - rcvd).toLocaleString()} rem</span> : null;
                      })()}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[11px] font-bold px-2 py-0.5 rounded whitespace-nowrap ${sCls}`}>
                        {txn.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                      {new Date(txn.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2.5">
                      {busy ? (
                        <span className="text-xs text-gray-400">{t("common.loading")}</span>
                      ) : acts.length > 0 ? (
                        <div className="flex gap-1.5 flex-nowrap items-center">
                          {!isOnline && <span title={t("errors.OFFLINE")} className="text-[11px] text-gray-400">offline</span>}
                          {acts.map((a) => (
                            <button
                              key={a.next}
                              disabled={!isOnline}
                              onClick={() => { setPartialQtyInput(""); setPartialQtyErr(""); setConfirmModal({ id: txn.id, next: a.next, label: a.label, transfer: txn, requiresQty: a.requiresQty }); }}
                              className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
                              /* action button colors are per-action (a.color) — dynamic, must stay as style */
                              style={{
                                borderColor: `${a.color}30`,
                                cursor:      isOnline ? "pointer" : "not-allowed",
                                background:  isOnline ? `${a.color}15` : "#F3F4F6",
                                color:       isOnline ? a.color : "#9CA3AF",
                                opacity:     isOnline ? 1 : 0.5,
                              }}
                            >
                              {a.label}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <span className="text-[11px] text-gray-200">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!transfersLoading && visibleTransfers.length === 0 && (
          <p className="p-8 text-center text-gray-400 text-sm">{t("common.no_data")}</p>
        )}
      </div>
    </div>
  );
}
