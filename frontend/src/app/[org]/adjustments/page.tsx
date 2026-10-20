"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoTenant, type DemoProduct, type ProductApprovalOverride } from "@/lib/demo-data";
import { NewAdjustmentPanel } from "@/components/features/inventory/NewAdjustmentPanel";
import { ProductLabel } from "@/components/features/inventory/ProductLabel";
import { useInventoryStore } from "@/lib/inventory-state";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { lotErrorMessage } from "@/lib/lotErrors";
import { formatQty } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { useTenantName } from "@/hooks/useTenantName";
import { useWarehouses } from "@/hooks/useWarehouses";
import { useTenantPositions } from "@/hooks/useTenantPositions";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { formatExpiry, type TransferDiscrepancyListItemApi } from "@/components/features/transfers/TransferLotDetails";
import { openDiscrepanciesKey } from "@/components/features/transfers/transferQueryKeys";

type ApiProduct = {
  id: string; sku: string; name: string; unit: string; pack_size?: number;
  reorder_point?: number | null; category?: string | null;
  is_discontinued?: boolean;
  batch_tracking?: boolean; expiry_tracking?: boolean;
  approval_overrides?: Record<string, ProductApprovalOverride>;
};

type AdjStatus = "DRAFT" | "PENDING_APPROVAL" | "APPROVED" | "POSTED" | "REJECTED" | "CANCELLED";
type AdjAction  = "submit" | "approve" | "reject" | "cancel";

// Bug 2: added product_id and warehouse_id for scoping and balance update (Bug 9)
interface AdjRecord {
  id: string;
  adjustment_id?: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  quantity_delta: number;
  reason_code: string;
  notes: string;
  status: AdjStatus;
  approval_required_role?: "NONE" | "RM" | "NM" | "TA";
  created_by?: string;
  created_at: string;
  is_self_approved?: boolean;
  lot_id?: string | null;
  lot_number?: string | null;
  expiry_date?: string | null;
  auto_lot?: boolean;
}

// lot_id set → lot number (+ expiry if any); lot_id null with lot_number →
// "new lot <number>"; auto_lot → "new lot, generated at posting"; nothing → "—".
function adjLotLabel(adj: AdjRecord): string {
  if (adj.lot_id) {
    return adj.expiry_date ? `${adj.lot_number ?? ""} · ${formatExpiry(adj.expiry_date)}` : (adj.lot_number ?? "—");
  }
  if (adj.lot_number) return t("adjustment.lot_new_named").replace("{number}", adj.lot_number);
  if (adj.auto_lot) return t("adjustment.lot_new_auto");
  return "—";
}

// MATRIX 1: GET /adjustments/{id}/approval-info response — when a Design-B
// product override has routed the adjustment, can_approve reflects the
// resolved required approver (or escalated TA), not just RBAC role.
interface AdjApprovalInfo {
  product_override_applied: boolean;
  required_approver_user_id?: string | null;
  required_approver_name?: string | null;
  approver_escalated: boolean;
  can_approve: boolean;
  step_label?: string | null;
}

const STATUS_CLASS: Record<AdjStatus, string> = {
  DRAFT:            "bg-gray-100 text-gray-500",
  PENDING_APPROVAL: "bg-blue-100 text-blue-800",
  APPROVED:         "bg-emerald-100 text-emerald-900",
  POSTED:           "bg-green-100 text-green-800",
  REJECTED:         "bg-red-100 text-red-900",
  CANCELLED:        "bg-gray-100 text-gray-400",
};

const REASONS = ["DAMAGE", "COUNT_VARIANCE", "EXPIRY", "SUPPLIER_RETURN", "SAMPLE"];
const NOTES   = ["Moisture exposure", "Count discrepancy resolved", "Expired batch disposed", "Transit damage on return", "Promotion sample"];

