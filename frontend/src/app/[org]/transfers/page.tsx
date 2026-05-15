"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";
import { NewTransferPanel } from "@/components/features/transfers/NewTransferPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { api } from "@/lib/api";

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

const STATUS_STYLE: Record<TransferStatus, { bg: string; color: string }> = {
  DRAFT:                  { bg: "#F3F4F6", color: "#6B7280" },
  PENDING_REVIEW:         { bg: "#EDE9FE", color: "#5B21B6" },
  PENDING_APPROVAL:       { bg: "#DBEAFE", color: "#1E40AF" },
  PENDING_SOURCE_CONFIRM: { bg: "#FEF3C7", color: "#92400E" },
  PENDING_DEST_CONFIRM:   { bg: "#FEF3C7", color: "#92400E" },
  APPROVED:               { bg: "#D1FAE5", color: "#065F46" },
  ADVISED:                { bg: "#ECFDF5", color: "#059669" },
  ISSUED:                 { bg: "#D1FAE5", color: "#065F46" },
  IN_TRANSIT:             { bg: "#FEF3C7", color: "#92400E" },
  PARTIALLY_RECEIVED:     { bg: "#FEF9C3", color: "#713F12" },
  RECEIVED:               { bg: "#DCFCE7", color: "#166534" },
  COMPLETED:              { bg: "#F3F4F6", color: "#374151" },
  REJECTED:               { bg: "#FEE2E2", color: "#991B1B" },
  CANCELLED:              { bg: "#F3F4F6", color: "#9CA3AF" },
};

