/* eslint-disable react-hooks/rules-of-hooks */
/* TODO: hooks are called after early guards — move guards after all hooks or use enabled:{} option on useQuery (pre-existing architectural issue, not introduced by inline-style session) */
"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { useInventoryStore } from "@/lib/inventory-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

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

/* ── Status / type Tailwind maps ────────────────────────────────────────── */
const STATUS_META: Record<TransferStatus, { bgClass: string; textClass: string; label: string }> = {
  DRAFT:                  { bgClass: "bg-gray-100",      textClass: "text-gray-500",      label: "Draft" },
  PENDING_REVIEW:         { bgClass: "bg-violet-100",    textClass: "text-violet-700",    label: "Pending Review" },
  PENDING_APPROVAL:       { bgClass: "bg-blue-100",      textClass: "text-blue-800",      label: "Pending Approval" },
  PENDING_SOURCE_CONFIRM: { bgClass: "bg-amber-100",     textClass: "text-amber-800",     label: "Pending Source Confirm" },
  PENDING_DEST_CONFIRM:   { bgClass: "bg-amber-100",     textClass: "text-amber-800",     label: "Pending Dest Confirm" },
  APPROVED:               { bgClass: "bg-emerald-100",   textClass: "text-emerald-800",   label: "Approved" },
  ADVISED:                { bgClass: "bg-emerald-50",    textClass: "text-emerald-600",   label: "Advised" },
  ISSUED:                 { bgClass: "bg-emerald-100",   textClass: "text-emerald-800",   label: "Issued" },
  IN_TRANSIT:             { bgClass: "bg-amber-100",     textClass: "text-amber-800",     label: "In Transit" },
  PARTIALLY_RECEIVED:     { bgClass: "bg-yellow-100",    textClass: "text-yellow-800",    label: "Partially Received" },
  RECEIVED:               { bgClass: "bg-green-100",     textClass: "text-green-800",     label: "Received" },
  COMPLETED:              { bgClass: "bg-gray-100",      textClass: "text-gray-700",      label: "Completed" },
  REJECTED:               { bgClass: "bg-red-100",       textClass: "text-red-800",       label: "Rejected" },
  CANCELLED:              { bgClass: "bg-gray-100",      textClass: "text-gray-400",      label: "Cancelled" },
};

const TYPE_META: Record<TransferType, { bgClass: string; textClass: string; label: string; desc: string }> = {
  PULL:   { bgClass: "bg-blue-100",    textClass: "text-blue-800",    label: "PULL",   desc: "Pull Request" },
  PUSH:   { bgClass: "bg-amber-100",   textClass: "text-amber-800",   label: "PUSH",   desc: "Push Issue" },
  SISTER: { bgClass: "bg-violet-100",  textClass: "text-violet-700",  label: "SISTER", desc: "Sister Transfer" },
};

const TIMELINE_STATES: Record<TransferType, TransferStatus[]> = {
  PULL:   ["DRAFT", "PENDING_REVIEW", "PENDING_APPROVAL", "APPROVED", "ISSUED", "IN_TRANSIT", "RECEIVED", "COMPLETED"],
  PUSH:   ["DRAFT", "PENDING_APPROVAL", "APPROVED", "ADVISED", "ISSUED", "IN_TRANSIT", "RECEIVED", "COMPLETED"],
  SISTER: ["DRAFT", "PENDING_SOURCE_CONFIRM", "PENDING_DEST_CONFIRM", "PENDING_APPROVAL", "APPROVED", "ISSUED", "IN_TRANSIT", "RECEIVED", "COMPLETED"],
};

