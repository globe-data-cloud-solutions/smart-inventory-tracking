"use client";

import { useParams } from "next/navigation";
import { Fragment, useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoProduct, type DemoWarehouse, type ProductApprovalOverride } from "@/lib/demo-data";
import { NewTransferPanel } from "@/components/features/transfers/NewTransferPanel";
import { ReceiveTransferPanel } from "@/components/features/transfers/ReceiveTransferPanel";
import { notify } from "@/lib/notify";
import { TransferRowDetails, hasLotSplit, transferDetailKey, type TransferReceiptDetail } from "@/components/features/transfers/TransferLotDetails";
import { ApproveLotsPanel, approveFailure, type ApproveFailure, type ApproveLine, type ApproveLotsBody } from "@/components/features/transfers/ApproveLotsPanel";
import { fetchDispatchPreview } from "@/components/features/transfers/DispatchPreview";
import { OpenDiscrepanciesPanel } from "@/components/features/transfers/OpenDiscrepanciesPanel";
import { tf, transferStatusLabel, transferTypeLabel, useTransferTypes } from "@/components/features/transfers/transferLabels";
import { ProductLabel } from "@/components/features/inventory/ProductLabel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { useWarehouses } from "@/hooks/useWarehouses";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";
import { formatQty } from "@/lib/utils";
import { usePermission } from "@/lib/permissions";

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
  approval_overrides?: Record<string, ProductApprovalOverride>;
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
  is_self_approved?: boolean;
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
  is_self_approved?: boolean;
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
    is_self_approved:             raw.is_self_approved ?? false,
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
  hierarchyLevels?: HierarchyLevel[],
): string | null {
  switch (status) {
    case "DRAFT": {
      // PULL: creator is at destination (to_warehouse) — show destination facility.
      // PUSH/SISTER: creator is at source (from_warehouse) — show source facility.
      const submitter = type === "PULL" ? toWarehouseName : fromWarehouseName;
      return tf("transfers.wait.draft", { name: submitter });
    }
    case "PENDING_REVIEW": {
      // Dynamic: derive reviewer level from creator authority level, mapped
      // through the tenant's actual configured hierarchy levels (handles
      // tenants without an LM tier — see getImmediateReviewerLevel).
      if (getLevelName && creatorAuthorityLevel != null && creatorAuthorityLevel > 1) {
        const reviewerLvl = getImmediateReviewerLevel(creatorAuthorityLevel, hierarchyLevels);
        return tf("transfers.wait.review_level", { level: getLevelName(reviewerLvl) });
      }
      return t("transfers.wait.review");
    }
    case "PENDING_APPROVAL":        return t("transfers.wait.approval");
    case "PENDING_SOURCE_CONFIRM":  return tf("transfers.wait.source_confirm", { name: fromWarehouseName });
    case "PENDING_DEST_CONFIRM":    return tf("transfers.wait.dest_confirm", { name: toWarehouseName });
    case "APPROVED":                return tf("transfers.wait.approved", { name: fromWarehouseName });
    case "ADVISED":                 return tf("transfers.wait.advised", { name: fromWarehouseName });
    case "ISSUED":                  return tf("transfers.wait.issued", { name: fromWarehouseName });
    case "IN_TRANSIT":              return tf("transfers.wait.in_transit", { name: toWarehouseName });
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
 * DEMO MODE ONLY. In gateway mode the server scopes GET /inventory/transfers
 * itself (node subtree plus approvers named on a transfer's approval steps),
 * so re-filtering client-side would hide transfers a WM / facility NM must approve.
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
  opensReceive?: boolean; // true for Receive — opens the per-lot receive form (POST /receive)
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

// Badge styling per underlying type; the text comes from transferTypeLabel (tenant name or generic label)
const TYPE_CLASS: Record<TransferType, string> = {
  PULL:   "bg-blue-100   text-blue-800",
  PUSH:   "bg-amber-100  text-amber-800",
  SISTER: "bg-violet-100 text-violet-800",
};

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

/** Inverse of ROLE_AUTHORITY_LEVEL's primary tiers — used to map a stored
 * created_by_authority_level (global scale) back to a canonical role code
 * so it can be located in the tenant's actual hierarchy_config levels. */
const GLOBAL_AUTHORITY_TO_ROLE: Record<number, string> = {
  1: "NM", 2: "RM", 3: "LM", 4: "WM",
};

/** A single level of a tenant's configured org hierarchy (CLAUDE.md §28). */
interface HierarchyLevel {
  level_number: number;
  level_name: string;
  default_role_code?: string | null;
}

/**
 * Resolves the tenant's configured hierarchy level_number for a given role,
 * by matching default_role_code. Falls back to the global ROLE_AUTHORITY_LEVEL
 * scale if the tenant hierarchy isn't loaded or has no matching level
 * (e.g. a 3-level tenant with no LM — see BUG_REPORT.md PENDING_REVIEW fix).
 */
function getTenantLevelForRole(role: string, hierarchyLevels?: HierarchyLevel[]): number {
  const match = hierarchyLevels?.find((l) => l.default_role_code === role);
  return match?.level_number ?? ROLE_AUTHORITY_LEVEL[role] ?? 4;
}

/**
 * Computes the tenant level_number of the immediate reviewer for a transfer
 * created by a user whose stored authority level is creatorAuthorityLevel
 * (global ROLE_AUTHORITY_LEVEL scale).
 *
 * Maps the creator's global level to their role, finds that role's actual
 * level_number in the tenant's configured hierarchy, then returns the next
 * configured level up. This avoids assuming a contiguous 4-level
 * NM/RM/LM/WM hierarchy — a 3-level tenant (NM/RM/WM, no LM) correctly
 * resolves a WM creator's reviewer to RM instead of a non-existent LM.
 */
function getImmediateReviewerLevel(
  creatorAuthorityLevel: number,
  hierarchyLevels?: HierarchyLevel[],
): number {
  if (!hierarchyLevels?.length) {
    return Math.max(1, creatorAuthorityLevel - 1);
  }
  const creatorRole = GLOBAL_AUTHORITY_TO_ROLE[creatorAuthorityLevel] ?? "WM";
  const creatorTenantLevel = getTenantLevelForRole(creatorRole, hierarchyLevels);

  const levelAbove = [...hierarchyLevels]
    .sort((a, b) => b.level_number - a.level_number)
    .find((l) => l.level_number < creatorTenantLevel);

  return levelAbove?.level_number ?? 1;
}

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
  hierarchyLevels?: HierarchyLevel[],
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
  // immediateReviewerLevel is derived from the creator's stored (global-scale)
  // authority level, then mapped through the tenant's actual configured
  // hierarchy levels — handles tenants without an LM tier (3-level orgs),
  // where a WM creator's reviewer is RM, not a non-existent LM.
  const immediateReviewerLevel = getImmediateReviewerLevel(creatorAuthorityLevel ?? 4, hierarchyLevels);
  const userTenantLevel = getTenantLevelForRole(role, hierarchyLevels);
  const canReview = !isCreator
    && creatorAuthorityLevel != null
    && userTenantLevel === immediateReviewerLevel;

  // PENDING_APPROVAL — use the approval-info response when available (canApproveOverride).
  // The override reflects the backend's actual required_authority_level which accounts for
  // self-approval escalation (e.g., NM-created PUSH requires TA/different-NM, not RM).
  // Falls back to level ≤ 2 && !isCreator when approval-info hasn't loaded yet.
  const canApprove = canApproveOverride !== undefined
    ? canApproveOverride
    : (userLevel <= 2 && !isCreator);

  // ── Action definitions (defined once, referenced by all maps) ─────────────
  const approve   : Action = { next: "APPROVED",               label: t("transfers.action.approve"),          color: "#059669" };
  const reject    : Action = { next: "REJECTED",               label: t("transfers.action.reject"),           color: "#991B1B" };
  const cancel    : Action = { next: "CANCELLED",              label: t("transfers.action.cancel"),           color: "#991B1B" };
  const issue     : Action = { next: "ISSUED",                 label: t("transfers.action.issue"),            color: "#065F46" };
  const dispatch  : Action = { next: "IN_TRANSIT",             label: t("transfers.action.dispatch"),         color: "#92400E" };
  // Receive opens the receive form (C2): quantities are confirmed per lot / per line
  // and posted to POST /receive; a short receipt becomes a server-side discrepancy.
  // There is no separate "Partially Received" action.
  const receive   : Action = { next: "RECEIVED",               label: t("transfers.receive.action"), color: "#059669", opensReceive: true };
  const complete  : Action = { next: "COMPLETED",              label: t("transfers.action.complete"),         color: "#374151" };
  const review    : Action = { next: "PENDING_REVIEW",         label: t("transfers.action.submit_review"),   color: "#5B21B6" };
  const toApproval: Action = { next: "PENDING_APPROVAL",       label: t("transfers.action.send_approval"),   color: "#1E40AF" };
  const submitReq : Action = { next: "PENDING_SOURCE_CONFIRM", label: t("transfers.action.submit_request"),   color: "#5B21B6" };
  const confirmSup: Action = { next: "PENDING_DEST_CONFIRM",   label: t("transfers.action.confirm_supply"),   color: "#059669" };
  const confirmInt: Action = { next: "PENDING_APPROVAL",       label: t("transfers.action.confirm_escalate"), color: "#1E40AF" };

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
      map.IN_TRANSIT         = [receive];
      map.PARTIALLY_RECEIVED = [receive];
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

    // APPROVED/ISSUED: source manager issues and dispatches.
    // The Advise step was removed from the UI — operators skipped it in practice.
    // ADVISED state is kept for backward compat: transfers that were already ADVISED
    // before this change still need Issue/Cancel buttons.
    if (isSrcManager) {
      map.APPROVED = [issue, cancel];
      map.ADVISED  = [issue, cancel];
      map.ISSUED   = [dispatch];
    }

    // IN_TRANSIT/RECEIVED: strictly destination-side — exact warehouse match only
    const pushDst = isDstWH;
    if (pushDst) {
      map.IN_TRANSIT         = [receive];
      map.PARTIALLY_RECEIVED = [receive];
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
      map.IN_TRANSIT         = [receive];
      map.PARTIALLY_RECEIVED = [receive];
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
  step_label?: string | null;
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

  const guard = useWriteGuard();
  const gp = guardProps(guard);
  const blocked = !isOnline || gp.disabled;
  const blockedTitle = !isOnline ? t("errors.OFFLINE") : gp.title;

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
            disabled={blocked}
            title={blockedTitle}
            onClick={() =>
              a.next === "APPROVED" ? onApprove(a.label) : onReject()
            }
            className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
            style={{
              borderColor: `${a.color}30`,
              background:  !blocked ? `${a.color}15` : "#F3F4F6",
              color:       !blocked ? a.color : "#9CA3AF",
              cursor:      !blocked ? "pointer" : "not-allowed",
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
      ? t("transfers.action.approve_auto")
      : t("transfers.action.approve");
    return (
      <div className="flex gap-1.5 flex-nowrap">
        <button
          disabled={blocked}
          title={blockedTitle}
          onClick={() => onApprove(approveLabel)}
          className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
          style={{
            borderColor: "#05996930",
            background:  !blocked ? "#05996915" : "#F3F4F6",
            color:       !blocked ? "#059669" : "#9CA3AF",
            cursor:      !blocked ? "pointer" : "not-allowed",
          }}
        >
          {approveLabel}
        </button>
        <button
          disabled={blocked}
          title={blockedTitle}
          onClick={onReject}
          className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
          style={{
            borderColor: "#991B1B30",
            background:  !blocked ? "#991B1B15" : "#F3F4F6",
            color:       !blocked ? "#991B1B" : "#9CA3AF",
            cursor:      !blocked ? "pointer" : "not-allowed",
          }}
        >
          {t("transfers.action.reject")}
        </button>
      </div>
    );
  }

  // Dynamic routing: show specific assignee name + position title
  if (info.is_dynamic_routing && info.current_approver_name) {
    const step = info.current_step && info.total_steps && info.total_steps > 1
      ? ` (${info.current_step}/${info.total_steps})`
      : "";
    const waitMsg = tf("transfers.wait.approver", {
      position: info.current_approver_position_title ?? info.required_role_display,
      name:     info.current_approver_name,
      step,
    });
    return <span className="text-[11px] text-gray-400 italic leading-tight">{waitMsg}</span>;
  }

  const waitMsg = info.required_role_display
    ? `${t("approval.awaiting").replace("{role}", info.required_role_display)}${info.reason ? ` (${info.reason})` : ""}`
    : t("transfers.wait.approval");
  return <span className="text-[11px] text-gray-400 italic leading-tight">{waitMsg}</span>;
}

export default function TransfersPage() {
  const { org } = useParams() as { org: string };
  const tenantName = useTenantName(org);
  const user = getSession();
  const qc   = useQueryClient();
  const { isOnline } = useOfflineSync();
  const guard = useWriteGuard();
  const gp = guardProps(guard);
  // partialReceive (store) is archived: partial receipts are server-side since C2.
  const { updateTransferStatus, getTransferEntry, addTransfer } = useInventoryStore();
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
  const [receiveFor, setReceiveFor] = useState<ApiTransfer | null>(null);
  const [approveFor, setApproveFor] = useState<{ transfer: ApiTransfer; lines: ApproveLine[] } | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const tenantId = user?.tenantId ?? "";
  const isGateway = !!process.env.NEXT_PUBLIC_API_URL;

  // Hierarchy config — used for dynamic waiting text (level names per org level)
  // and for mapping global authority levels to this tenant's actual reviewer levels.
  // Fetched once per page load; stale after 5 minutes.
  const { data: hierarchyLevels } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    enabled:  !!tenantId && isGateway,
    staleTime: 300_000,
  });
  const getLevelName = (levelNum: number): string =>
    hierarchyLevels?.find((l) => l.level_number === levelNum)?.level_name
    ?? tf("transfers.wait.level_fallback", { n: levelNum });

  // Approval-info cache — prefetched for every PENDING_APPROVAL transfer so
  // getAvailableActions can use the backend's actual can_approve rather than
  // the coarse frontend estimate (canApprove = level <= 2).
  // useRef keeps the Map stable across re-renders without triggering extra effects.
  const approvalInfoCache = useRef<Map<string, ApprovalInfoResponse>>(new Map());

  // Tenant transfer type configs: the type badge shows the tenant's own name for the type
  // (generic translated label when there is none, and in demo mode).
  const tenantTransferTypes = useTransferTypes(tenantId);

  const colLabels = [
    t("transfers.col.reference"), t("transfers.col.type"), t("transfers.col.from"), t("transfers.col.to"),
    t("transfers.col.product"), t("transfers.col.qty"), t("transfers.col.status"), t("transfers.col.date"),
    t("transfers.col.actions"),
  ];

  const { data: rawTransfers = [], isLoading: transfersLoading } = useQuery<ApiTransfer[]>({
    queryKey: ["transfers", org],
    queryFn:  () =>
      api.get<RawApiTransfer[]>("/api/v1/inventory/transfers/")
        .then((rows) => rows.map(normalizeTransfer)),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 0,
    refetchInterval: 15000,
  });

  // Everything effectiveWarehouses depends on lives here, above allTransfers (which reads it).
  // Hook order stays unconditional and ahead of the early returns below.
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

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);

  // Config-based: true whenever NEXT_PUBLIC_API_URL is set, regardless of whether
  // inventory_balances has rows yet.  The old stockData.length > 0 check was the
  // root cause of L1 stock doubling — an empty inventory_balances caused
  // isGatewayMode=false, which fell through to demo data paths and Zustand
  // double-counting even though the backend IS configured.
  const isGatewayMode = IS_GATEWAY_MODE;

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

  // Prefer org-node list (has level_number for canPush + all nodes regardless of stock).
  // Fall back to analytics-derived list until org-node data loads.
  const effectiveWarehouses = isGatewayMode
    ? (orgNodeWarehouses.length > 0 ? orgNodeWarehouses : gatewayWarehouses)
    : (tenant?.warehouses ?? []);


  // Resolve warehouse names: API JOIN may return null when a node exists only in
  // organization_node (not warehouses table). Fall back to effectiveWarehouses by ID.
  const allTransfers = rawTransfers.map((tx) => {
    const fromName = tx.from_warehouse_name ||
      effectiveWarehouses.find((w) => w.id === tx.from_warehouse_id)?.name ||
      "—";
    const toName = tx.to_warehouse_name ||
      effectiveWarehouses.find((w) => w.id === tx.to_warehouse_id)?.name ||
      "—";
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
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products/"),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 30_000,
  });

  // Discrepancy resolve (D2): TA / NM / SA tenant-wide, RM within its node subtree.
  // The backend decides scope. Called before the early returns below (rules of hooks).
  const canResolve = usePermission("transfer:resolve_discrepancy", user?.role ?? "");

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("dashboard.tenants_heading")}</p>;
  if (!user) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  // Build stockByProductId from analytics/stock data: productId → { warehouseId: currentStock }
  // This is the source of truth for balances in gateway mode — the products API does not
  // return on_hand or warehouse_id.
  const stockByProductId = new Map<string, Record<string, number>>();
  for (const row of stockData) {
    const existing = stockByProductId.get(row.product_id) ?? {};
    existing[row.warehouse_id] = Number(row.current_stock);
    stockByProductId.set(row.product_id, existing);
  }

  // In gateway mode, always use real API products — never fall back to demo catalog.
  // DEMO_TENANTS is empty (all data is in the DB), so this is now unconditional.
  const mergedProducts: DemoProduct[] = apiProducts.map((p) => ({
    id:            p.id,
    sku:           p.sku,
    name:          p.name,
    category:      p.category ?? p.type_code,
    unit:          p.unit,
    batchTracking: false,
    reorderPoint:  p.reorder_point ?? 0,
    stock:         stockByProductId.get(p.id) ?? {},
    approval_overrides: p.approval_overrides,
  }));
  const productById = new Map(mergedProducts.map((p) => [p.id, p]));

  // Apply hierarchy + role scoping
  const scopedTransfers = isGatewayMode
    ? allTransfers
    : scopeTransfers(allTransfers, user.role, user.warehouseId, effectiveWarehouses);

  // Bug 4: terminal statuses drop to the Audit Log; only active transfers shown here
  const TERMINAL: TransferStatus[] = ["COMPLETED", "CANCELLED", "REJECTED"];
  const visibleTransfers = scopedTransfers.filter((t) => !TERMINAL.includes(t.status));
  const archivedCount = scopedTransfers.filter((t) => TERMINAL.includes(t.status)).length;

  // Approve clicked: the final approver of a transfer with a batch-tracked line gets
  // the lot picker; every other case keeps the plain confirm → PATCH approve.
  async function openApprove(txn: ApiTransfer, label: string) {
    const plainApprove = () => {
      setPartialQtyInput(""); setPartialQtyErr("");
      setConfirmModal({ id: txn.id, next: "APPROVED", label, transfer: txn });
    };
    if (txn.is_self_approved) { plainApprove(); return; }
    setTransitioning(txn.id);
    try {
      const info = await qc.fetchQuery<ApprovalInfoResponse>({
        queryKey: ["approval-info", txn.id],
        queryFn:  () => api.get<ApprovalInfoResponse>(`/api/v1/inventory/transfers/${txn.id}/approval-info`),
        staleTime: 0,
      });
      const isFinalStep = (info.current_step ?? 1) === (info.total_steps ?? 1);
      if (info.is_auto_approve || !isFinalStep) { plainApprove(); return; }

      const detail = await api.get<TransferReceiptDetail>(`/api/v1/inventory/transfers/${txn.id}`);
      const previewed = await Promise.all(
        (detail.lines ?? []).map(async (line) => ({
          line,
          preview: await fetchDispatchPreview(line.product_id, txn.from_warehouse_id, line.quantity),
        })),
      );
      // A null strategy means the line's product is not batch-tracked: no picker for it.
      const batchLines: ApproveLine[] = previewed
        .filter(({ preview }) => preview.strategy !== null)
        .map(({ line, preview }) => ({
          lineId:      line.line_id,
          productId:   line.product_id,
          productName: line.product_name,
          quantity:    Number(line.quantity),
          preview,
        }));
      if (batchLines.length === 0) { plainApprove(); return; }
      setApproveFor({ transfer: txn, lines: batchLines });
    } catch (err: unknown) {
      console.warn("[openApprove] lot picker unavailable, using plain approve:", err);
      plainApprove();
    } finally {
      setTransitioning(null);
    }
  }

  // approve (lot picker only): failures are returned for the panel to show instead of
  // a toast; approve.body switches the request to POST /approve with the chosen lots.
  async function doTransition(
    id: string,
    next: TransferStatus,
    partialQty?: number,
    approve?: { body: ApproveLotsBody | null },
  ): Promise<ApproveFailure | null> {
    if (!user) return null;
    if (isSubmitting) return null;  // prevent double-submit
    if (!isOnline) {
      setConfirmModal(null);
      setToast(t("transfers.offline_error"));
      setTimeout(() => setToast(""), 5000);
      return null;
    }
    const blockedReason = guard.reason();
    if (blockedReason) {
      setConfirmModal(null);
      setToast(blockedReason);
      setTimeout(() => setToast(""), 5000);
      return null;
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
          setToast(tf("transfers.toast.status_changed", { status: transferStatusLabel(freshStatus) }));
          setTimeout(() => setToast(""), 5000);
          return null;
        }
      } catch (prefetchErr: unknown) {
        const pErr = prefetchErr as { status?: number };
        if (pErr.status === 422) {
          // 422 on GET: route validation error or stale ID — refresh rather than proceeding
          // to a PATCH that will also 422. Let the user retry with fresh data.
          await qc.invalidateQueries({ queryKey: ["transfers", org] });
          setToast(t("transfers.toast.state_changed"));
          setTimeout(() => setToast(""), 5000);
          return null;
        }
        // Non-422 failures (network, 404): proceed to the PATCH and handle any error there
        console.warn("[doTransition] pre-fetch GET failed:", prefetchErr);
      }
      // ───────────────────────────────────────────────────────────────────────

      if (approve?.body) {
        // Final approver chose different lots — the server decides if that is permitted.
        await api.post(`/api/v1/inventory/transfers/${id}/approve`, approve.body);
      } else {
        console.log("[doTransition] sending PATCH:", { id, next_status: next, cachedStatus: transfer?.status });
        await api.patch(`/api/v1/inventory/transfers/${id}`, { next_status: next });
      }

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
      if (approve) void qc.invalidateQueries({ queryKey: transferDetailKey(id) });

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
      // archived: the client-only partialReceive(id, partialQty) store call that used to
      // follow here — partial receipts are server-side since C2 (receive form → POST /receive).
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
        quantityStr:   transfer ? `${formatQty(transfer.quantity)} ${transfer.product_name ? "units" : ""}` : undefined,
        fromWarehouse: transfer?.from_warehouse_name,
        toWarehouse:   transfer?.to_warehouse_name,
        notes:         partialQty ? `Batch received: ${formatQty(partialQty)} units` : undefined,
        actedOnBehalfOf:
          (next === "ISSUED" || next === "IN_TRANSIT")
          && user.warehouseId?.toLowerCase() !== transfer?.from_warehouse_id?.toLowerCase()
            ? (transfer?.from_warehouse_name ?? t("common.unknown"))
            : undefined,
      });
      if (next === "APPROVED") {
        const approvalInfo = qc.getQueryData<ApprovalInfoResponse>(["approval-info", id]);
        const toastMsg = approvalInfo?.is_auto_approve
          ? tf("transfers.toast.auto_approved", { role: approvalInfo.required_role_display })
          : tf("transfers.toast.status_updated", { status: transferStatusLabel("APPROVED") });
        setToast(toastMsg);
      } else {
        setToast(tf("transfers.toast.status_updated", { status: transferStatusLabel(next) }));
      }
      setTimeout(() => setToast(""), 3000);
      return null;
    } catch (err: unknown) {
      const apiErr = err as { status?: number; message?: string; code?: string };
      const is422  = apiErr.status === 422;
      const code   = apiErr.code ?? "";
      const msg    = apiErr.message ?? t("transfers.transition_failed");
      // Log full error so browser console shows the exact backend code + message
      console.error("[doTransition] transition failed:", { id, next, status: apiErr.status, code, message: msg, raw: err });
      if (approve) {
        // Lot picker is open: it shows the translated error and keeps the approver's input.
        void qc.invalidateQueries({ queryKey: ["transfers", org] });
        return approveFailure(err);
      }
      const toastMsg = is422
        ? (code ? tf("transfers.toast.invalid_transition_code", { code }) : t("transfers.toast.invalid_transition"))
        : (msg.length <= 80 ? msg : t("transfers.toast.check_permissions"));
      setToast(toastMsg);
      setTimeout(() => setToast(""), 5000);
      // Always refresh on error so the UI reflects the actual backend state
      void qc.invalidateQueries({ queryKey: ["transfers", org] });
      return null;
    } finally {
      setTransitioning(null);
      setIsSubmitting(false);
    }
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(id)) nextSet.delete(id); else nextSet.add(id);
      return nextSet;
    });
  }

  // Receive form submitted: refresh the same queries doTransition refreshes.
  function onReceived(id: string, ref: string, receivedTotal: number, discrepancyCount: number) {
    setReceiveFor(null);
    void qc.invalidateQueries({ queryKey: ["transfers", org] });
    void qc.invalidateQueries({ queryKey: transferDetailKey(id) });
    void qc.invalidateQueries({ queryKey: ["inventory-stock", org] });
    let msg = t("transfers.receive.toast_received").replace("{qty}", formatQty(receivedTotal));
    if (discrepancyCount === 1) {
      msg += ` · ${t("transfers.receive.toast_discrepancy_one")}`;
    } else if (discrepancyCount > 1) {
      msg += ` · ${t("transfers.receive.toast_discrepancies").replace("{count}", String(discrepancyCount))}`;
    }
    notify({ kind: discrepancyCount > 0 ? "warning" : "success", message: `${ref} — ${msg}` });
  }

  function onDiscrepancyResolved() {
    setToast(t("transfers.discrepancies.toast_resolved"));
    setTimeout(() => setToast(""), 5000);
  }

  const stats = {
    draft:     visibleTransfers.filter((t) => t.status === "DRAFT").length,
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
              {confirmModal.label} — {t("transfers.status_will_change")} <strong>{transferStatusLabel(confirmModal.next)}</strong>.
            </p>

            {gp.title && (
              <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
                {gp.title}
              </p>
            )}

            {confirmModal.requiresQty && (() => {
              const storeEntry   = getTransferEntry(confirmModal.id);
              const alreadyRecvd = storeEntry?.receivedQuantity ?? 0;
              const total        = confirmModal.transfer.quantity;
              const remaining    = total - alreadyRecvd;
              return (
                <div className="bg-gray-50 rounded-md px-3.5 py-3 mb-4">
                  <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                    <span>{t("transfers.total_qty")}</span><strong className="text-gray-900">{formatQty(total)}</strong>
                  </div>
                  {alreadyRecvd > 0 && (
                    <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                      <span>{t("transfers.prev_received")}</span><strong className="text-emerald-600">{formatQty(alreadyRecvd)}</strong>
                    </div>
                  )}
                  <div className="flex justify-between text-xs text-gray-500 mb-2.5">
                    <span>{t("transfers.still_in_transit")}</span><strong className="text-amber-800">{formatQty(remaining)}</strong>
                  </div>
                  <label className="block text-[11px] font-bold uppercase tracking-wide text-gray-700 mb-1">
                    {t("transfers.qty_this_batch")}
                  </label>
                  <input
                    type="number" min="1" max={remaining}
                    value={partialQtyInput}
                    onChange={(e) => { setPartialQtyInput(e.target.value); setPartialQtyErr(""); }}
                    placeholder={`1 – ${formatQty(remaining)}`}
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
                disabled={isSubmitting || gp.disabled}
                title={gp.title}
                onClick={() => {
                  if (confirmModal.requiresQty) {
                    const storeEntry = getTransferEntry(confirmModal.id);
                    const remaining  = confirmModal.transfer.quantity - (storeEntry?.receivedQuantity ?? 0);
                    const qty        = parseFloat(partialQtyInput);
                    if (!qty || qty <= 0 || qty > remaining) { setPartialQtyErr(tf("transfers.toast.qty_range", { max: formatQty(remaining) })); return; }
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

      {receiveFor && (
        <ReceiveTransferPanel
          transferId={receiveFor.id}
          transferRef={receiveFor.ref}
          basePath="/api/v1/inventory/transfers"
          onClose={() => setReceiveFor(null)}
          onReceived={(total, count) => onReceived(receiveFor.id, receiveFor.ref, total, count)}
        />
      )}

      {approveFor && (
        <ApproveLotsPanel
          transferRef={approveFor.transfer.ref}
          sourceWarehouseId={approveFor.transfer.from_warehouse_id}
          lines={approveFor.lines}
          onClose={() => setApproveFor(null)}
          onSubmit={async (body) => {
            const failure = await doTransition(approveFor.transfer.id, "APPROVED", undefined, { body });
            if (!failure) setApproveFor(null);
            return failure;
          }}
        />
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

      <OpenDiscrepanciesPanel
        org={org}
        basePath="/api/v1/inventory/transfers"
        canResolve={canResolve}
        productName={(id) => productById.get(id)?.name}
        onResolved={onDiscrepancyResolved}
      />

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {colLabels.map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {transfersLoading && Array.from({ length: 4 }).map((_, i) => (
                <tr key={`skel-${i}`} className={`border-b border-gray-100 ${i % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  {colLabels.map((c) => (
                    <td key={c} className="px-3 py-3">
                      <div className="h-3 rounded bg-gray-200 animate-pulse" style={{ width: `${55 + (i * 13 + c.length * 7) % 35}%` }} />
                    </td>
                  ))}
                </tr>
              ))}
              {!transfersLoading && visibleTransfers.map((txn, idx) => {
                const sCls = STATUS_CLASS[txn.status] ?? "bg-gray-100 text-gray-500";
                const tb   = {
                  cls:   TYPE_CLASS[txn.transfer_type] ?? "bg-gray-100 text-gray-500",
                  label: transferTypeLabel(txn.transfer_type, tenantTransferTypes),
                };
                // Use cached approval-info can_approve when available (populated by the
                // prefetch useEffect above).  Falls back to local estimate on first render.
                const cachedApprInfo = txn.status === "PENDING_APPROVAL"
                  ? (approvalInfoCache.current.get(txn.id)
                      ?? qc.getQueryData<ApprovalInfoResponse>(["approval-info", txn.id]))
                  : undefined;
                const acts    = getAvailableActions(user.role, txn.transfer_type, txn.status, user.warehouseId, txn.from_warehouse_id, txn.to_warehouse_id, txn.quantity, user.id, txn.created_by, txn.created_by_authority_level, cachedApprInfo?.can_approve, hierarchyLevels);
                const waitMsg = acts.length === 0 ? getWaitingMessage(txn.status, txn.from_warehouse_name, txn.to_warehouse_name, txn.created_by_authority_level, getLevelName, txn.transfer_type, hierarchyLevels) : null;
                const busy    = transitioning === txn.id;
                const canExpand  = hasLotSplit(txn.status);
                const isExpanded = canExpand && expanded.has(txn.id);
                return (
                  <Fragment key={txn.id}>
                  <tr className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {canExpand && (
                        <button
                          type="button"
                          onClick={() => toggleExpanded(txn.id)}
                          aria-expanded={isExpanded}
                          aria-label={t("transfers.lots.toggle")}
                          title={t("transfers.lots.toggle")}
                          className="mr-1.5 text-xs text-gray-500 bg-transparent border-0 cursor-pointer p-0 w-4"
                        >
                          {isExpanded ? "▾" : "▸"}
                        </button>
                      )}
                      <Link href={`/${org}/transfers/${txn.id}`} className="font-mono text-xs font-semibold no-underline" style={{ color: tenant?.color ?? "#1B4332" }}>
                        {txn.ref} →
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${tb.cls}`}>{tb.label}</span>
                    </td>
                    <td className="px-3 py-2.5 text-gray-700 text-sm">{txn.from_warehouse_name}</td>
                    <td className="px-3 py-2.5 text-gray-700 text-sm">{txn.to_warehouse_name}</td>
                    <td className="px-3 py-2.5 text-gray-500 text-sm">
                      <ProductLabel
                        name={txn.product_name}
                        approvalOverrides={productById.get(txn.product_id)?.approval_overrides}
                        transactionType={txn.transfer_type}
                      />
                    </td>
                    <td className="px-3 py-2.5 font-semibold text-gray-900 text-sm">
                      {formatQty(txn.quantity ?? 0)}
                      {txn.status === "PARTIALLY_RECEIVED" && (() => {
                        const e = getTransferEntry(txn.id); const rcvd = e?.receivedQuantity ?? 0;
                        return rcvd > 0 ? <span className="block text-[10px] font-medium text-amber-800">{tf("transfers.list.rcvd_rem", { rcvd: formatQty(rcvd), rem: formatQty(Number(txn.quantity ?? 0) - rcvd) })}</span> : null;
                      })()}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[11px] font-bold px-2 py-0.5 rounded whitespace-nowrap ${sCls}`}>
                        {transferStatusLabel(txn.status)}
                      </span>
                      {txn.is_self_approved && (
                        <span
                          title={t("transfers.self_approved_hint")}
                          className="ml-1 text-[10px] font-semibold px-1.5 py-0.5 rounded bg-teal-100 text-teal-800 whitespace-nowrap"
                        >
                          {t("transfers.self_approved")}
                        </span>
                      )}
                      {txn.status === "PENDING_APPROVAL" && cachedApprInfo?.status_label && (
                        <p className="text-[10px] text-gray-400 mt-0.5 leading-tight max-w-[140px]">
                          {cachedApprInfo.status_label}
                        </p>
                      )}
                      {txn.status === "PENDING_APPROVAL" && cachedApprInfo?.step_label && (
                        <p className="text-[10px] font-semibold text-blue-600 mt-0.5">
                          {cachedApprInfo.step_label}
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
                          onApprove={(label) => void openApprove(txn, label)}
                          onReject={() => {
                            setPartialQtyInput(""); setPartialQtyErr("");
                            setConfirmModal({ id: txn.id, next: "REJECTED", label: t("transfers.action.reject"), transfer: txn });
                          }}
                          fallbackActions={acts.filter(
                            (a) => a.next === "APPROVED" || a.next === "REJECTED"
                          )}
                        />
                      ) : acts.length > 0 ? (
                        <div className="flex gap-1.5 flex-nowrap items-center">
                          {!isOnline && <span title={t("errors.OFFLINE")} className="text-[11px] text-gray-400">{t("transfers.list.offline")}</span>}
                          {acts.map((a) => {
                            const rowBlocked = !isOnline || gp.disabled;
                            return (
                            <button
                              key={a.next}
                              disabled={rowBlocked}
                              title={!isOnline ? t("errors.OFFLINE") : gp.title}
                              onClick={() => {
                                if (a.opensReceive) { setReceiveFor(txn); return; }
                                setPartialQtyInput(""); setPartialQtyErr(""); setConfirmModal({ id: txn.id, next: a.next, label: a.label, transfer: txn, requiresQty: a.requiresQty });
                              }}
                              className="text-[11px] font-bold px-2.5 py-1 rounded whitespace-nowrap border"
                              /* action button colors are per-action (a.color) — dynamic, must stay as style */
                              style={{
                                borderColor: `${a.color}30`,
                                cursor:      !rowBlocked ? "pointer" : "not-allowed",
                                background:  !rowBlocked ? `${a.color}15` : "#F3F4F6",
                                color:       !rowBlocked ? a.color : "#9CA3AF",
                                opacity:     !rowBlocked ? 1 : 0.5,
                              }}
                            >
                              {a.label}
                            </button>
                            );
                          })}
                          {acts.some((a) => a.next === "ISSUED" || a.next === "IN_TRANSIT")
                            && user.warehouseId?.toLowerCase() !== txn.from_warehouse_id?.toLowerCase() && (
                            <span className="text-[10px] text-gray-500 italic whitespace-nowrap">
                              {t("transfer.acting_on_behalf").replace("{warehouse}", txn.from_warehouse_name ?? t("common.unknown"))}
                            </span>
                          )}
                        </div>
                      ) : waitMsg ? (
                        <span className="text-[11px] text-gray-400 italic leading-tight">{waitMsg}</span>
                      ) : (
                        <span className="text-[11px] text-gray-200">—</span>
                      )}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="border-b border-gray-100 bg-gray-50">
                      <td colSpan={colLabels.length} className="px-8 py-3">
                        <TransferRowDetails
                          transferId={txn.id}
                          basePath="/api/v1/inventory/transfers"
                          canResolve={canResolve}
                          onResolved={onDiscrepancyResolved}
                        />
                      </td>
                    </tr>
                  )}
                  </Fragment>
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
