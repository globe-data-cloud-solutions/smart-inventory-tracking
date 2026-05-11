"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { NewTransferPanel } from "@/components/features/transfers/NewTransferPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { api } from "@/lib/api";

type TransferStatus =
  | "DRAFT" | "SUBMITTED" | "APPROVED" | "IN_TRANSIT" | "RECEIVED" | "CLOSED" | "REJECTED" | "CANCELLED";

interface ApiTransfer {
  id: string; ref: string;
  product_id: string; product_name: string;
  from_warehouse_name: string; to_warehouse_id: string; to_warehouse_name: string;
  quantity: number; notes: string; status: TransferStatus; created_at: string;
}

const STATUS_STYLE: Record<TransferStatus, { bg: string; color: string }> = {
  DRAFT:      { bg: "#F3F4F6", color: "#6B7280" },
  SUBMITTED:  { bg: "#DBEAFE", color: "#1E40AF" },
  APPROVED:   { bg: "#D1FAE5", color: "#065F46" },
  IN_TRANSIT: { bg: "#FEF3C7", color: "#92400E" },
  RECEIVED:   { bg: "#DCFCE7", color: "#166534" },
  CLOSED:     { bg: "#F3F4F6", color: "#374151" },
  REJECTED:   { bg: "#FEE2E2", color: "#991B1B" },
  CANCELLED:  { bg: "#F3F4F6", color: "#9CA3AF" },
};

