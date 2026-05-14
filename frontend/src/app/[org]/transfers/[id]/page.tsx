"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { useInventoryStore } from "@/lib/inventory-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { api } from "@/lib/api";

/* ── Types ──────────────────────────────────────────────────────────────── */
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

interface TransferDetail {
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

interface Action {
  next: TransferStatus;
  label: string;
  color: string;
}

/* ── Constants ───────────────────────────────────────────────────────────── */
const DARK   = "#0f2d1f";
const GOLD   = "#FCDD09";
const FOREST = "#1B4332";

const STATUS_META: Record<TransferStatus, { bg: string; color: string; label: string }> = {
  DRAFT:                  { bg: "#F3F4F6", color: "#6B7280", label: "Draft" },
  PENDING_REVIEW:         { bg: "#EDE9FE", color: "#5B21B6", label: "Pending Review" },
  PENDING_APPROVAL:       { bg: "#DBEAFE", color: "#1E40AF", label: "Pending Approval" },
  PENDING_SOURCE_CONFIRM: { bg: "#FEF3C7", color: "#92400E", label: "Pending Source Confirm" },
  PENDING_DEST_CONFIRM:   { bg: "#FEF3C7", color: "#92400E", label: "Pending Dest Confirm" },
  APPROVED:               { bg: "#D1FAE5", color: "#065F46", label: "Approved" },
  ADVISED:                { bg: "#ECFDF5", color: "#059669", label: "Advised" },
  ISSUED:                 { bg: "#D1FAE5", color: "#065F46", label: "Issued" },
  IN_TRANSIT:             { bg: "#FEF3C7", color: "#92400E", label: "In Transit" },
  PARTIALLY_RECEIVED:     { bg: "#FEF9C3", color: "#713F12", label: "Partially Received" },
  RECEIVED:               { bg: "#DCFCE7", color: "#166534", label: "Received" },
  COMPLETED:              { bg: "#F3F4F6", color: "#374151", label: "Completed" },
  REJECTED:               { bg: "#FEE2E2", color: "#991B1B", label: "Rejected" },
  CANCELLED:              { bg: "#F3F4F6", color: "#9CA3AF", label: "Cancelled" },
};

const TYPE_BADGE: Record<TransferType, { bg: string; color: string; label: string; desc: string }> = {
  PULL:   { bg: "#DBEAFE", color: "#1E40AF", label: "PULL", desc: "Pull Request" },
  PUSH:   { bg: "#FEF3C7", color: "#92400E", label: "PUSH", desc: "Push Issue" },
  SISTER: { bg: "#EDE9FE", color: "#5B21B6", label: "SISTER", desc: "Sister Transfer" },
};

const TIMELINE_STATES: Record<TransferType, TransferStatus[]> = {
  PULL:   ["DRAFT", "PENDING_REVIEW", "PENDING_APPROVAL", "APPROVED", "ISSUED", "IN_TRANSIT", "RECEIVED", "COMPLETED"],
  PUSH:   ["DRAFT", "PENDING_APPROVAL", "APPROVED", "ADVISED", "ISSUED", "IN_TRANSIT", "RECEIVED", "COMPLETED"],
  SISTER: ["DRAFT", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM", "PENDING_APPROVAL", "APPROVED", "ISSUED", "IN_TRANSIT", "RECEIVED", "COMPLETED"],
};

function getAvailableActions(role: string, type: TransferType, status: TransferStatus): Action[] {
  const approve:    Action = { next: "APPROVED",               label: "Approve",              color: "#059669" };
  const reject:     Action = { next: "REJECTED",               label: "Reject",               color: "#DC2626" };
  const cancel:     Action = { next: "CANCELLED",              label: "Cancel",               color: "#DC2626" };
  const issue:      Action = { next: "ISSUED",                 label: "Issue Stock",           color: "#065F46" };
  const dispatch:   Action = { next: "IN_TRANSIT",             label: "Dispatch",             color: "#92400E" };
  const advise:     Action = { next: "ADVISED",                label: "Advise",               color: "#059669" };
  const partRecv:   Action = { next: "PARTIALLY_RECEIVED",     label: "Partially Received",   color: "#713F12" };
  const markRecv:   Action = { next: "RECEIVED",               label: "Mark as Received",     color: "#059669" };
  const complete:   Action = { next: "COMPLETED",              label: "Complete Transfer",    color: "#374151" };
  const review:     Action = { next: "PENDING_REVIEW",         label: "Submit for Review",    color: "#5B21B6" };
  const toApproval: Action = { next: "PENDING_APPROVAL",       label: "Send for Approval",    color: "#1E40AF" };
  const srcConfirm: Action = { next: "PENDING_SOURCE_CONFIRM", label: "Request Confirmation", color: "#92400E" };
  const dstConfirm: Action = { next: "PENDING_DEST_CONFIRM",   label: "Dest Confirm",         color: "#92400E" };

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
        DRAFT:              [toApproval, cancel],
        PENDING_APPROVAL:   [approve, reject, cancel],
        APPROVED:           [advise, issue, cancel],
        ADVISED:            [issue, cancel],
        ISSUED:             [dispatch],
        IN_TRANSIT:         [partRecv, markRecv],
        PARTIALLY_RECEIVED: [markRecv],
        RECEIVED:           [complete],
      };
      return map[status] ?? [];
    }
    if (type === "SISTER") {
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:                  [srcConfirm, cancel],
        PENDING_SOURCE_CONFIRM: [dstConfirm, cancel],
        PENDING_DEST_CONFIRM:   [toApproval, reject, cancel],
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
      const map: Partial<Record<TransferStatus, Action[]>> = {
        DRAFT:                [srcConfirm, cancel],
        PENDING_DEST_CONFIRM: [toApproval, cancel],
        IN_TRANSIT:           [partRecv, markRecv],
        PARTIALLY_RECEIVED:   [markRecv],
        RECEIVED:             [complete],
      };
      return map[status] ?? [];
    }
    return [];
  }

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