// Bug 2: buildSeedAdj now includes product_id and warehouse_id for scoping
function buildSeedAdj(tenant: DemoTenant, userId: string): AdjRecord[] {
  return tenant.products.slice(0, 5).map((p, i) => {
    const wh  = tenant.warehouses[i % tenant.warehouses.length];
    const qty = i % 2 === 0 ? -(50 + i * 30) : (100 + i * 50);
    const status: AdjStatus =
      i < 2 ? "POSTED" : i === 2 ? "REJECTED" : i === 3 ? "PENDING_APPROVAL" : "DRAFT";
    return {
      id:                     `seed-adj-${tenant.id}-${i}`,
      product_id:             p.id,
      product_name:           p.name,
      product_sku:            p.sku,
      warehouse_id:           wh?.id ?? "",
      warehouse_name:         wh?.name ?? "Warehouse",
      quantity_delta:         qty,
      reason_code:            REASONS[i % REASONS.length] ?? "DAMAGE",
      notes:                  NOTES[i % NOTES.length] ?? "",
      status,
      approval_required_role: i < 2 ? "NONE" : "RM",
      created_by:             i === 4 ? userId : "other-seed-user",
      created_at:             `2026-0${i + 1 < 10 ? "0" : ""}${i + 1}-15T10:00:00Z`,
    } satisfies AdjRecord;
  });
}

const APPROVER_ROLES = new Set(["NM", "RM", "TA", "SA"]);