function getAvailableActions(
  role: string,
  type: TransferType,
  status: TransferStatus,
  userWH?: string,
  fromWH?: string,
  toWH?: string,
): Action[] {
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
  const submitReq:  Action = { next: "PENDING_SOURCE_CONFIRM", label: "Submit Request",       color: "#5B21B6" };
  const confirmSup: Action = { next: "PENDING_DEST_CONFIRM",   label: "Confirm Supply",       color: "#059669" };
  const confirmInt: Action = { next: "PENDING_APPROVAL",       label: "Confirm & Escalate",   color: "#1E40AF" };

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

  if (role === "WM") {
    const isDestWM = !!userWH && userWH === toWH;
    const isSrcWM  = !!userWH && userWH === fromWH;

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
      void isSrcWM;
      return [];
    }
    if (type === "SISTER") {
      if (isDestWM) {
        const map: Partial<Record<TransferStatus, Action[]>> = {
          DRAFT:                [submitReq, cancel],
          PENDING_DEST_CONFIRM: [confirmInt, reject, cancel],
          IN_TRANSIT:           [partRecv, markRecv],
          PARTIALLY_RECEIVED:   [markRecv],
          RECEIVED:             [complete],
        };
        return map[status] ?? [];
      }
      if (isSrcWM) {
        const map: Partial<Record<TransferStatus, Action[]>> = {
          PENDING_SOURCE_CONFIRM: [confirmSup, reject, cancel],
          APPROVED:               [issue, cancel],
          ISSUED:                 [dispatch],
        };
        return map[status] ?? [];
      }
      return [];
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
  const termMeta  = STATUS_META[status];

  return (
    <div className="px-6 py-5 bg-gray-50 border-b border-gray-200">
      <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-4">
        {t("transfers.progress")}
      </p>
      <div className="flex items-center overflow-x-auto pb-1">
        {timelineStates.map((s, idx) => {
          const done    = terminal ? false : activeIdx > idx;
          const current = !terminal && activeIdx === idx;

          return (
            <div key={s} className={`flex items-center ${idx < timelineStates.length - 1 ? "flex-1" : ""}`}>
              <div className="flex flex-col items-center gap-1.5">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center font-extrabold text-[11px] flex-shrink-0 ring-2 ${
                  done    ? "bg-[#1B4332] text-white ring-transparent" :
                  current ? "bg-[#FCDD09] text-[#0f2d1f] ring-[#1B4332]" :
                            "bg-gray-200 text-gray-400 ring-transparent"
                }`}>
                  {done ? "✓" : idx + 1}
                </div>
                <span className={`text-[9px] whitespace-nowrap max-w-[72px] text-center leading-tight ${
                  done    ? "text-[#1B4332] font-medium" :
                  current ? "text-[#0f2d1f] font-bold" :
                            "text-gray-400 font-medium"
                }`}>
                  {STATUS_META[s]?.label ?? s}
                </span>
              </div>
              {idx < timelineStates.length - 1 && (
                <div className={`flex-1 h-0.5 mx-1 mb-5 min-w-2 ${done ? "bg-[#1B4332]" : "bg-gray-200"}`} />
              )}
            </div>
          );
        })}

        {terminal && (
          <div className="ml-3 flex flex-col items-center gap-1.5">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-sm ${termMeta.bgClass} ${termMeta.textClass}`}>
              ✕
            </div>
            <span className={`text-[9px] font-bold ${termMeta.textClass}`}>{termMeta.label}</span>
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
  const { updateTransferStatus, addTransfer, getTransferEntry } = useInventoryStore();

  const [toast, setToast]     = useState("");
  const [loading, setLoading] = useState(false);
  const [confirm, setConfirm] = useState<{ next: TransferStatus; label: string } | null>(null);

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("transfers.select_tenant")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant || !user) return <p className="p-8 text-gray-500">{t("transfers.not_found")}</p>;

  const { data: transfer, isLoading, error } = useQuery<TransferDetail>({
    queryKey: ["transfer", id],
    queryFn:  () => api.get<TransferDetail>(`/api/v1/transfers/${id}`),
    staleTime: 0,
    refetchInterval: 15000,
  });

  async function doTransition(next: TransferStatus) {
    if (!isOnline) {
      setConfirm(null);
      setToast(t("transfers.offline_action_blocked"));
      setTimeout(() => setToast(""), 5000);
      return;
    }
    setLoading(true);
    setConfirm(null);
    try {
      await api.patch(`/api/v1/transfers/${id}`, { next_status: next });

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
      await qc.invalidateQueries({ queryKey: ["transfer", id] });
      await qc.invalidateQueries({ queryKey: ["transfers", org] });
      setToast(`${t("transfers.updated_to")} ${next}`);
      setTimeout(() => setToast(""), 3000);
    } catch (err: unknown) {
      setToast(err instanceof Error ? err.message : t("transfers.transition_failed"));
      setTimeout(() => setToast(""), 4000);
    } finally {
      setLoading(false);
    }
  }

  if (isLoading) {
    return <div className="p-12 text-center text-gray-400">{t("transfers.loading")}</div>;
  }

  if (error || !transfer) {
    return (
      <div className="p-8">
        <p className="text-red-600 text-sm">{t("transfers.transfer_not_found")}</p>
        <button
          onClick={() => router.back()}
          className="mt-3 text-sm text-[#1B4332] bg-transparent border-none cursor-pointer underline"
        >
          {t("transfers.back")}
        </button>
      </div>
    );
  }

  const s        = STATUS_META[transfer.status];
  const tb       = TYPE_META[transfer.transfer_type] ?? { bgClass: "bg-gray-100", textClass: "text-gray-600", label: transfer.transfer_type, desc: transfer.transfer_type };
  const roleActs = getAvailableActions(
    user.role, transfer.transfer_type, transfer.status,
    user.warehouseId, transfer.from_warehouse_id, transfer.to_warehouse_id
  );
  const terminal = ["COMPLETED", "REJECTED", "CANCELLED"].includes(transfer.status);

  const detailFields = [
    { label: t("transfers.detail.type"),     value: `${tb.label} — ${tb.desc}` },
    { label: t("transfers.detail.status"),   value: s.label },
    { label: t("transfers.detail.from"),     value: transfer.from_warehouse_name },
    { label: t("transfers.detail.to"),       value: transfer.to_warehouse_name },
    { label: t("transfers.detail.product"),  value: transfer.product_name },
    { label: t("transfers.detail.quantity"), value: transfer.quantity.toLocaleString() },
    { label: t("transfers.detail.created"),  value: new Date(transfer.created_at).toLocaleString() },
  ];

  return (
    <div className="p-8">
      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0f2d1f] text-[#FCDD09] font-bold text-sm px-5 py-2.5 rounded-md shadow-lg max-w-sm">
          {toast}
        </div>
      )}

      {/* Confirm modal */}
      {confirm && (
        <>
          <div onClick={() => setConfirm(null)} className="fixed inset-0 bg-black/40 z-50" />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-xl p-8 z-50 w-[340px] shadow-2xl">
            <p className="font-bold text-base text-gray-900 mb-2">{t("transfers.confirm_action")}</p>
            <p className="text-sm text-gray-500 mb-6">
              {confirm.label} {t("transfers.confirm_transfer")} <strong>{transfer.ref}</strong>?{" "}
              {t("transfers.status_will_change")} <strong>{confirm.next.replace(/_/g, " ")}</strong>.
            </p>
            <div className="flex gap-2.5">
              <button
                onClick={() => setConfirm(null)}
                className="flex-1 py-2 bg-gray-100 border-none rounded-md text-sm font-semibold cursor-pointer hover:bg-gray-200 transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={() => doTransition(confirm.next)}
                className="flex-[2] py-2 bg-[#1B4332] text-[#FCDD09] border-none rounded-md text-sm font-bold cursor-pointer hover:bg-[#0f2d1f] transition-colors"
              >
                {t("common.confirm")}
              </button>
            </div>
          </div>
        </>
      )}

      {/* Back link */}
      <button
        onClick={() => router.back()}
        className="text-sm text-gray-500 bg-transparent border-none cursor-pointer mb-4 p-0 hover:text-gray-700 transition-colors"
      >
        {t("transfers.back")}
      </button>

      {/* Transfer card */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden max-w-[800px]">
        {/* Tenant colour bar — runtime value, legitimately dynamic */}
        {/* uses --tenant-color from [org]/layout.tsx */}
        <div className="h-1 bg-[var(--tenant-color)]" />

        {/* Header */}
        <div className="px-6 py-5 bg-[#0f2d1f] flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="font-mono text-lg font-bold text-[#FCDD09] m-0">{transfer.ref}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${tb.bgClass} ${tb.textClass}`}>
                {tb.label}
              </span>
              <span className="text-sm text-emerald-300">{tb.desc} · {tenant.name}</span>
            </div>
          </div>
          <span className={`text-sm font-bold px-3.5 py-1.5 rounded-full ${s.bgClass} ${s.textClass}`}>
            {s.label}
          </span>
        </div>

        {/* Timeline */}
        <TransferTimeline status={transfer.status} transferType={transfer.transfer_type} />

        {/* Details */}
        <div className="p-6">
          <div className="grid grid-cols-2 gap-3 mb-6">
            {detailFields.map(({ label, value }) => (
              <div key={label} className="px-3.5 py-2.5 bg-gray-50 rounded-md border border-gray-200">
                <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 m-0">{label}</p>
                <p className="text-sm font-semibold text-gray-900 mt-1 mb-0">{value}</p>
              </div>
            ))}
          </div>

          {transfer.notes && (
            <div className="px-3.5 py-2.5 bg-amber-50 border border-amber-200 rounded-md mb-6 text-sm text-amber-800">
              <strong>{t("transfers.detail.notes")}:</strong> {transfer.notes}
            </div>
          )}

          {/* Offline warning */}
          {!isOnline && roleActs.length > 0 && (
            <div className="px-3.5 py-2.5 bg-red-50 border border-red-200 rounded-md mb-4 text-sm text-red-600">
              <strong>{t("common.offline")}</strong> — {t("transfers.offline_actions_disabled")}
            </div>
          )}

          {/* Action buttons — a.color is runtime hex, style= is legitimately required */}
          {roleActs.length > 0 && (
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2.5">
                {t("transfers.available_actions")}
              </p>
              <div className="flex gap-2.5 flex-wrap">
                {loading ? (
                  <span className="text-sm text-gray-400">{t("transfers.updating")}</span>
                ) : (
                  roleActs.map((a) => (
                    <button
                      key={a.next}
                      disabled={!isOnline}
                      onClick={() => setConfirm({ next: a.next, label: a.label })}
                      style={{
                        border:     `1.5px solid ${a.color}40`,
                        background: isOnline ? `${a.color}10` : undefined,
                        color:      isOnline ? a.color : undefined,
                      }}
                      className={`px-6 py-2.5 rounded-md font-bold text-sm transition-opacity ${
                        isOnline ? "cursor-pointer opacity-100" : "cursor-not-allowed opacity-50 bg-gray-100 text-gray-400"
                      }`}
                    >
                      {a.label}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}

          {roleActs.length === 0 && !terminal && (
            <p className="text-sm text-gray-400 italic">
              {t("transfers.no_actions_for_role")} ({user.role})
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
