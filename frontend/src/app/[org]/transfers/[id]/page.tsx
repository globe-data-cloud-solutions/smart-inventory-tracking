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
type TransferStatus =
  | "DRAFT" | "SUBMITTED" | "APPROVED" | "IN_TRANSIT" | "RECEIVED" | "CLOSED" | "REJECTED" | "CANCELLED";

interface TransferDetail {
  id: string; ref: string;
  product_id: string; product_name: string;
  from_warehouse_id: string; from_warehouse_name: string;
  to_warehouse_id: string; to_warehouse_name: string;
  quantity: number; notes: string;
  status: TransferStatus;
  created_at: string;
}

/* ── Constants ───────────────────────────────────────────────────────────── */
const DARK  = "#0f2d1f";
const GOLD  = "#FCDD09";
const FOREST = "#1B4332";

// Forward-progress states (in order)
const TIMELINE_STATES: TransferStatus[] = ["DRAFT", "SUBMITTED", "APPROVED", "IN_TRANSIT", "RECEIVED", "CLOSED"];

const STATUS_META: Record<TransferStatus, { bg: string; color: string; label: string }> = {
  DRAFT:      { bg: "#F3F4F6", color: "#6B7280", label: "Draft" },
  SUBMITTED:  { bg: "#DBEAFE", color: "#1E40AF", label: "Submitted" },
  APPROVED:   { bg: "#D1FAE5", color: "#065F46", label: "Approved" },
  IN_TRANSIT: { bg: "#FEF3C7", color: "#92400E", label: "In Transit" },
  RECEIVED:   { bg: "#DCFCE7", color: "#166534", label: "Received" },
  CLOSED:     { bg: "#F3F4F6", color: "#374151", label: "Closed" },
  REJECTED:   { bg: "#FEE2E2", color: "#991B1B", label: "Rejected" },
  CANCELLED:  { bg: "#F3F4F6", color: "#9CA3AF", label: "Cancelled" },
};

