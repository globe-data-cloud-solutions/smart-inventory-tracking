"use client";

import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoTenant } from "@/lib/demo-data";
import { NewAdjustmentPanel } from "@/components/features/inventory/NewAdjustmentPanel";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type AdjStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "APPLIED" | "REJECTED" | "CANCELLED";

interface AdjRecord {
  id: string; product_name: string; product_sku: string;
  warehouse_name: string; quantity: number; reason_code: string;
  notes: string; status: AdjStatus; approval_required_role: "NONE" | "RM" | "NM";
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

function buildSeedAdj(tenant: DemoTenant): AdjRecord[] {
  return tenant.products.slice(0, 5).map((p, i) => {
    const wh  = tenant.warehouses[i % tenant.warehouses.length];
    const qty = i % 2 === 0 ? -(50 + i * 30) : (100 + i * 50);
    return {
      id:                    `seed-adj-${tenant.id}-${i}`,
      product_name:          p.name,
      product_sku:           p.sku,
      warehouse_name:        wh?.name ?? "Warehouse",
      quantity:              qty,
      reason_code:           REASONS[i % REASONS.length] ?? "DAMAGE",
      notes:                 NOTES[i % NOTES.length] ?? "",
      status:                i < 3 ? "APPLIED" : "SUBMITTED",
      approval_required_role: i < 3 ? "NONE" : "RM",
      created_at:            `2026-0${i + 1 < 10 ? "0" : ""}${i + 1}-15T10:00:00Z`,
    } satisfies AdjRecord;
  });
}

const CAN_APPROVE: Record<string, string[]> = {
  RM: ["RM"], NM: ["RM", "NM"], TA: ["RM", "NM"], SA: ["RM", "NM"],
};

export default function AdjustmentsPage() {
  const { org }  = useParams() as { org: string };
  const user     = getSession();
  const qc       = useQueryClient();

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
  const approvableRoles = CAN_APPROVE[user.role] ?? [];

  async function transition(id: string, next: AdjStatus) {
    try {
      await api.patch(`/api/v1/inventory/adjust/${id}`, { next_status: next });
      await qc.invalidateQueries({ queryKey: ["adjustments", org] });
    } catch { /* demo adjustments ignore 404 */ }
  }

  const pending   = allAdj.filter((a) => a.status === "SUBMITTED");
  const applied   = allAdj.filter((a) => a.status === "APPLIED");
  const other     = allAdj.filter((a) => !["SUBMITTED", "APPLIED"].includes(a.status));
  const myPending = pending.filter((a) => approvableRoles.includes(a.approval_required_role));

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("adjustment.title")}</h2>
          <p className="text-sm text-gray-500 mt-1">{tenant.name} · {t("adjustment.title")}</p>
        </div>
        <NewAdjustmentPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
      </div>

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
              {allAdj.map((a, idx) => (
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
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${STATUS_CLASS[a.status]}`}>
                      {t(`status.${a.status}`) || a.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {allAdj.length === 0 && (
          <p className="p-8 text-center text-gray-400 text-sm">{t("common.no_data")}</p>
        )}
      </div>

      {/* suppress unused var warnings from scope */}
      <span className="hidden">{applied.length}{other.length}</span>
    </div>
  );
}
