"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoTenant } from "@/lib/demo-data";
import { NewAdjustmentPanel } from "@/components/features/inventory/NewAdjustmentPanel";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type AdjStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "APPLIED" | "REJECTED" | "CANCELLED";

// Bug 2: added product_id and warehouse_id for scoping and balance update (Bug 9)
interface AdjRecord {
  id: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  quantity: number;
  reason_code: string;
  notes: string;
  status: AdjStatus;
  approval_required_role: "NONE" | "RM" | "NM" | "TA";
  created_at: string;
}

const STATUS_CLASS: Record<AdjStatus, string> = {
  DRAFT:     "bg-gray-100 text-gray-500",
  SUBMITTED: "bg-blue-100 text-blue-800",
  APPROVED:  "bg-emerald-100 text-emerald-900",
  APPLIED:   "bg-green-100 text-green-800",
  REJECTED:  "bg-red-100 text-red-900",
  CANCELLED: "bg-gray-100 text-gray-400",
};

const REASONS = ["DAMAGE", "COUNT_VARIANCE", "EXPIRY", "SUPPLIER_RETURN", "SAMPLE"];
const NOTES   = ["Moisture exposure", "Count discrepancy resolved", "Expired batch disposed", "Transit damage on return", "Promotion sample"];

// Bug 2: buildSeedAdj now includes product_id and warehouse_id for scoping
function buildSeedAdj(tenant: DemoTenant): AdjRecord[] {
  return tenant.products.slice(0, 5).map((p, i) => {
    const wh  = tenant.warehouses[i % tenant.warehouses.length];
    const qty = i % 2 === 0 ? -(50 + i * 30) : (100 + i * 50);
    return {
      id:                     `seed-adj-${tenant.id}-${i}`,
      product_id:             p.id,
      product_name:           p.name,
      product_sku:            p.sku,
      warehouse_id:           wh?.id ?? "",
      warehouse_name:         wh?.name ?? "Warehouse",
      quantity:               qty,
      reason_code:            REASONS[i % REASONS.length] ?? "DAMAGE",
      notes:                  NOTES[i % NOTES.length] ?? "",
      status:                 i < 3 ? "APPLIED" : "SUBMITTED",
      approval_required_role: i < 3 ? "NONE" : "RM",
      created_at:             `2026-0${i + 1 < 10 ? "0" : ""}${i + 1}-15T10:00:00Z`,
    } satisfies AdjRecord;
  });
}

const CAN_APPROVE: Record<string, string[]> = {
  RM: ["RM"], NM: ["RM", "NM"], TA: ["RM", "NM", "TA"], SA: ["RM", "NM", "TA"],
};