const ROLE_TRANSITIONS: Record<string, Partial<Record<TransferStatus, { next: TransferStatus; label: string; color: string }[]>>> = {
  WM: {
    DRAFT:      [{ next: "SUBMITTED",  label: "Submit for Approval", color: "#1E40AF"  }, { next: "CANCELLED", label: "Cancel", color: "#DC2626" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark as Received",    color: "#059669"  }],
  },
  LM: {
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch",            color: "#92400E"  }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark as Received",    color: "#059669"  }],
  },
  RM: {
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve",             color: "#059669"  }, { next: "REJECTED",  label: "Reject",  color: "#DC2626" }],
    APPROVED:   [{ next: "CANCELLED",  label: "Cancel",              color: "#DC2626"  }],
  },
  NM: {
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve",             color: "#059669"  }, { next: "REJECTED",  label: "Reject",  color: "#DC2626" }],
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch",            color: "#92400E"  }, { next: "CANCELLED", label: "Cancel",  color: "#DC2626" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark as Received",    color: "#059669"  }],
  },
  TA: {
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve",             color: "#059669"  }, { next: "REJECTED",  label: "Reject",  color: "#DC2626" }],
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch",            color: "#92400E"  }, { next: "CANCELLED", label: "Cancel",  color: "#DC2626" }],
    DRAFT:      [{ next: "SUBMITTED",  label: "Submit for Approval", color: "#1E40AF"  }, { next: "CANCELLED", label: "Cancel",  color: "#DC2626" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark as Received",    color: "#059669"  }],
  },
  SA: {
    DRAFT:      [{ next: "SUBMITTED",  label: "Submit for Approval", color: "#1E40AF"  }, { next: "CANCELLED", label: "Cancel",  color: "#DC2626" }],
    SUBMITTED:  [{ next: "APPROVED",   label: "Approve",             color: "#059669"  }, { next: "REJECTED",  label: "Reject",  color: "#DC2626" }],
    APPROVED:   [{ next: "IN_TRANSIT", label: "Dispatch",            color: "#92400E"  }, { next: "CANCELLED", label: "Cancel",  color: "#DC2626" }],
    IN_TRANSIT: [{ next: "RECEIVED",   label: "Mark as Received",    color: "#059669"  }],
    RECEIVED:   [{ next: "CLOSED",     label: "Close Transfer",      color: "#374151"  }],
  },
};

/* ── Status timeline ─────────────────────────────────────────────────────── */
function TransferTimeline({ status }: { status: TransferStatus }) {
  const terminal = status === "REJECTED" || status === "CANCELLED";
  const activeIdx = TIMELINE_STATES.indexOf(status);

  return (
    <div style={{ padding: "1.25rem 1.5rem", background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}>
      <p style={{ fontSize: 12, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: "0.05em", margin: "0 0 1rem" }}>
        Transfer Progress
      </p>
      <div style={{ display: "flex", alignItems: "center" }}>
        {TIMELINE_STATES.map((s, idx) => {
          const done    = terminal ? false : activeIdx > idx;
          const current = !terminal && activeIdx === idx;
          const future  = !done && !current;

          return (
            <div key={s} style={{ display: "flex", alignItems: "center", flex: idx < TIMELINE_STATES.length - 1 ? 1 : "none" }}>
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
                  fontSize: 10, fontWeight: current ? 700 : 500, whiteSpace: "nowrap",
                  color: done ? FOREST : current ? DARK : "#9CA3AF",
                }}>
                  {STATUS_META[s]?.label ?? s}
                </span>
              </div>
              {/* Connector */}
              {idx < TIMELINE_STATES.length - 1 && (
                <div style={{ flex: 1, height: 2, background: done ? FOREST : "#E5E7EB", margin: "0 4px", marginBottom: 20 }} />
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
            <span style={{ fontSize: 10, fontWeight: 700, color: STATUS_META[status].color }}>{STATUS_META[status].label}</span>
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

  const [toast, setToast]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [confirm, setConfirm]   = useState<{ next: TransferStatus; label: string } | null>(null);

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
    return (
      <div style={{ padding: "3rem", textAlign: "center", color: "#9CA3AF" }}>
        Loading transfer…
      </div>
    );
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
  const roleActs = (ROLE_TRANSITIONS[user.role] ?? {})[transfer.status] ?? [];

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
              {confirm.label} transfer <strong>{transfer.ref}</strong>? Status will change to <strong>{confirm.next}</strong>.
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
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden", maxWidth: 760 }}>
        <div style={{ height: 4, background: tenant.color }} />

        {/* Header */}
        <div style={{ padding: "1.25rem 1.5rem", background: DARK, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <p style={{ fontFamily: "monospace", fontSize: 18, fontWeight: 700, color: GOLD, margin: 0 }}>{transfer.ref}</p>
            <p style={{ fontSize: 13, color: "#6ee7b7", margin: "4px 0 0" }}>Stock Transfer · {tenant.name}</p>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, padding: "5px 14px", borderRadius: 99, background: s.bg, color: s.color }}>
            {s.label}
          </span>
        </div>

        {/* Timeline */}
        <TransferTimeline status={transfer.status} />

        {/* Details */}
        <div style={{ padding: "1.5rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: "1.5rem" }}>
            {[
              { label: "From",     value: transfer.from_warehouse_name },
              { label: "To",       value: transfer.to_warehouse_name   },
              { label: "Product",  value: transfer.product_name        },
              { label: "Quantity", value: transfer.quantity.toLocaleString() },
              { label: "Created",  value: new Date(transfer.created_at).toLocaleString() },
              { label: "Status",   value: s.label },
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
              🔌 <strong>Offline</strong> — Transfer status changes require an internet connection. Actions are disabled until you reconnect.
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

          {roleActs.length === 0 && !["CLOSED", "REJECTED", "CANCELLED"].includes(transfer.status) && (
            <p style={{ fontSize: 13, color: "#9CA3AF", fontStyle: "italic" }}>
              No actions available for your role ({user.role}) at this stage.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
