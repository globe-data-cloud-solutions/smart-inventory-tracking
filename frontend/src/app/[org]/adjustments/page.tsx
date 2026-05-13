"use client";

import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoTenant } from "@/lib/demo-data";
import { NewAdjustmentPanel } from "@/components/features/inventory/NewAdjustmentPanel";
import { api } from "@/lib/api";

type AdjStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "APPLIED" | "REJECTED" | "CANCELLED";

interface AdjRecord {
  id: string; product_name: string; product_sku: string;
  warehouse_name: string; quantity: number; reason_code: string;
  notes: string; status: AdjStatus; approval_required_role: "NONE" | "RM" | "NM";
  created_at: string;
}

const STATUS_STYLE: Record<AdjStatus, { bg: string; color: string }> = {
  DRAFT:     { bg: "#F3F4F6", color: "#6B7280" },
  SUBMITTED: { bg: "#DBEAFE", color: "#1E40AF" },
  APPROVED:  { bg: "#D1FAE5", color: "#065F46" },
  APPLIED:   { bg: "#DCFCE7", color: "#166534" },
  REJECTED:  { bg: "#FEE2E2", color: "#991B1B" },
  CANCELLED: { bg: "#F3F4F6", color: "#9CA3AF" },
};

const REASONS = ["DAMAGE", "COUNT_VARIANCE", "EXPIRY", "SUPPLIER_RETURN", "SAMPLE"];
const NOTES   = ["Moisture exposure", "Count discrepancy resolved", "Expired batch disposed", "Transit damage on return", "Promotion sample"];

/** Build seed adjustments from this tenant's own products — no hardcoded cross-tenant data. */
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

// Which roles can approve/reject which pending adjustments
const CAN_APPROVE: Record<string, string[]> = {
  RM: ["RM"], NM: ["RM", "NM"], TA: ["RM", "NM"], SA: ["RM", "NM"],
};

export default function AdjustmentsPage() {
  const { org }  = useParams() as { org: string };
  const user     = getSession();
  const qc       = useQueryClient();

  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view adjustments.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant || !user) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

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
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>Adjustments</h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>{tenant.name} · Stock corrections and write-offs</p>
        </div>
        <NewAdjustmentPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
      </div>

      {/* Approval queue — visible to RM/NM/TA/SA */}
      {myPending.length > 0 && (
        <div style={{ background: "#FEF3C7", border: "1px solid #FDE68A", borderRadius: 6, padding: "1rem 1.25rem", marginBottom: "1.5rem" }}>
          <p style={{ fontWeight: 700, fontSize: 14, color: "#92400E", margin: "0 0 0.75rem" }}>
            Pending Your Approval ({myPending.length})
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {myPending.map((a) => (
              <div key={a.id} style={{ background: "#fff", border: "1px solid #FDE68A", borderRadius: 6, padding: "0.875rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                <div>
                  <p style={{ fontWeight: 700, fontSize: 13, color: "#1F2937", margin: 0 }}>{a.product_name}</p>
                  <p style={{ fontSize: 12, color: "#6B7280", margin: "2px 0 0" }}>
                    {a.warehouse_name} · {a.reason_code.replace(/_/g, " ")} · {a.quantity > 0 ? "+" : ""}{a.quantity} units
                  </p>
                  {a.notes && <p style={{ fontSize: 12, color: "#9CA3AF", margin: "2px 0 0", fontStyle: "italic" }}>{a.notes}</p>}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => transition(a.id, "APPROVED")}
                    style={{ padding: "6px 14px", background: "#DCFCE7", color: "#166534", border: "1px solid #BBF7D0", borderRadius: 4, fontSize: 12, fontWeight: 700, cursor: "pointer" }}
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => transition(a.id, "REJECTED")}
                    style={{ padding: "6px 14px", background: "#FEE2E2", color: "#991B1B", border: "1px solid #FECACA", borderRadius: 4, fontSize: 12, fontWeight: 700, cursor: "pointer" }}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Full adjustments table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                {["Date", "SKU", "Product", "Warehouse", "Quantity", "Reason", "Approval", "Status"].map((h) => (
                  <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allAdj.map((a, idx) => {
                const s = STATUS_STYLE[a.status];
                return (
                  <tr key={a.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "9px 14px", color: "#9CA3AF", fontSize: 12, whiteSpace: "nowrap" }}>{new Date(a.created_at).toLocaleDateString()}</td>
                    <td style={{ padding: "9px 14px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{a.product_sku}</td>
                    <td style={{ padding: "9px 14px", fontWeight: 600, color: "#1F2937" }}>{a.product_name}</td>
                    <td style={{ padding: "9px 14px", color: "#374151" }}>{a.warehouse_name}</td>
                    <td style={{ padding: "9px 14px", fontWeight: 700, color: a.quantity < 0 ? "#DC2626" : "#059669" }}>
                      {a.quantity > 0 ? "+" : ""}{a.quantity.toLocaleString()}
                    </td>
                    <td style={{ padding: "9px 14px", color: "#6B7280", fontSize: 12 }}>{a.reason_code.replace(/_/g, " ")}</td>
                    <td style={{ padding: "9px 14px" }}>
                      {a.approval_required_role === "NONE"
                        ? <span style={{ fontSize: 11, color: "#9CA3AF" }}>Auto</span>
                        : <span style={{ fontSize: 11, fontWeight: 700, background: "#FEF3C7", color: "#92400E", padding: "2px 7px", borderRadius: 3 }}>{a.approval_required_role}</span>}
                    </td>
                    <td style={{ padding: "9px 14px" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3, background: s.bg, color: s.color }}>
                        {a.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {allAdj.length === 0 && (
          <p style={{ padding: "2rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>No adjustments yet. Click "+ New Adjustment" to create one.</p>
        )}
      </div>
    </div>
  );
}