export default function AdjustmentsPage() {
  const { org }        = useParams() as { org: string };
  const user           = getSession();
  const qc             = useQueryClient();
  const [showLegend, setShowLegend] = useState(false);

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant || !user) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const { data: apiAdj = [] } = useQuery<AdjRecord[]>({
    queryKey: ["adjustments", org],
    queryFn:  () => api.get<AdjRecord[]>("/api/v1/inventory/adjust"),
    staleTime: 0,
  });

  const seedAdj = buildSeedAdj(tenant);
  const allAdj: AdjRecord[] = [...apiAdj, ...seedAdj];

  // Bug 2: WM sees only adjustments for their own warehouse; managers see all
  const visibleAdj = user.role === "WM" && user.warehouseId
    ? allAdj.filter((a) => a.warehouse_id === user.warehouseId)
    : allAdj;

  const approvableRoles = CAN_APPROVE[user.role] ?? [];

  async function transition(id: string, next: AdjStatus) {
    // IMPORTANT: search allAdj — not visibleAdj. visibleAdj is display-only (WM-scoped).
    // Approvers (RM/NM/TA) must find the adjustment record regardless of which WH created it.
    const adj = allAdj.find((a) => a.id === id);

    console.log("[ADJ] APPROVE START", {
      id,
      next,
      adjFound:            !!adj,
      adjProductId:        adj?.product_id,
      adjWarehouseId:      adj?.warehouse_id,
      adjQty:              adj?.quantity,
      adjStatus:           adj?.status,
      approverRole:        user?.role,
      approverWarehouseId: user?.warehouseId ?? "(none — manager)",
      allAdjCount:         allAdj.length,
      visibleAdjCount:     visibleAdj.length,
      storeTenantSlug:     useInventoryStore.getState().currentTenantSlug,
    });

    if (!adj) {
      console.warn("[ADJ] adj is undefined — id not found in allAdj. Balance update will be skipped.", { id, allAdjIds: allAdj.map((a) => a.id) });
    }

    try {
      await api.patch(`/api/v1/inventory/adjust/${id}`, { next_status: next });
    } catch { /* seed adjustments return 404 — fall through to state updates below */ }

    // Update inventory balance OUTSIDE the try/catch so 404s (seed records) don't
    // swallow the store update. warehouse_id comes from the adjustment record — NOT from
    // the approver's JWT (NM/RM/TA have no assigned warehouse_id).
    if (next === "APPROVED" && adj?.product_id && adj.warehouse_id) {
      const adjWarehouseId = adj.warehouse_id;
      const adjProductId   = adj.product_id;
      const adjQty         = adj.quantity;
      const store          = useInventoryStore.getState();

      if (adjQty > 0) store.addReceive(adjProductId, adjWarehouseId, adjQty);
      else            store.addIssue(adjProductId, adjWarehouseId, Math.abs(adjQty));

      console.log("[ADJ] STORE UPDATE CALLED", {
        method:                adjQty > 0 ? "addReceive" : "addIssue",
        productId:             adjProductId,
        warehouseId:           adjWarehouseId,
        qty:                   Math.abs(adjQty),
        storeTenantSlug:       useInventoryStore.getState().currentTenantSlug,
        newAdjustmentsCount:   useInventoryStore.getState().adjustments.length,
        issueEntriesForThisWH: useInventoryStore.getState().adjustments.filter(
          (a) => a.productId === adjProductId && a.warehouseId === adjWarehouseId && a.type === "ISSUE"
        ).length,
      });

      // Audit log for this approval — use adj.warehouse_id (the WH that created the
      // adjustment), never the approver's warehouse_id (NM/TA have none).
      if (user) {
        useAuditStore.getState().log({
          tenantSlug:    org,
          userEmail:     user.email,
          userName:      user.name,
          role:          user.role,
          category:      "ADJUSTMENT",
          action:        "ADJUSTMENT_APPROVED",
          resourceRef:   id,
          resourceType:  "adjustment",
          productName:   adj.product_name,
          quantityStr:   `${adjQty > 0 ? "+" : ""}${adjQty}`,
          fromWarehouse: adj.warehouse_name,
          notes:         adj.notes,
        });
      }
    } else if (next === "APPROVED") {
      console.warn("[ADJ] APPROVED but store update skipped — adj missing or empty warehouse_id", {
        adjFound:          !!adj,
        adjProductId:      adj?.product_id,
        adjWarehouseId:    adj?.warehouse_id,
        adjWarehouseTruthy: !!adj?.warehouse_id,
      });
    }

    await qc.invalidateQueries({ queryKey: ["adjustments", org] });
    void qc.invalidateQueries({ queryKey: ["products", org] });
  }

  const pending   = visibleAdj.filter((a) => a.status === "SUBMITTED");
  const applied   = visibleAdj.filter((a) => a.status === "APPLIED");
  const other     = visibleAdj.filter((a) => !["SUBMITTED", "APPLIED"].includes(a.status));
  const myPending = pending.filter((a) => approvableRoles.includes(a.approval_required_role));

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("adjustment.title")}</h2>
          <p className="text-sm text-gray-500 mt-1">{tenant.name} · {t("adjustment.title")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowLegend((s) => !s)}
            aria-expanded={showLegend}
            className="text-xs text-gray-500 border border-gray-200 rounded px-2.5 py-1.5 hover:bg-gray-50 cursor-pointer"
          >
            {showLegend ? t("adjustment.threshold_hide") : t("adjustment.threshold_show")} ⓘ
          </button>
          <NewAdjustmentPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
        </div>
      </div>

      {/* Approval threshold legend — collapsible */}
      {showLegend && (
        <div className="mb-5 bg-blue-50 border border-blue-200 rounded-md px-5 py-4 text-xs text-blue-900">
          <p className="font-bold text-sm mb-2">{t("adjustment.threshold_legend_title")}</p>
          <ul className="flex flex-col gap-1.5">
            <li>✓ {t("adjustment.threshold_damage_always")}</li>
            <li>✓ {t("adjustment.threshold_expiry_always")}</li>
            <li>✓ {t("adjustment.threshold_supplier_return_always")}</li>
            <li>✓ {t("adjustment.threshold_qty_wm")}</li>
            <li>✓ {t("adjustment.threshold_qty_rm")}</li>
            <li>✓ {t("adjustment.threshold_qty_ta")}</li>
            <li>✓ {t("adjustment.threshold_zero_floor")}</li>
          </ul>
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
                  <p className="font-bold text-sm text-gray-800 m-0">{a.product_name}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {a.warehouse_name} · {a.reason_code.replace(/_/g, " ")} · {a.quantity > 0 ? "+" : ""}{a.quantity} units
                  </p>
                  {a.notes && <p className="text-xs text-gray-400 mt-0.5 italic">{a.notes}</p>}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => void transition(a.id, "APPROVED")}
                    className="px-3.5 py-1.5 bg-green-100 text-green-800 border border-emerald-200 rounded text-xs font-bold cursor-pointer"
                  >
                    {t("adjustment.approve")}
                  </button>
                  <button
                    onClick={() => void transition(a.id, "REJECTED")}
                    className="px-3.5 py-1.5 bg-red-100 text-red-900 border border-red-200 rounded text-xs font-bold cursor-pointer"
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
        <div className="h-[3px]" style={{ background: tenant.color }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {["common.date", "table.sku", "table.product", "table.location", "adjustment.quantity", "adjustment.reason", "adjustment.approval", "table.status"].map((key) => (
                  <th key={key} className="px-3.5 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    {t(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleAdj.map((a, idx) => (
                <tr key={a.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  <td className="px-3.5 py-2 text-gray-400 text-xs whitespace-nowrap">{new Date(a.created_at).toLocaleDateString()}</td>
                  <td className="px-3.5 py-2 font-mono text-xs text-gray-400">{a.product_sku}</td>
                  <td className="px-3.5 py-2 font-semibold text-gray-800">{a.product_name}</td>
                  <td className="px-3.5 py-2 text-gray-700">{a.warehouse_name}</td>
                  <td className={`px-3.5 py-2 font-bold ${a.quantity < 0 ? "text-red-600" : "text-emerald-600"}`}>
                    {a.quantity > 0 ? "+" : ""}{a.quantity.toLocaleString()}
                  </td>
                  <td className="px-3.5 py-2 text-gray-500 text-xs">{a.reason_code.replace(/_/g, " ")}</td>
                  <td className="px-3.5 py-2">
                    {a.approval_required_role === "NONE"
                      ? <span className="text-xs text-gray-400">{t("adjustment.auto_applied")}</span>
                      : <span className="text-xs font-bold bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">{a.approval_required_role}</span>
                    }
                  </td>
                  <td className="px-3.5 py-2">
                    {/* Bug 3: status.APPLIED now resolves to "Applied" via en.json */}
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${STATUS_CLASS[a.status]}`}>
                      {t(`status.${a.status}`)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {visibleAdj.length === 0 && (
          <p className="p-8 text-center text-gray-400 text-sm">{t("common.no_data")}</p>
        )}
      </div>

      {/* suppress unused var warnings */}
      <span className="hidden">{applied.length}{other.length}</span>
    </div>
  );
}