const TYPE_BADGE: Record<TransferType, { bg: string; color: string; label: string }> = {
  PULL:   { bg: "#DBEAFE", color: "#1E40AF", label: "PULL" },
  PUSH:   { bg: "#FEF3C7", color: "#92400E", label: "PUSH" },
  SISTER: { bg: "#EDE9FE", color: "#5B21B6", label: "SISTER" },
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

  // WM
  if (role === "WM") {
    if (type === "PULL") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:              [review, cancel],
        IN_TRANSIT:         [partRecv, markRecv],
        PARTIALLY_RECEIVED: [markRecv],
        RECEIVED:           [complete],
      };
      return map[status] ?? [];
    }
    if (type === "PUSH") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        IN_TRANSIT:         [partRecv, markRecv],
        PARTIALLY_RECEIVED: [markRecv],
        RECEIVED:           [complete],
      };
      return map[status] ?? [];
    }
    if (type === "SISTER") {
      // Context matters: destination WM vs source WM have different responsibilities
      const isDestWM = !!userWH && userWH === toWH;   // they requested stock
      const isSrcWM  = !!userWH && userWH === fromWH; // they supply stock

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
  const { updateTransferStatus, partialReceive, getTransferEntry } = useInventoryStore();
  const logAudit = useAuditStore((s) => s.log);
  const [transitioning, setTransitioning] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    id: string; next: TransferStatus; label: string; transfer: ApiTransfer;
    requiresQty?: boolean;
  } | null>(null);
  const [partialQtyInput, setPartialQtyInput] = useState("");
  const [partialQtyErr, setPartialQtyErr] = useState("");
  const [toast, setToast] = useState("");

  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view transfers.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant || !user) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const { data: allTransfers = [] } = useQuery<ApiTransfer[]>({
    queryKey: ["transfers", org],
    queryFn:  () => api.get<ApiTransfer[]>("/api/v1/transfers"),
    staleTime: 0,
    refetchInterval: 15000,
  });

  // Apply hierarchy + role scoping
  const scopedTransfers = scopeTransfers(allTransfers, user.role, user.warehouseId, tenant.warehouses);

  // Bug 4: terminal statuses drop to the Audit Log; only active transfers shown here
  const TERMINAL: TransferStatus[] = ["COMPLETED", "CANCELLED", "REJECTED"];
  const visibleTransfers = scopedTransfers.filter((t) => !TERMINAL.includes(t.status));
  const archivedCount = scopedTransfers.filter((t) => TERMINAL.includes(t.status)).length;

  async function doTransition(id: string, next: TransferStatus, partialQty?: number) {
    if (!isOnline) {
      setConfirmModal(null);
      setToast("Transfer status changes require an internet connection. Please reconnect and try again.");
      setTimeout(() => setToast(""), 5000);
      return;
    }
    const transfer = allTransfers.find((t) => t.id === id);
    setTransitioning(id);
    setConfirmModal(null);
    try {
      await api.patch(`/api/v1/transfers/${id}`, { next_status: next });
      await qc.invalidateQueries({ queryKey: ["transfers", org] });
      updateTransferStatus(id, next);
      if (next === "PARTIALLY_RECEIVED" && partialQty) {
        partialReceive(id, partialQty);
      }
      // Bug 3: record every transition in the audit log
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
      const msg = err instanceof Error ? err.message : "Transition failed.";
      setToast(msg.length <= 80 ? msg : "Transition failed — check permissions.");
      setTimeout(() => setToast(""), 5000);
    } finally {
      setTransitioning(null);
    }
  }

  const stats = {
    draft:      visibleTransfers.filter((t) => t.status === "DRAFT").length,
    inTransit:  visibleTransfers.filter((t) => ["IN_TRANSIT", "PARTIALLY_RECEIVED"].includes(t.status)).length,
    pending:    visibleTransfers.filter((t) => ["PENDING_REVIEW", "PENDING_APPROVAL", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM"].includes(t.status)).length,
    approved:   visibleTransfers.filter((t) => ["APPROVED", "ADVISED", "ISSUED"].includes(t.status)).length,
  };

  return (
    <div style={{ padding: "2rem" }}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 24, right: 24, zIndex: 200,
          background: "#1B4332", color: "#FCDD09", fontWeight: 700, fontSize: 13,
          padding: "10px 20px", borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
        }}>
          {toast}
        </div>
      )}

      {/* Confirm modal */}
      {confirmModal && (
        <>
          <div onClick={() => setConfirmModal(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 200 }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
            background: "#fff", borderRadius: 10, padding: "2rem", zIndex: 201,
            width: confirmModal.requiresQty ? 400 : 340, boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
          }}>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#111827", margin: "0 0 0.5rem" }}>
              {confirmModal.requiresQty ? "Partial Receive" : "Confirm Action"}
            </p>
            <p style={{ fontSize: 14, color: "#6B7280", margin: "0 0 1rem" }}>
              {confirmModal.label} — status will change to <strong>{confirmModal.next.replace(/_/g, " ")}</strong>.
            </p>

            {/* Bug 2: qty input for PARTIALLY_RECEIVED */}
            {confirmModal.requiresQty && (() => {
              const storeEntry   = getTransferEntry(confirmModal.id);
              const alreadyRecvd = storeEntry?.receivedQuantity ?? 0;
              const total        = confirmModal.transfer.quantity;
              const remaining    = total - alreadyRecvd;
              return (
                <div style={{ background: "#F9FAFB", borderRadius: 6, padding: "12px 14px", marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6B7280", marginBottom: 6 }}>
                    <span>Total quantity</span><strong style={{ color: "#111827" }}>{total.toLocaleString()}</strong>
                  </div>
                  {alreadyRecvd > 0 && (
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6B7280", marginBottom: 6 }}>
                      <span>Previously received</span><strong style={{ color: "#059669" }}>{alreadyRecvd.toLocaleString()}</strong>
                    </div>
                  )}
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6B7280", marginBottom: 10 }}>
                    <span>Still in transit</span><strong style={{ color: "#92400E" }}>{remaining.toLocaleString()}</strong>
                  </div>
                  <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    Quantity received this batch
                  </label>
                  <input
                    type="number" min="1" max={remaining}
                    value={partialQtyInput}
                    onChange={(e) => { setPartialQtyInput(e.target.value); setPartialQtyErr(""); }}
                    placeholder={`1 – ${remaining.toLocaleString()}`}
                    autoFocus
                    style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: `1px solid ${partialQtyErr ? "#DC2626" : "#D1D5DB"}`, borderRadius: 4, outline: "none", boxSizing: "border-box" as const }}
                  />
                  {partialQtyErr && <p style={{ fontSize: 11, color: "#DC2626", margin: "4px 0 0" }}>{partialQtyErr}</p>}
                </div>
              );
            })()}

            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={() => { setConfirmModal(null); setPartialQtyErr(""); }} style={{ flex: 1, padding: "9px", background: "#F3F4F6", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                Cancel
              </button>
              <button
                onClick={() => {
                  if (confirmModal.requiresQty) {
                    const storeEntry = getTransferEntry(confirmModal.id);
                    const remaining  = confirmModal.transfer.quantity - (storeEntry?.receivedQuantity ?? 0);
                    const qty        = parseFloat(partialQtyInput);
                    if (!qty || qty <= 0 || qty > remaining) {
                      setPartialQtyErr(`Enter a quantity between 1 and ${remaining.toLocaleString()}`);
                      return;
                    }
                    doTransition(confirmModal.id, confirmModal.next, qty);
                  } else {
                    doTransition(confirmModal.id, confirmModal.next);
                  }
                }}
                style={{ flex: 2, padding: "9px", background: "#1B4332", color: "#FCDD09", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 700, cursor: "pointer" }}
              >
                Confirm
              </button>
            </div>
          </div>
        </>
      )}

      {/* Header */}
      <div style={{ marginBottom: "1.5rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>Transfers</h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
            {tenant.name} · {visibleTransfers.length} active transfer{visibleTransfers.length !== 1 ? "s" : ""}{user.warehouseId && !["TA","SA","RM","LM"].includes(user.role) ? ` · ${user.warehouseName ?? "your warehouse"}` : ""}
            {archivedCount > 0 && (
              <span style={{ marginLeft: 10, fontSize: 11, color: "#9CA3AF" }}>
                {archivedCount} archived → <a href={`/${org}/audit-log`} style={{ color: "#1B4332", fontWeight: 600, textDecoration: "none" }}>Audit Log</a>
              </span>
            )}
          </p>
        </div>
        <NewTransferPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
      </div>

      {/* Summary chips */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1.5rem", flexWrap: "wrap" }}>
        {[
          { label: "Draft",      count: stats.draft,     bg: "#F3F4F6", color: "#374151" },
          { label: "Pending",    count: stats.pending,   bg: "#EDE9FE", color: "#5B21B6" },
          { label: "Approved",   count: stats.approved,  bg: "#D1FAE5", color: "#065F46" },
          { label: "In Transit", count: stats.inTransit, bg: "#FEF3C7", color: "#92400E" },
        ].map((s) => (
          <div key={s.label} style={{ background: s.bg, color: s.color, fontSize: 12, fontWeight: 700, padding: "4px 12px", borderRadius: 20 }}>
            {s.label}: {s.count}
          </div>
        ))}
      </div>

      {/* Table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                {COLS.map((h) => (
                  <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleTransfers.map((t, idx) => {
                const s    = STATUS_STYLE[t.status] ?? { bg: "#F3F4F6", color: "#6B7280" };
                const tb   = TYPE_BADGE[t.transfer_type] ?? { bg: "#F3F4F6", color: "#6B7280", label: t.transfer_type };
                const acts = getAvailableActions(user.role, t.transfer_type, t.status, user.warehouseId, t.from_warehouse_id, t.to_warehouse_id);
                const busy = transitioning === t.id;
                return (
                  <tr key={t.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "10px 12px" }}>
                      <Link href={`/${org}/transfers/${t.id}`} style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: tenant.color, textDecoration: "none" }}>
                        {t.ref} →
                      </Link>
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 3, background: tb.bg, color: tb.color, whiteSpace: "nowrap" }}>
                        {tb.label}
                      </span>
                    </td>
                    <td style={{ padding: "10px 12px", color: "#374151", fontSize: 13 }}>{t.from_warehouse_name}</td>
                    <td style={{ padding: "10px 12px", color: "#374151", fontSize: 13 }}>{t.to_warehouse_name}</td>
                    <td style={{ padding: "10px 12px", color: "#6B7280", fontSize: 13 }}>{t.product_name}</td>
                    <td style={{ padding: "10px 12px", fontWeight: 600, color: "#111827", fontSize: 13 }}>
                      {t.quantity.toLocaleString()}
                      {t.status === "PARTIALLY_RECEIVED" && (() => {
                        const e = getTransferEntry(t.id);
                        const rcvd = e?.receivedQuantity ?? 0;
                        return rcvd > 0 ? (
                          <span style={{ display: "block", fontSize: 10, fontWeight: 500, color: "#92400E" }}>
                            {rcvd.toLocaleString()} rcvd · {(t.quantity - rcvd).toLocaleString()} rem
                          </span>
                        ) : null;
                      })()}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3, background: s.bg, color: s.color, whiteSpace: "nowrap" }}>
                        {t.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td style={{ padding: "10px 12px", color: "#9CA3AF", fontSize: 12, whiteSpace: "nowrap" }}>
                      {new Date(t.created_at).toLocaleDateString()}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      {busy ? (
                        <span style={{ fontSize: 12, color: "#9CA3AF" }}>Updating…</span>
                      ) : acts.length > 0 ? (
                        <div style={{ display: "flex", gap: 6, flexWrap: "nowrap", alignItems: "center" }}>
                          {!isOnline && (
                            <span title="Offline — actions unavailable" style={{ fontSize: 11, color: "#9CA3AF" }}>offline</span>
                          )}
                          {acts.map((a) => (
                            <button
                              key={a.next}
                              disabled={!isOnline}
                              onClick={() => {
                                setPartialQtyInput("");
                                setPartialQtyErr("");
                                setConfirmModal({ id: t.id, next: a.next, label: a.label, transfer: t, requiresQty: a.requiresQty });
                              }}
                              style={{
                                fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 4,
                                border: `1px solid ${a.color}20`,
                                cursor: isOnline ? "pointer" : "not-allowed",
                                whiteSpace: "nowrap",
                                background: isOnline ? `${a.color}12` : "#F3F4F6",
                                color: isOnline ? a.color : "#9CA3AF",
                                opacity: isOnline ? 1 : 0.5,
                              }}
                            >
                              {a.label}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <span style={{ fontSize: 11, color: "#D1D5DB" }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {visibleTransfers.length === 0 && (
          <p style={{ padding: "2rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>No transfers yet. Click "+ New Transfer" to create one.</p>
        )}
      </div>
    </div>
  );
}