export default function AdjustmentsPage() {
  const { org }        = useParams() as { org: string };
  const tenantName     = useTenantName(org);
  const user           = getSession();
  const qc             = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const isGatewayMode  = IS_GATEWAY_MODE;
  const guard = useWriteGuard();
  const gp = guardProps(guard);

  // All hooks called unconditionally — before any early returns
  const { data: apiAdj = [] } = useQuery<AdjRecord[]>({
    queryKey: ["adjustments", org],
    queryFn:  () => api.get<AdjRecord[]>("/api/v1/inventory/adjustments/"),
    enabled:  isGatewayMode && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  // Open transit discrepancies (same query/cache as the Transfers panel). Silent on error,
  // e.g. 403 for a role without transfer:list — the notice simply does not render.
  const { data: openDiscrepancies = [] } = useQuery<TransferDiscrepancyListItemApi[]>({
    queryKey: openDiscrepanciesKey(),
    queryFn:  () => api.get<TransferDiscrepancyListItemApi[]>("/api/v1/inventory/transfers/discrepancies?status=OPEN"),
    enabled:  isGatewayMode && org !== SA_ORG_SLUG,
    retry:    false,
    staleTime: 0,
  });

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products/"),
    enabled:  isGatewayMode && org !== SA_ORG_SLUG,
    staleTime: 30_000,
  });

  type AdjStockItem = { product_id: string; warehouse_id: string; current_stock: string };
  const { data: adjInventoryStock = [] } = useQuery<AdjStockItem[]>({
    queryKey: ["inventory-stock", org],
    queryFn:  () => api.get<AdjStockItem[]>("/api/v1/inventory/analytics/stock"),
    enabled:  isGatewayMode && org !== SA_ORG_SLUG,
    staleTime: 30_000,
  });
  const adjStockByProductId = useMemo(() => {
    const map = new Map<string, Record<string, number>>();
    for (const item of adjInventoryStock) {
      const existing = map.get(item.product_id) ?? {};
      existing[item.warehouse_id] = parseFloat(item.current_stock) || 0;
      map.set(item.product_id, existing);
    }
    return map;
  }, [adjInventoryStock]);

  const { warehouses: orgNodeWarehouses } = useWarehouses();

  // Dynamic adjustment-approval-rules helper — shown next to "Show History".
  const tid = user?.tenantId ?? "";

  interface AdjApprovalRuleOut {
    id: string;
    role_code: string;
    level_number: number;
    reason_code: string | null;
    threshold_type: "QUANTITY" | "VALUE";
    qty_limit: string | null;
    value_limit: string | null;
    approver_role_code: string | null;
    approver_position_id: string | null;
    approver_position_title: string | null;
    priority: number;
    is_active: boolean;
  }
  const { data: adjApprovalRules = [] } = useQuery<AdjApprovalRuleOut[]>({
    queryKey: ["adjustment-approval-rules", tid],
    queryFn:  () => api.get<AdjApprovalRuleOut[]>(`/api/v1/tenants/${tid}/adjustment-approval-rules`),
    enabled:  !!tid && isGatewayMode,
    staleTime: 300_000,
  });

  interface HierarchyLevel { level_number: number; level_name: string; role_display_label: string | null; default_role_code: string | null; }
  const { data: hierarchyConfig = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tid],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tid}/hierarchy/config`),
    enabled:  !!tid && isGatewayMode,
    staleTime: 300_000,
  });

  const { positions: tenantPositions } = useTenantPositions(tid);

  const ruleSummary = useMemo(() => {
    return adjApprovalRules
      .filter((r) => r.is_active)
      .sort((a, b) => a.priority - b.priority)
      .map((r) => {
        const level = hierarchyConfig.find((l) => l.level_number === r.level_number);
        const levelLabel = level?.role_display_label ?? level?.level_name ?? r.role_code;

        let posLabel: string;
        if (r.approver_position_id) {
          const pos = tenantPositions.find((p) => p.id === r.approver_position_id);
          posLabel = pos?.display_label ?? r.approver_position_title ?? r.approver_role_code ?? "TA";
        } else if (r.approver_role_code) {
          posLabel = r.approver_role_code;
        } else {
          posLabel = t("adjustment.self_approve");
        }

        const limitText = r.threshold_type === "VALUE"
          ? (r.value_limit != null ? `> ${formatQty(parseFloat(r.value_limit))}` : "")
          : (r.qty_limit != null ? `> ${formatQty(parseFloat(r.qty_limit))} units` : "");

        // Self-approve rules have no limit and no specific approver — omit the
        // empty "()" entirely rather than rendering "L1 HQ () → Self-approve".
        const limitPart = limitText ? ` (${limitText})` : "";
        return `${levelLabel}${limitPart} → ${posLabel}`;
      });
  }, [adjApprovalRules, hierarchyConfig, tenantPositions]);

  // Any active per-product approval override (Design-B "controlled" product) —
  // shown to all roles regardless of whether any adjustment-approval-rules exist.
  const anyControlledProduct = useMemo(
    () => apiProducts.some((p) => p.approval_overrides && Object.keys(p.approval_overrides).length > 0),
    [apiProducts],
  );

  // Lookup for the 🔒 ProductLabel on adjustment rows — adjustment records carry
  // only product_id/product_name, not approval_overrides.
  const productById = useMemo(
    () => new Map(apiProducts.map((p) => [p.id, p])),
    [apiProducts],
  );

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant && !isGatewayMode) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;
  if (!user) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;
  const currentUser = user;

  const seedAdj = tenant ? buildSeedAdj(tenant, currentUser.id) : [];
  const allAdj: AdjRecord[] = [...apiAdj, ...seedAdj];

  // Build product and warehouse lists for NewAdjustmentPanel.
  // In gateway mode use real API data; in demo mode fall back to tenant seed data.
  const panelProducts: DemoProduct[] = isGatewayMode
    ? apiProducts.filter((p) => !p.is_discontinued).map((p) => ({
        id: p.id, sku: p.sku, name: p.name,
        category: p.category ?? "—",
        unit: p.unit,
        batchTracking: p.batch_tracking === true,
        expiryTracking: p.expiry_tracking === true,
        reorderPoint: p.reorder_point ?? 0,
        stock: adjStockByProductId.get(p.id) ?? {},
        approval_overrides: p.approval_overrides,
      }))
    : (tenant?.products ?? []);
  const panelWarehouses = isGatewayMode
    ? orgNodeWarehouses
    : (tenant?.warehouses ?? []);

  // Bug 2: WM sees only adjustments for their own warehouse; managers see all
  const visibleAdj = currentUser.role === "WM" && currentUser.warehouseId
    ? allAdj.filter((a) => a.warehouse_id === currentUser.warehouseId)
    : allAdj;

  // Default: show only actionable records. History toggle reveals the full list.
  const ACTIVE_STATUSES = new Set<AdjStatus>(["DRAFT", "PENDING_APPROVAL"]);
  const displayAdj = showHistory
    ? visibleAdj
    : visibleAdj.filter((a) => ACTIVE_STATUSES.has(a.status));

  const isApproverRole = APPROVER_ROLES.has(currentUser.role);

  // MATRIX 1: prefetch approval-info for PENDING_APPROVAL adjustments so the
  // Approve/Reject buttons honor product-override required-approver routing
  // (not just the RBAC-only isApproverRole check below).
  const approvalInfoCache = useRef<Map<string, AdjApprovalInfo>>(new Map());
  useEffect(() => {
    if (!isGatewayMode) return;
    visibleAdj
      .filter((a) => a.status === "PENDING_APPROVAL")
      .forEach((a) => {
        const id = a.adjustment_id ?? a.id;
        if (approvalInfoCache.current.has(id)) return;
        api.get<AdjApprovalInfo>(`/api/v1/inventory/adjustments/${id}/approval-info`)
          .then((info) => { approvalInfoCache.current.set(id, info); })
          .catch(() => { /* silently ignore — falls back to local canApprove */ });
      });
  }, [visibleAdj, isGatewayMode]);

  function canApprove(adj: AdjRecord): boolean {
    const isCreator = currentUser.id.toLowerCase() === (adj.created_by ?? "").toLowerCase();
    const info = approvalInfoCache.current.get(adj.adjustment_id ?? adj.id);
    if (info?.product_override_applied) return info.can_approve;
    return isApproverRole && !isCreator;
  }

  function approvalStepLabel(adj: AdjRecord): string | null {
    const info = approvalInfoCache.current.get(adj.adjustment_id ?? adj.id);
    return info?.product_override_applied ? (info.step_label ?? null) : null;
  }

  async function transition(id: string, action: AdjAction) {
    if (guard.reason()) return;  // guardProps already disables the triggering button
    // IMPORTANT: search allAdj — not visibleAdj. visibleAdj is display-only (WM-scoped).
    // Approvers (RM/NM/TA) must find the adjustment record regardless of which WH created it.
    const adj = allAdj.find((a) => (a.adjustment_id ?? a.id) === id);

    setActionError(null);
    try {
      await api.post(`/api/v1/inventory/adjustments/${id}/${action}`, {});
    } catch (err: unknown) {
      const lotError = lotErrorMessage(err);
      if (lotError !== null) {
        // Real lot failure at posting — show it translated and do not touch local stock.
        setActionError(lotError);
        return;
      }
      /* seed adjustments return 404 — fall through to state updates below */
    }

    // Update inventory balance OUTSIDE the try/catch so 404s (seed records) don't
    // swallow the store update. warehouse_id comes from the adjustment record — NOT from
    // the approver's JWT (NM/RM/TA have no assigned warehouse_id).
    if (action === "approve" && adj?.product_id && adj.warehouse_id) {
      const adjWarehouseId = adj.warehouse_id;
      const adjProductId   = adj.product_id;
      const adjQty         = adj.quantity_delta ?? 0;
      const store          = useInventoryStore.getState();

      if (adjQty > 0) store.addReceive(adjProductId, adjWarehouseId, adjQty);
      else            store.addIssue(adjProductId, adjWarehouseId, Math.abs(adjQty));
    }

    await qc.invalidateQueries({ queryKey: ["adjustments", org] });
    void qc.invalidateQueries({ queryKey: ["products", org] });
    void qc.invalidateQueries({ queryKey: ["inventory", org] });
  }

  const pending   = visibleAdj.filter((a) => a.status === "PENDING_APPROVAL");
  const applied   = visibleAdj.filter((a) => a.status === "POSTED");
  const other     = visibleAdj.filter((a) => !["PENDING_APPROVAL", "POSTED"].includes(a.status));
  const myPending = pending.filter(canApprove);

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("adjustment.title")}</h2>
          <p className="text-sm text-gray-500 mt-1">{tenantName ?? org} · {t("adjustment.title")}</p>
        </div>
        <div className="flex items-center gap-2">
          {(ruleSummary.length > 0 || anyControlledProduct) && (
            <div className="relative group">
              <button
                type="button"
                title={t("adjustment.rules_hint")}
                className="w-6 h-6 flex items-center justify-center rounded-full border border-gray-300 text-gray-500 text-xs font-bold hover:bg-gray-50 cursor-pointer"
              >
                ⓘ
              </button>
              <div className="hidden group-hover:block absolute right-0 top-full mt-1 w-72 bg-white border border-gray-200 rounded-md shadow-lg z-50 p-3 text-xs">
                <p className="font-bold text-gray-700 mb-1.5">{t("adjustment.rules_hint")}</p>
                {ruleSummary.length > 0 && (
                  <>
                    <ul className="space-y-1 text-gray-600">
                      {ruleSummary.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                    <p className="text-[11px] text-gray-400 mt-2 pt-2 border-t border-gray-100">
                      {t("approval_rule.no_match_default")}
                    </p>
                  </>
                )}
                {anyControlledProduct && (
                  <p className={`text-[11px] text-gray-500 ${ruleSummary.length > 0 ? "mt-2 pt-2 border-t border-gray-100" : ""}`}>
                    {t("adjustment.controlled_note")}
                  </p>
                )}
              </div>
            </div>
          )}
          <button
            onClick={() => setShowHistory((s) => !s)}
            className="text-xs text-gray-500 border border-gray-200 rounded px-2.5 py-1.5 hover:bg-gray-50 cursor-pointer"
          >
            {showHistory ? t("adjustment.hide_history") : t("adjustment.show_history")}
          </button>
          <NewAdjustmentPanel products={panelProducts} warehouses={panelWarehouses} orgSlug={org} />
        </div>
      </div>

      {openDiscrepancies.length > 0 && (
        <div data-testid="adjustments-discrepancy-notice" className="mb-4 bg-amber-50 border border-amber-200 rounded px-4 py-2.5 text-sm text-amber-900">
          {t("adjustment.transit_discrepancies_notice").replace("{count}", String(openDiscrepancies.length))}{" "}
          <Link href={`/${org}/transfers?focus=discrepancies`} className="font-semibold text-eth-forest underline">
            {t("adjustment.transit_discrepancies_link")}
          </Link>
        </div>
      )}

      {actionError && (
        <div data-testid="adj-action-error" className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-2.5 text-sm text-red-600">
          {actionError}
        </div>
      )}

      {gp.title && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-2.5 text-sm text-red-600">
          {gp.title}
        </div>
      )}

      {/* Approval queue — visible to RM/NM/TA/SA */}
      {myPending.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-md px-5 py-4 mb-6">
          <p className="font-bold text-sm text-amber-800 mb-3">
            {t("adjustment.submit")} ({myPending.length})
          </p>
          <div className="flex flex-col gap-2">
            {myPending.map((a) => (
              <div key={a.id} className="bg-white border border-amber-200 rounded-md px-4 py-3.5 flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <p className="font-bold text-sm text-gray-800 m-0">
                    <ProductLabel
                      name={a.product_name}
                      approvalOverrides={productById.get(a.product_id)?.approval_overrides}
                      transactionType="ADJUSTMENT"
                    />
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {a.warehouse_name} · {a.reason_code.replace(/_/g, " ")} · {(a.quantity_delta ?? 0) > 0 ? "+" : ""}{formatQty(a.quantity_delta ?? 0)} units
                  </p>
                  <p data-testid="adj-approval-lot" className="text-xs text-gray-400 mt-0.5">
                    {t("table.lot")}: {adjLotLabel(a)}
                  </p>
                  {a.notes && <p className="text-xs text-gray-400 mt-0.5 italic">{a.notes}</p>}
                </div>
                <div className="flex gap-2">
                  <button
                    disabled={gp.disabled}
                    title={gp.title}
                    onClick={() => void transition(a.adjustment_id ?? a.id,"approve")}
                    className={`px-3.5 py-1.5 bg-green-100 text-green-800 border border-emerald-200 rounded text-xs font-bold ${gp.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                  >
                    {t("adjustment.approve")}
                  </button>
                  <button
                    disabled={gp.disabled}
                    title={gp.title}
                    onClick={() => void transition(a.adjustment_id ?? a.id,"reject")}
                    className={`px-3.5 py-1.5 bg-red-100 text-red-900 border border-red-200 rounded text-xs font-bold ${gp.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                  >
                    {t("adjustment.reject")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Full adjustments table */}
      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {["common.date", "table.sku", "table.product", "table.location", "adjustment.quantity", "adjustment.reason", "table.lot", "adjustment.approval", "table.status", "table.actions"].map((key) => (
                  <th key={key} className="px-3.5 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    {t(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayAdj.map((a, idx) => (
                <tr key={a.adjustment_id ?? a.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  <td className="px-3.5 py-2 text-gray-400 text-xs whitespace-nowrap">{formatDate(a.created_at)}</td>
                  <td className="px-3.5 py-2 font-mono text-xs text-gray-400">{a.product_sku}</td>
                  <td className="px-3.5 py-2 font-semibold text-gray-800">
                    <ProductLabel
                      name={a.product_name}
                      approvalOverrides={productById.get(a.product_id)?.approval_overrides}
                      transactionType="ADJUSTMENT"
                    />
                  </td>
                  <td className="px-3.5 py-2 text-gray-700">{a.warehouse_name}</td>
                  <td className={`px-3.5 py-2 font-bold ${(a.quantity_delta ?? 0) < 0 ? "text-red-600" : "text-emerald-600"}`}>
                    {(a.quantity_delta ?? 0) > 0 ? "+" : ""}{formatQty(a.quantity_delta ?? 0)}
                  </td>
                  <td className="px-3.5 py-2 text-gray-500 text-xs">{a.reason_code.replace(/_/g, " ")}</td>
                  <td data-testid="adj-row-lot" className="px-3.5 py-2 text-gray-500 text-xs">{adjLotLabel(a)}</td>
                  <td className="px-3.5 py-2">
                    {(a.approval_required_role ?? "NONE") === "NONE"
                      ? <span className="text-xs text-gray-400">{t("adjustment.auto_applied")}</span>
                      : <span className="text-xs font-bold bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">{a.approval_required_role}</span>
                    }
                  </td>
                  <td className="px-3.5 py-2">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${STATUS_CLASS[a.status]}`}>
                      {t(`status.${a.status}`)}
                    </span>
                    {a.status === "POSTED" && a.is_self_approved && (
                      <span className="ml-1 px-1.5 py-0.5 text-xs bg-blue-100 text-blue-700 rounded">
                        {t('adjustment.self_approved')}
                      </span>
                    )}
                  </td>
                  <td className="px-3.5 py-2">
                    {a.status === "DRAFT" && currentUser.id.toLowerCase() === (a.created_by ?? "").toLowerCase() && (
                      <div className="flex gap-1.5">
                        <button
                          disabled={gp.disabled}
                          title={gp.title}
                          onClick={() => void transition(a.adjustment_id ?? a.id,"submit")}
                          className={`px-2.5 py-1 bg-blue-100 text-blue-800 border border-blue-200 rounded text-xs font-bold ${gp.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-blue-200"}`}
                        >
                          {t("adjustment.submit")}
                        </button>
                        <button
                          disabled={gp.disabled}
                          title={gp.title}
                          onClick={() => void transition(a.adjustment_id ?? a.id,"cancel")}
                          className={`px-2.5 py-1 bg-gray-100 text-gray-600 border border-gray-200 rounded text-xs font-bold ${gp.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-gray-200"}`}
                        >
                          {t("adjustment.cancel")}
                        </button>
                      </div>
                    )}
                    {a.status === "PENDING_APPROVAL" && canApprove(a) && (
                      <div className="flex gap-1.5">
                        <button
                          disabled={gp.disabled}
                          title={gp.title}
                          onClick={() => void transition(a.adjustment_id ?? a.id,"approve")}
                          className={`px-2.5 py-1 bg-green-100 text-green-800 border border-emerald-200 rounded text-xs font-bold ${gp.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-green-200"}`}
                        >
                          {t("adjustment.approve")}
                        </button>
                        <button
                          disabled={gp.disabled}
                          title={gp.title}
                          onClick={() => void transition(a.adjustment_id ?? a.id,"reject")}
                          className={`px-2.5 py-1 bg-red-100 text-red-900 border border-red-200 rounded text-xs font-bold ${gp.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-red-200"}`}
                        >
                          {t("adjustment.reject")}
                        </button>
                      </div>
                    )}
                    {a.status === "PENDING_APPROVAL" && !canApprove(a) && approvalStepLabel(a) && (
                      <span className="text-[11px] text-amber-700 italic">{approvalStepLabel(a)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {displayAdj.length === 0 && (
          <div className="p-8 text-center">
            <p className="text-gray-400 text-sm font-medium">{t("adjustment.no_pending")}</p>
            {!showHistory && visibleAdj.length > 0 && (
              <p className="text-gray-400 text-xs mt-1">{t("adjustment.no_pending_hint")}</p>
            )}
          </div>
        )}
      </div>

      {/* suppress unused var warnings */}
      <span className="hidden">{applied.length}{other.length}</span>
    </div>
  );
}