/* ── Timeline component ──────────────────────────────────────────────────── */
function TransferTimeline({ status, transferType }: { status: TransferStatus; transferType: TransferType }) {
  const timelineStates = TIMELINE_STATES[transferType];
  const terminal  = status === "REJECTED" || status === "CANCELLED";
  const activeIdx = timelineStates.indexOf(status);

  return (
    <div style={{ padding: "1.25rem 1.5rem", background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}>
      <p style={{ fontSize: 12, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: "0.05em", margin: "0 0 1rem" }}>
        Transfer Progress
      </p>
      <div style={{ display: "flex", alignItems: "center", overflowX: "auto", paddingBottom: 4 }}>
        {timelineStates.map((s, idx) => {
          const done    = terminal ? false : activeIdx > idx;
          const current = !terminal && activeIdx === idx;

          return (
            <div key={s} style={{ display: "flex", alignItems: "center", flex: idx < timelineStates.length - 1 ? 1 : "none" }}>
              {/* Node */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: "50%",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 800, fontSize: 11,
                  background: done ? FOREST : current ? GOLD : "#E5E7EB",
                  color: done ? "#fff" : current ? DARK : "#9CA3AF",
                  border: current ? `2px solid ${FOREST}` : "2px solid transparent",
                  flexShrink: 0,
                }}>
                  {done ? "✓" : idx + 1}
                </div>
                <span style={{
                  fontSize: 9, fontWeight: current ? 700 : 500, whiteSpace: "nowrap",
                  color: done ? FOREST : current ? DARK : "#9CA3AF",
                  maxWidth: 72, textAlign: "center", lineHeight: 1.2,
                }}>
                  {STATUS_META[s]?.label ?? s}
                </span>
              </div>
              {/* Connector */}
              {idx < timelineStates.length - 1 && (
                <div style={{ flex: 1, height: 2, background: done ? FOREST : "#E5E7EB", margin: "0 4px", marginBottom: 20, minWidth: 8 }} />
              )}
            </div>
          );
        })}

        {/* Terminal state badge */}
        {terminal && (
          <div style={{ marginLeft: 12, display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%",
              background: STATUS_META[status].bg, color: STATUS_META[status].color,
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13,
            }}>✕</div>
            <span style={{ fontSize: 9, fontWeight: 700, color: STATUS_META[status].color }}>{STATUS_META[status].label}</span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Main page ───────────────────────────────────────────────────────────── */
export default function TransferDetailPage() {
  const { org, id } = useParams() as { org: string; id: string };
  const router       = useRouter();
  const user         = getSession();
  const qc           = useQueryClient();
  const { isOnline } = useOfflineSync();
  const updateTransferStatus = useInventoryStore((s) => s.updateTransferStatus);

  const [toast, setToast]     = useState("");
  const [loading, setLoading] = useState(false);
  const [confirm, setConfirm] = useState<{ next: TransferStatus; label: string } | null>(null);

  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant first.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant || !user) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const { data: transfer, isLoading, error } = useQuery<TransferDetail>({
    queryKey: ["transfer", id],
    queryFn:  () => api.get<TransferDetail>(`/api/v1/transfers/${id}`),
    staleTime: 0,
    refetchInterval: 15000,
  });

  async function doTransition(next: TransferStatus) {
    if (!isOnline) {
      setConfirm(null);
      setToast("Transfer status changes require an internet connection.");
      setTimeout(() => setToast(""), 5000);
      return;
    }
    setLoading(true);
    setConfirm(null);
    try {
      await api.patch(`/api/v1/transfers/${id}`, { next_status: next });
      updateTransferStatus(id, next);
      await qc.invalidateQueries({ queryKey: ["transfer", id] });
      await qc.invalidateQueries({ queryKey: ["transfers", org] });
      setToast(`Transfer updated to ${next}`);
      setTimeout(() => setToast(""), 3000);
    } catch (err: unknown) {
      setToast(err instanceof Error ? err.message : "Transition failed.");
      setTimeout(() => setToast(""), 4000);
    } finally {
      setLoading(false);
    }
  }

  if (isLoading) {
    return <div style={{ padding: "3rem", textAlign: "center", color: "#9CA3AF" }}>Loading transfer…</div>;
  }

  if (error || !transfer) {
    return (
      <div style={{ padding: "2rem" }}>
        <p style={{ color: "#DC2626", fontSize: 14 }}>Transfer not found.</p>
        <button onClick={() => router.back()} style={{ marginTop: 12, fontSize: 13, color: FOREST, background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
          ← Back to Transfers
        </button>
      </div>
    );
  }

  const s        = STATUS_META[transfer.status];
  const tb       = TYPE_BADGE[transfer.transfer_type] ?? { bg: "#F3F4F6", color: "#6B7280", label: transfer.transfer_type, desc: transfer.transfer_type };
  const roleActs = getAvailableActions(user.role, transfer.transfer_type, transfer.status);
  const terminal = ["COMPLETED", "REJECTED", "CANCELLED"].includes(transfer.status);

  return (
    <div style={{ padding: "2rem" }}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 24, right: 24, zIndex: 200,
          background: DARK, color: GOLD, fontWeight: 700, fontSize: 13,
          padding: "10px 20px", borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
          maxWidth: 360,
        }}>
          {toast}
        </div>
      )}

      {/* Confirm modal */}
      {confirm && (
        <>
          <div onClick={() => setConfirm(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 200 }} />
          <div style={{
            position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
            background: "#fff", borderRadius: 10, padding: "2rem", zIndex: 201,
            width: 340, boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
          }}>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#111827", margin: "0 0 0.5rem" }}>Confirm Action</p>
            <p style={{ fontSize: 14, color: "#6B7280", margin: "0 0 1.5rem" }}>
              {confirm.label} transfer <strong>{transfer.ref}</strong>? Status will change to <strong>{confirm.next.replace(/_/g, " ")}</strong>.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={() => setConfirm(null)} style={{ flex: 1, padding: "9px", background: "#F3F4F6", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>Cancel</button>
              <button onClick={() => doTransition(confirm.next)} style={{ flex: 2, padding: "9px", background: FOREST, color: GOLD, border: "none", borderRadius: 6, fontSize: 13, fontWeight: 700, cursor: "pointer" }}>Confirm</button>
            </div>
          </div>
        </>
      )}

      {/* Back link */}
      <button onClick={() => router.back()} style={{ fontSize: 13, color: "#6B7280", background: "none", border: "none", cursor: "pointer", marginBottom: "1rem", padding: 0 }}>
        ← Back to Transfers
      </button>

      {/* Transfer card */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden", maxWidth: 800 }}>
        <div style={{ height: 4, background: tenant.color }} />

        {/* Header */}
        <div style={{ padding: "1.25rem 1.5rem", background: DARK, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <p style={{ fontFamily: "monospace", fontSize: 18, fontWeight: 700, color: GOLD, margin: 0 }}>{transfer.ref}</p>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 3, background: tb.bg, color: tb.color }}>
                {tb.label}
              </span>
              <span style={{ fontSize: 13, color: "#6ee7b7" }}>{tb.desc} · {tenant.name}</span>
            </div>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, padding: "5px 14px", borderRadius: 99, background: s.bg, color: s.color }}>
            {s.label}
          </span>
        </div>

        {/* Timeline */}
        <TransferTimeline status={transfer.status} transferType={transfer.transfer_type} />

        {/* Details */}
        <div style={{ padding: "1.5rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: "1.5rem" }}>
            {[
              { label: "Transfer Type", value: `${tb.label} — ${tb.desc}` },
              { label: "Status",        value: s.label },
              { label: "From",          value: transfer.from_warehouse_name },
              { label: "To",            value: transfer.to_warehouse_name   },
              { label: "Product",       value: transfer.product_name        },
              { label: "Quantity",      value: transfer.quantity.toLocaleString() },
              { label: "Created",       value: new Date(transfer.created_at).toLocaleString() },
            ].map(({ label, value }) => (
              <div key={label} style={{ padding: "10px 14px", background: "#F9FAFB", borderRadius: 6, border: "1px solid #E5E7EB" }}>
                <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#9CA3AF", margin: 0 }}>{label}</p>
                <p style={{ fontSize: 14, fontWeight: 600, color: "#111827", margin: "4px 0 0" }}>{value}</p>
              </div>
            ))}
          </div>

          {transfer.notes && (
            <div style={{ padding: "10px 14px", background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 6, marginBottom: "1.5rem", fontSize: 13, color: "#92400E" }}>
              <strong>Notes:</strong> {transfer.notes}
            </div>
          )}

          {/* Offline warning */}
          {!isOnline && roleActs.length > 0 && (
            <div style={{ padding: "10px 14px", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 6, marginBottom: "1rem", fontSize: 13, color: "#DC2626" }}>
              <strong>Offline</strong> — Transfer status changes require an internet connection. Actions are disabled until you reconnect.
            </div>
          )}

          {/* Action buttons */}
          {roleActs.length > 0 && (
            <div>
              <p style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#9CA3AF", margin: "0 0 10px" }}>
                Available Actions
              </p>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {loading ? (
                  <span style={{ fontSize: 13, color: "#9CA3AF" }}>Updating…</span>
                ) : (
                  roleActs.map((a) => (
                    <button
                      key={a.next}
                      disabled={!isOnline}
                      onClick={() => setConfirm({ next: a.next, label: a.label })}
                      style={{
                        padding: "10px 24px", borderRadius: 6, fontWeight: 700, fontSize: 13,
                        border: `1.5px solid ${a.color}40`,
                        background: isOnline ? `${a.color}10` : "#F3F4F6",
                        color: isOnline ? a.color : "#9CA3AF",
                        cursor: isOnline ? "pointer" : "not-allowed",
                        opacity: isOnline ? 1 : 0.5,
                      }}
                    >
                      {a.label}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}

          {roleActs.length === 0 && !terminal && (
            <p style={{ fontSize: 13, color: "#9CA3AF", fontStyle: "italic" }}>
              No actions available for your role ({user.role}) at this stage.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