// Which roles can trigger which transitions
const ROLE_TRANSITIONS: Record<string, Partial<Record<TransferStatus, { next: TransferStatus; label: string; color: string }[]>>> = {
  WM: {
    DRAFT:      [{ next: "SUBMITTED", label: "Submit",   color: "#1E40AF" }, { next: "CANCELLED", label: "Cancel", color: "#991B1B" }],
    IN_TRANSIT: [{ next: "RECEIVED",  label: "Mark Received", color: "#059669" }],
  },
  LM: {
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch", color: "#92400E" }],
    DRAFT:      [{ next: "SUBMITTED", label: "Submit",   color: "#1E40AF" }],
    IN_TRANSIT: [{ next: "RECEIVED",  label: "Mark Received", color: "#059669" }],
  },
  RM: {
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve", color: "#059669" }, { next: "REJECTED", label: "Reject", color: "#991B1B" }],
    APPROVED:   [{ next: "CANCELLED",  label: "Cancel",  color: "#991B1B" }],
  },
  NM: {
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve", color: "#059669" }, { next: "REJECTED", label: "Reject", color: "#991B1B" }],
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch", color: "#92400E" }, { next: "CANCELLED", label: "Cancel", color: "#991B1B" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark Received", color: "#059669" }],
  },
  TA: {
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve", color: "#059669" }, { next: "REJECTED", label: "Reject", color: "#991B1B" }],
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch", color: "#92400E" }, { next: "CANCELLED", label: "Cancel", color: "#991B1B" }],
    DRAFT:      [{ next: "SUBMITTED",  label: "Submit",  color: "#1E40AF" }, { next: "CANCELLED", label: "Cancel", color: "#991B1B" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark Received", color: "#059669" }],
  },
  SA: {
    DRAFT:      [{ next: "SUBMITTED",  label: "Submit",  color: "#1E40AF" }, { next: "CANCELLED", label: "Cancel", color: "#991B1B" }],
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve", color: "#059669" }, { next: "REJECTED", label: "Reject", color: "#991B1B" }],
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch", color: "#92400E" }, { next: "CANCELLED", label: "Cancel", color: "#991B1B" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark Received", color: "#059669" }],
    RECEIVED:   [{ next: "CLOSED",     label: "Close",  color: "#374151" }],
  },
};

// DEMO_TRANSFERS now live in _demo-state.ts and are fetched via GET /api/v1/transfers

const COLS = ["Reference", "From", "To", "Product", "Qty", "Status", "Date", "Actions"];

export default function TransfersPage() {
  const { org } = useParams() as { org: string };
  const user = getSession();
  const qc   = useQueryClient();
  const { isOnline } = useOfflineSync();
  const completePending = useInventoryStore((s) => s.completePending);
  const [transitioning, setTransitioning] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{ id: string; next: TransferStatus; label: string; transfer?: ApiTransfer } | null>(null);
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
  const roleActions = ROLE_TRANSITIONS[user.role] ?? {};

  async function doTransition(id: string, next: TransferStatus, transfer?: ApiTransfer) {
    // Transfer status changes require server-side approval chain — must not be queued offline
    if (!isOnline) {
      setConfirmModal(null);
      setToast("Transfer status changes require an internet connection. Please reconnect and try again.");
      setTimeout(() => setToast(""), 5000);
      return;
    }
    setTransitioning(id);
    setConfirmModal(null);
    try {
      await api.patch(`/api/v1/transfers/${id}`, { next_status: next });
      await qc.invalidateQueries({ queryKey: ["transfers", org] });
      // When a transfer is received, clear pending and credit destination warehouse
      if (next === "RECEIVED" && transfer) {
        completePending(id, transfer.to_warehouse_id, transfer.product_id, transfer.quantity);
      }
      setToast(`Status updated to ${next}`);
      setTimeout(() => setToast(""), 3000);
    } catch {
      setToast("Transition failed — check permissions.");
      setTimeout(() => setToast(""), 4000);
    } finally {
      setTransitioning(null);
    }
  }

  const stats = {
    draft:     allTransfers.filter((t) => t.status === "DRAFT").length,
    inTransit: allTransfers.filter((t) => t.status === "IN_TRANSIT").length,
    pending:   allTransfers.filter((t) => ["SUBMITTED", "APPROVED"].includes(t.status)).length,
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
            width: 340, boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
          }}>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#111827", margin: "0 0 0.5rem" }}>Confirm Action</p>
            <p style={{ fontSize: 14, color: "#6B7280", margin: "0 0 1.5rem" }}>
              {confirmModal.label} this transfer? Status will change to <strong>{confirmModal.next}</strong>.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={() => setConfirmModal(null)} style={{ flex: 1, padding: "9px", background: "#F3F4F6", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                Cancel
              </button>
              <button
                onClick={() => doTransition(confirmModal.id, confirmModal.next, confirmModal.transfer)}
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
            {tenant.name} · {allTransfers.length} transfer orders
          </p>
        </div>
        <NewTransferPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
      </div>

      {/* Summary chips */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1.5rem", flexWrap: "wrap" }}>
        {[
          { label: "Draft",      count: stats.draft,     bg: "#F3F4F6", color: "#374151" },
          { label: "In Transit", count: stats.inTransit, bg: "#FEF3C7", color: "#92400E" },
          { label: "Pending",    count: stats.pending,   bg: "#DBEAFE", color: "#1E40AF" },
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
              {allTransfers.map((t, idx) => {
                const s   = STATUS_STYLE[t.status];
                const acts = roleActions[t.status] ?? [];
                const busy = transitioning === t.id;
                return (
                  <tr key={t.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "10px 12px" }}>
                      <Link href={`/${org}/transfers/${t.id}`} style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: tenant.color, textDecoration: "none" }}>
                        {t.ref} →
                      </Link>
                    </td>
                    <td style={{ padding: "10px 12px", color: "#374151", fontSize: 13 }}>{t.from_warehouse_name}</td>
                    <td style={{ padding: "10px 12px", color: "#374151", fontSize: 13 }}>{t.to_warehouse_name}</td>
                    <td style={{ padding: "10px 12px", color: "#6B7280", fontSize: 13 }}>{t.product_name}</td>
                    <td style={{ padding: "10px 12px", fontWeight: 600, color: "#111827", fontSize: 13 }}>{t.quantity.toLocaleString()}</td>
                    <td style={{ padding: "10px 12px" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3, background: s.bg, color: s.color, whiteSpace: "nowrap" }}>
                        {t.status}
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
                            <span title="Offline — actions unavailable" style={{ fontSize: 11, color: "#9CA3AF" }}>🔌 offline</span>
                          )}
                          {acts.map((a) => (
                            <button
                              key={a.next}
                              disabled={!isOnline}
                              onClick={() => setConfirmModal({ id: t.id, next: a.next, label: a.label, transfer: t })}
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
        {allTransfers.length === 0 && (
          <p style={{ padding: "2rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>No transfers yet. Click "+ New Transfer" to create one.</p>
        )}
      </div>
    </div>
  );
}
