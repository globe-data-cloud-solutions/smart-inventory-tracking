"use client";

import { useParams } from "next/navigation";
import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoProduct, type DemoWarehouse } from "@/lib/demo-data";
import { NewTransferPanel } from "@/components/features/transfers/NewTransferPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useWarehouses } from "@/hooks/useWarehouses";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";

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
  created_by_authority_level?: number;
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
  created_by?: string;
  created_by_authority_level?: number;
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
    notes:                        "",
    status:                       raw.status,
    created_by:                   raw.created_by,
    created_by_authority_level:   raw.created_by_authority_level,
    created_at:                   raw.created_at,
  };
}

/**
 * Returns a contextual "waiting for…" label when the current user has no action on a
 * transfer. Shown in the Actions column instead of "—" so non-actors understand why
 * the row is visible but has no buttons.
 *
 * getLevelName: optional resolver from hierarchy config — maps level_number → tenant
 * level label (e.g. 1 → "National", 2 → "Regional"). When provided, PENDING_REVIEW
 * shows the reviewer's level name derived from the creator's authority level.
 * creatorAuthorityLevel: from transfer.created_by_authority_level.
 * type: used for DRAFT message to identify which facility is responsible for submitting.
 */
function getWaitingMessage(
  status: TransferStatus,
  fromWarehouseName: string,
  toWarehouseName: string,
  creatorAuthorityLevel?: number | null,
  getLevelName?: (levelNum: number) => string,
  type?: TransferType,
): string | null {
  switch (status) {
    case "DRAFT": {
      // PULL: creator is at destination (to_warehouse) — show destination facility.
      // PUSH/SISTER: creator is at source (from_warehouse) — show source facility.
      const submitter = type === "PULL" ? toWarehouseName : fromWarehouseName;
      return `Waiting for ${submitter} to submit`;
    }
    case "PENDING_REVIEW": {
      // Dynamic: derive reviewer level from creator authority level.
      // Creator is WM (authority 4) → reviewer is level 3 (LM/RM).
      if (getLevelName && creatorAuthorityLevel != null && creatorAuthorityLevel > 1) {
        const reviewerLvl = Math.max(1, creatorAuthorityLevel - 1);
        return `Awaiting ${getLevelName(reviewerLvl)} review`;
      }
      return "Awaiting review";
    }
    case "PENDING_APPROVAL":        return "Awaiting approval";
    case "PENDING_SOURCE_CONFIRM":  return `Awaiting ${fromWarehouseName} confirmation`;
    case "PENDING_DEST_CONFIRM":    return `Awaiting ${toWarehouseName} confirmation`;
    case "APPROVED":                return `Waiting for ${fromWarehouseName} to issue`;
    case "ADVISED":                 return `Waiting for ${fromWarehouseName} to issue (advised)`;
    case "ISSUED":                  return `Waiting for ${fromWarehouseName} to dispatch`;
    case "IN_TRANSIT":              return `In transit → ${toWarehouseName}`;
    default:                        return null;
  }
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

// Base styling per underlying type — labels overridden by tenant display name at render time
const TYPE_CLASS: Record<TransferType, { cls: string; label: string }> = {
  PULL:   { cls: "bg-blue-100   text-blue-800",   label: "PULL"   },
  PUSH:   { cls: "bg-amber-100  text-amber-800",  label: "PUSH"   },
  SISTER: { cls: "bg-violet-100 text-violet-800", label: "SISTER" },
};

interface TenantTransferType { id: string; underlying_type: TransferType; display_name: string; is_active: boolean }

/**
 * Authority level scale — lower number = higher authority (mirrors backend ROLE_AUTHORITY_LEVEL).
 * Used to compute canReview / canApprove / isSrcManager / isDstManager without hardcoding
 * role names.  Adding a new role only requires adding it here.
 */
const ROLE_AUTHORITY_LEVEL: Record<string, number> = {
  SA: 1, TA: 1, NM: 1,
  RM: 2,
  LM: 3,
  WM: 4,
  SA_GT: 5, RT: 5, AU: 5, SYS: 5,
};

/**
 * Returns the action buttons available to this user for a specific transfer.
 *
 * Authority-level rules (replace all hardcoded role === 'X' checks):
 *
 *   isTenantMgr  = userLevel <= 1          SA/TA/NM — tenant-wide authority
 *   isSrcManager = isTenantMgr || isSrcWH  dispatch / issue authority
 *   isDstManager = isTenantMgr || isDstWH || isCreator   receive authority
 *
 *   canReview    = !isCreator && userLevel === immediateReviewerLevel
 *                  immediateReviewerLevel = max(1, creatorAuthorityLevel - 1)
 *                  Only the IMMEDIATE superior reviews — not anyone who outranks
 *                  the creator.  For a WM (L4) creator: reviewer is L3 (LM).
 *
 *   canApprove   = canApproveOverride (from approval-info endpoint) when available,
 *                  else falls back to userLevel <= 2 && !isCreator.
 *                  The override ensures the frontend matches the backend's actual
 *                  required authority level (e.g., NM-created PUSH requires L1).
 *
 * UUID comparisons are always case-insensitive — JWT warehouseId and DB UUIDs
 * may differ in casing depending on how the JWT was issued vs how Postgres
 * serialises UUIDs (CLAUDE.md §27).
 */
function getAvailableActions(
  role: string,
  type: TransferType,
  status: TransferStatus,
  userWH?: string,
  fromWH?: string,
  toWH?: string,
  _quantity?: number,
  userId?: string,
  createdBy?: string,
  creatorAuthorityLevel?: number,
  canApproveOverride?: boolean,   // from approval-info endpoint; takes precedence when defined
): Action[] {
  const userLevel = ROLE_AUTHORITY_LEVEL[role] ?? 5;
  if (userLevel >= 5) return [];   // AU/RT/SYS/SA_GT have no transfer authority

  const uWH     = userWH?.toLowerCase();
  const isSrcWH = !!uWH && uWH === fromWH?.toLowerCase();
  const isDstWH = !!uWH && uWH === toWH?.toLowerCase();
  const isCreator = !!userId && userId === createdBy;

  // Tenant-level managers (NM/TA/SA, level ≤ 1) have authority over any transfer.
  // Facility-bound roles (RM/LM/WM) need their warehouse_id to match.
  const isTenantMgr  = userLevel <= 1;
  const isSrcManager = isTenantMgr || isSrcWH;
  const isDstManager = isTenantMgr || isDstWH || isCreator;

  // PENDING_REVIEW — only the IMMEDIATE superior of the creator reviews.
  // immediateReviewerLevel = creatorLevel - 1 (floor at 1).
  // WM (L4) creator → L3 (LM) reviews. RM (L2) creator → L1 (NM) reviews.
  // This prevents NM from seeing review buttons on WM-created PULLs (that belongs to RM/LM).
  const immediateReviewerLevel = Math.max(1, (creatorAuthorityLevel ?? 4) - 1);
  const canReview = !isCreator
    && creatorAuthorityLevel != null
    && userLevel === immediateReviewerLevel;

  // PENDING_APPROVAL — use the approval-info response when available (canApproveOverride).
  // The override reflects the backend's actual required_authority_level which accounts for
  // self-approval escalation (e.g., NM-created PUSH requires TA/different-NM, not RM).
  // Falls back to level ≤ 2 && !isCreator when approval-info hasn't loaded yet.
  const canApprove = canApproveOverride !== undefined
    ? canApproveOverride
    : (userLevel <= 2 && !isCreator);

  // ── Action definitions (defined once, referenced by all maps) ─────────────
  const approve   : Action = { next: "APPROVED",               label: "Approve",            color: "#059669" };
  const reject    : Action = { next: "REJECTED",               label: "Reject",             color: "#991B1B" };
  const cancel    : Action = { next: "CANCELLED",              label: "Cancel",             color: "#991B1B" };
  const issue     : Action = { next: "ISSUED",                 label: "Issue",              color: "#065F46" };
  const dispatch  : Action = { next: "IN_TRANSIT",             label: "Dispatch",           color: "#92400E" };
  const advise    : Action = { next: "ADVISED",                label: "Advise",             color: "#059669" };
  // PARTIAL_RECEIVE: hidden pending full implementation. State machine entry kept
  // for data integrity. Re-enable by adding partialReceive back to IN_TRANSIT actions.
  // See BUG_REPORT.md §deferred
  const markRecv  : Action = { next: "RECEIVED",               label: "Mark Received",      color: "#059669" };
  const complete  : Action = { next: "COMPLETED",              label: "Complete",           color: "#374151" };
  const review    : Action = { next: "PENDING_REVIEW",         label: "Submit for Review",  color: "#5B21B6" };
  const toApproval: Action = { next: "PENDING_APPROVAL",       label: "Send for Approval",  color: "#1E40AF" };
  const submitReq : Action = { next: "PENDING_SOURCE_CONFIRM", label: "Submit Request",     color: "#5B21B6" };
  const confirmSup: Action = { next: "PENDING_DEST_CONFIRM",   label: "Confirm Supply",     color: "#059669" };
  const confirmInt: Action = { next: "PENDING_APPROVAL",       label: "Confirm & Escalate", color: "#1E40AF" };

  // ── PULL: destination requests stock from source ──────────────────────────
  //
  // Role mapping for a PULL (Region WH requests from Main):
  //   Creator/requester (RM at Region)  = destination side
  //   Source manager (NM at Main)       = supply side
  //
  // isTenantMgr (NM/TA/SA) intentionally excluded from destination actions:
  // NM is the *source* for a PULL, so they must see supply-side buttons
  // (issue, dispatch) and NOT destination buttons (receive, complete).
  // Using isDstManager (which includes isTenantMgr) would give NM both sides.
  if (type === "PULL") {
    const map: Partial<Record<TransferStatus, Action[]>> = {};

    // DRAFT: only the creator (RM who raised the request) can submit it.
    // isTenantMgr / any-reviewer guard removed — showing Submit to NM was wrong.
    if (isCreator) map.DRAFT = [review, cancel];

    // PENDING_REVIEW: reviewer outranks creator and is not the creator
    if (canReview) map.PENDING_REVIEW = [toApproval, reject, cancel];

    // PENDING_APPROVAL: approver approves/rejects
    if (canApprove) map.PENDING_APPROVAL = [approve, reject, cancel];

    // APPROVED/ISSUED: source manager issues and dispatches
    if (isSrcManager) {
      map.APPROVED = [issue, cancel];
      map.ISSUED   = [dispatch];
    }

    // IN_TRANSIT/RECEIVED: strictly destination-side.
    // pullDst excludes isTenantMgr so NM (source) never gets receive/complete.
    const pullDst = isDstWH || isCreator;
    if (pullDst) {
      map.IN_TRANSIT         = [markRecv];
      map.PARTIALLY_RECEIVED = [markRecv];
      map.RECEIVED           = [complete];
    }

    return map[status] ?? [];
  }

  // ── PUSH: source proactively sends stock to destination ───────────────────
  //
  // PUSH originates at the source; the destination only receives.
  // isTenantMgr excluded from destination actions for PUSH:
  // NM/TA are typically the *source* of a PUSH, so giving them
  // receive authority via isTenantMgr would let the source receive their
  // own shipment. pushDst uses exact warehouse match only.
  if (type === "PUSH") {
    const map: Partial<Record<TransferStatus, Action[]>> = {};

    // DRAFT: only the creator (the source who initiated the push) can submit
    if (isCreator) map.DRAFT = [toApproval, cancel];

    // PENDING_APPROVAL
    if (canApprove) map.PENDING_APPROVAL = [approve, reject, cancel];

    // APPROVED/ADVISED/ISSUED: source manager advises, issues, and dispatches
    if (isSrcManager) {
      map.APPROVED = [advise, issue, cancel];
      map.ADVISED  = [issue, cancel];
      map.ISSUED   = [dispatch];
    }

    // IN_TRANSIT/RECEIVED: strictly destination-side — exact warehouse match only
    const pushDst = isDstWH;
    if (pushDst) {
      map.IN_TRANSIT         = [markRecv];
      map.PARTIALLY_RECEIVED = [markRecv];
      map.RECEIVED           = [complete];
    }

    return map[status] ?? [];
  }

  // ── SISTER: lateral WH ↔ WH transfer ─────────────────────────────────────
  //
  // SISTER is strictly peer-to-peer between two WH facilities at the same level.
  // Higher-level managers (NM/TA) may approve the escalated request but must NOT
  // see confirm/issue/receive buttons — those belong to the two peer WMs only.
  // isSrcWH and isDstWH use exact warehouse match (never isTenantMgr).
  // canApprove (level ≤ 2, !isCreator) correctly gives NM the PENDING_APPROVAL
  // buttons since the transfer is escalated to NM for approval.
  if (type === "SISTER") {
    const map: Partial<Record<TransferStatus, Action[]>> = {};

    // DRAFT: only the creator (destination WM who raised the request)
    if (isCreator) map.DRAFT = [submitReq, cancel];

    // PENDING_SOURCE_CONFIRM: source WM confirms supply — exact warehouse match only
    if (isSrcWH) map.PENDING_SOURCE_CONFIRM = [confirmSup, reject, cancel];

    // PENDING_DEST_CONFIRM: destination WM re-confirms — exact warehouse match only
    if (isDstWH) map.PENDING_DEST_CONFIRM = [confirmInt, reject, cancel];

    // PENDING_APPROVAL: escalated to NM/TA (canApprove handles level gate)
    if (canApprove) map.PENDING_APPROVAL = [approve, reject, cancel];

    // APPROVED/ISSUED: source WM issues and dispatches — exact warehouse match only
    if (isSrcWH) {
      map.APPROVED = [issue, cancel];
      map.ISSUED   = [dispatch];
    }

    // IN_TRANSIT/RECEIVED: destination WM receives — exact warehouse match only
    if (isDstWH) {
      map.IN_TRANSIT         = [markRecv];
      map.PARTIALLY_RECEIVED = [markRecv];
      map.RECEIVED           = [complete];
    }

    return map[status] ?? [];
  }

  return [];
}

interface ApprovalInfoResponse {
  transfer_id: string;
  required_authority_level: number;
  required_role_display: string;
  is_auto_approve: boolean;
  can_approve: boolean;
  reason: string;
  // Session 6: dynamic routing fields
  current_step?: number;
  total_steps?: number;
  current_approver_user_id?: string | null;
  current_approver_name?: string | null;
  current_approver_position_title?: string | null;
  execution_mode?: string;
  sla_hours?: number | null;
  is_dynamic_routing?: boolean;
  holder_count?: number;
  all_holders?: { user_id: string; name: string }[];
  status_label?: string | null;
}

/**
 * Renders the actions cell for PENDING_APPROVAL transfers.
 * Fetches approval-info to determine if the current user can approve,
 * and shows a dynamic waiting message with the required role if not.
 */
function ApprovalPendingActions({
  transferId,
  isOnline,
  onApprove,
  onReject,
  fallbackActions,
}: {
  transferId: string;
  isOnline: boolean;
  onApprove: (label: string) => void;
  onReject: () => void;
  fallbackActions: Action[];
}) {
  const { data: info, isLoading, isError } = useQuery<ApprovalInfoResponse>({
    queryKey: ["approval-info", transferId],
    queryFn:  () =>
      api.get<ApprovalInfoResponse>(
        `/api/v1/inventory/transfers/${transferId}/approval-info`
      ),
    staleTime: 30_000,
  });

  if (isLoading) {
    return <span className="text-xs text-gray-400">…</span>;
  }

  if (isError || !info) {
    if (!fallbackActions.length) {
      return <span className="text-[11px] text-gray-200">—</span>;
    }
    return (
      <div className="flex gap-1.5 flex-nowrap">
        {fallbackActions.map((a) => (
          <button
            key={a.next}
            disabled={!isOnline}
            onClick={() =>
              a.next === "APPROVED" ? onApprove(a.label) : onReject()
            }
            className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
            style={{
              borderColor: `${a.color}30`,
              background:  isOnline ? `${a.color}15` : "#F3F4F6",
              color:       isOnline ? a.color : "#9CA3AF",
              cursor:      isOnline ? "pointer" : "not-allowed",
            }}
          >
            {a.label}
          </button>
        ))}
      </div>
    );
  }

  if (info.can_approve) {
    const approveLabel = info.is_auto_approve
      ? `✓ Approve (auto — within your authority)`
      : "Approve";
    return (
      <div className="flex gap-1.5 flex-nowrap">
        <button
          disabled={!isOnline}
          onClick={() => onApprove(approveLabel)}
          className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
          style={{
            borderColor: "#05996930",
            background:  isOnline ? "#05996915" : "#F3F4F6",
            color:       isOnline ? "#059669" : "#9CA3AF",
            cursor:      isOnline ? "pointer" : "not-allowed",
          }}
        >
          {approveLabel}
        </button>
        <button
          disabled={!isOnline}
          onClick={onReject}
          className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
          style={{
            borderColor: "#991B1B30",
            background:  isOnline ? "#991B1B15" : "#F3F4F6",
            color:       isOnline ? "#991B1B" : "#9CA3AF",
            cursor:      isOnline ? "pointer" : "not-allowed",
          }}
        >
          Reject
        </button>
      </div>
    );
  }

  // Dynamic routing: show specific assignee name + position title
  if (info.is_dynamic_routing && info.current_approver_name) {
    const step = info.current_step && info.total_steps && info.total_steps > 1
      ? ` (${info.current_step}/${info.total_steps})`
      : "";
    const waitMsg = `Awaiting ${info.current_approver_position_title ?? info.required_role_display}: ${info.current_approver_name}${step}`;
    return <span className="text-[11px] text-gray-400 italic leading-tight">{waitMsg}</span>;
  }

  const waitMsg = info.required_role_display
    ? `${t("approval.awaiting").replace("{role}", info.required_role_display)}${info.reason ? ` (${info.reason})` : ""}`
    : "Awaiting approval";
  return <span className="text-[11px] text-gray-400 italic leading-tight">{waitMsg}</span>;
}

const COLS = ["Reference", "Type", "From", "To", "Product", "Qty", "Status", "Date", "Actions"];

export default function TransfersPage() {
  const { org } = useParams() as { org: string };
  const tenantName = useTenantName(org);
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

  const tenantId = user?.tenantId ?? "";
  const isGateway = !!process.env.NEXT_PUBLIC_API_URL;

  // Hierarchy config — used for dynamic waiting text (level names per org level).
  // Fetched once per page load; stale after 5 minutes.
  interface HierarchyLevel { level_number: number; level_name: string; }
  const { data: hierarchyLevels } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    enabled:  !!tenantId && isGateway,
    staleTime: 300_000,
  });
  const getLevelName = (levelNum: number): string =>
    hierarchyLevels?.find((l) => l.level_number === levelNum)?.level_name
    ?? `Level ${levelNum} Manager`;

  // Approval-info cache — prefetched for every PENDING_APPROVAL transfer so
  // getAvailableActions can use the backend's actual can_approve rather than
  // the coarse frontend estimate (canApprove = level <= 2).
  // useRef keeps the Map stable across re-renders without triggering extra effects.
  const approvalInfoCache = useRef<Map<string, ApprovalInfoResponse>>(new Map());

  // Fetch tenant transfer type configs to show display names instead of PULL/PUSH/SISTER
  const { data: tenantTransferTypes = [] } = useQuery<TenantTransferType[]>({
    queryKey: ["transfer-types-page", tenantId],
    queryFn:  () => api.get<TenantTransferType[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    enabled:  isGateway && !!tenantId,
    staleTime: 60_000,
  });

  function getTypeLabel(underlyingType: TransferType): string {
    const cfg = tenantTransferTypes.find((t) => t.underlying_type === underlyingType);
    return cfg?.display_name ?? TYPE_CLASS[underlyingType]?.label ?? underlyingType;
  }

  const { data: rawTransfers = [], isLoading: transfersLoading } = useQuery<ApiTransfer[]>({
    queryKey: ["transfers", org],
    queryFn:  () =>
      api.get<RawApiTransfer[]>("/api/v1/inventory/transfers")
        .then((rows) => rows.map(normalizeTransfer)),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 15000,
  });

  // Resolve warehouse names: API JOIN may return null when a node exists only in
  // organization_node (not warehouses table). Fall back to effectiveWarehouses by ID.
  const allTransfers = rawTransfers.map((tx) => {
    const fromName = tx.from_warehouse_name ||
      effectiveWarehouses.find((w) => w.id === tx.from_warehouse_id)?.name ||
      tx.from_warehouse_id;
    const toName = tx.to_warehouse_name ||
      effectiveWarehouses.find((w) => w.id === tx.to_warehouse_id)?.name ||
      tx.to_warehouse_id;
    return { ...tx, from_warehouse_name: fromName, to_warehouse_name: toName };
  });

  // Prefetch approval-info for all PENDING_APPROVAL transfers so the Approve/Reject
  // buttons are controlled by the backend's actual required_authority_level.
  // Runs whenever allTransfers changes; only fetches each transfer once.
  useEffect(() => {
    if (!isGateway) return;
    allTransfers
      .filter((t) => t.status === "PENDING_APPROVAL" && !approvalInfoCache.current.has(t.id))
      .forEach((t) => {
        api.get<ApprovalInfoResponse>(`/api/v1/inventory/transfers/${t.id}/approval-info`)
          .then((info) => { approvalInfoCache.current.set(t.id, info); })
          .catch(() => { /* silently ignore — falls back to local canApprove */ });
      });
  }, [allTransfers, isGateway]);  // eslint-disable-line react-hooks/exhaustive-deps

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

  // Org-node warehouses include level_number (needed for canPush) and all nodes
  // even those with no stock yet — covers BUG 3 (canPush) and BUG 4 (name resolution).
  const { warehouses: orgNodeWarehouses } = useWarehouses();

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

  // Prefer org-node list (has level_number for canPush + all nodes regardless of stock).
  // Fall back to analytics-derived list until org-node data loads.
  const effectiveWarehouses = isGatewayMode
    ? (orgNodeWarehouses.length > 0 ? orgNodeWarehouses : gatewayWarehouses)
    : (tenant?.warehouses ?? []);

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
      setToast(t("transfers.offline_error"));
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

        // Case-insensitive comparison — DB may return different casing than cached value.
        // Guard: only abort if we HAVE a cached status to compare against.
        // If transfer is absent from the cache (background refetch cleared it), we
        // cannot detect a stale-cache scenario — proceed to the PATCH in that case.
        if (transfer?.status && fresh.status.toUpperCase() !== transfer.status.toUpperCase()) {
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
      if (next === "APPROVED") {
        const approvalInfo = qc.getQueryData<ApprovalInfoResponse>(["approval-info", id]);
        const toastMsg = approvalInfo?.is_auto_approve
          ? `Transfer auto-approved. ${approvalInfo.required_role_display} has been notified.`
          : `Status updated to APPROVED`;
        setToast(toastMsg);
      } else {
        setToast(`Status updated to ${next.replace(/_/g, " ")}`);
      }
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
            {tenantName ?? org} · {visibleTransfers.length} {t("transfers.active_label")}{user.warehouseId && !["TA","SA","RM","LM"].includes(user.role) ? ` · ${user.warehouseName ?? effectiveWarehouses.find((w) => w.id === user.warehouseId)?.name ?? t("transfers.your_warehouse")}` : ""}
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
                const tb   = { ...(TYPE_CLASS[txn.transfer_type] ?? { cls: "bg-gray-100 text-gray-500", label: txn.transfer_type }), label: getTypeLabel(txn.transfer_type) };
                // Use cached approval-info can_approve when available (populated by the
                // prefetch useEffect above).  Falls back to local estimate on first render.
                const cachedApprInfo = txn.status === "PENDING_APPROVAL"
                  ? (approvalInfoCache.current.get(txn.id)
                      ?? qc.getQueryData<ApprovalInfoResponse>(["approval-info", txn.id]))
                  : undefined;
                const acts    = getAvailableActions(user.role, txn.transfer_type, txn.status, user.warehouseId, txn.from_warehouse_id, txn.to_warehouse_id, txn.quantity, user.id, txn.created_by, txn.created_by_authority_level, cachedApprInfo?.can_approve);
                const waitMsg = acts.length === 0 ? getWaitingMessage(txn.status, txn.from_warehouse_name, txn.to_warehouse_name, txn.created_by_authority_level, getLevelName, txn.transfer_type) : null;
                const busy    = transitioning === txn.id;
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
                      {txn.status === "PENDING_APPROVAL" && cachedApprInfo?.status_label && (
                        <p className="text-[10px] text-gray-400 mt-0.5 leading-tight max-w-[140px]">
                          {cachedApprInfo.status_label}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                      {new Date(txn.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2.5">
                      {busy ? (
                        <span className="text-xs text-gray-400">{t("common.loading")}</span>
                      ) : txn.status === "PENDING_APPROVAL" ? (
                        <ApprovalPendingActions
                          transferId={txn.id}
                          isOnline={isOnline}
                          onApprove={(label) => {
                            setPartialQtyInput(""); setPartialQtyErr("");
                            setConfirmModal({ id: txn.id, next: "APPROVED", label, transfer: txn });
                          }}
                          onReject={() => {
                            setPartialQtyInput(""); setPartialQtyErr("");
                            setConfirmModal({ id: txn.id, next: "REJECTED", label: "Reject", transfer: txn });
                          }}
                          fallbackActions={acts.filter(
                            (a) => a.next === "APPROVED" || a.next === "REJECTED"
                          )}
                        />
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
                      ) : waitMsg ? (
                        <span className="text-[11px] text-gray-400 italic leading-tight">{waitMsg}</span>
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
