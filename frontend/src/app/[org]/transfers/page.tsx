"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { NewTransferPanel } from "@/components/features/transfers/NewTransferPanel";
import { api } from "@/lib/api";

type TransferStatus =
  | "DRAFT" | "SUBMITTED" | "APPROVED" | "IN_TRANSIT" | "RECEIVED" | "CLOSED" | "REJECTED" | "CANCELLED";

interface ApiTransfer {
  id: string; ref: string; product_name: string;
  from_warehouse_name: string; to_warehouse_name: string;
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

const DEMO_TRANSFERS: ApiTransfer[] = [
  { id: "d1", ref: "SHIP-2026-001", product_name: "Multiple SKUs", from_warehouse_name: "Main Production Center", to_warehouse_name: "North WH",           quantity: 1200, notes: "", status: "CLOSED",     created_at: "2026-05-01T08:00:00Z" },
  { id: "d2", ref: "SHIP-2026-002", product_name: "Multiple SKUs", from_warehouse_name: "North WH",              to_warehouse_name: "North-Subcenter WH",   quantity: 480,  notes: "", status: "IN_TRANSIT", created_at: "2026-05-05T09:30:00Z" },
  { id: "d3", ref: "SHIP-2026-003", product_name: "Multiple SKUs", from_warehouse_name: "Main Production Center", to_warehouse_name: "South WH",            quantity: 860,  notes: "", status: "APPROVED",   created_at: "2026-05-07T14:00:00Z" },
  { id: "d4", ref: "SHIP-2026-004", product_name: "Multiple SKUs", from_warehouse_name: "Main Production Center", to_warehouse_name: "East WH",             quantity: 540,  notes: "", status: "DRAFT",      created_at: "2026-05-09T11:00:00Z" },
  { id: "d5", ref: "SHIP-2026-005", product_name: "Multiple SKUs", from_warehouse_name: "South WH",              to_warehouse_name: "West WH",              quantity: 200,  notes: "", status: "REJECTED",   created_at: "2026-05-09T16:00:00Z" },
];

const COLS = ["Reference", "From", "To", "Product", "Quantity", "Status", "Date"];

function TransferRow({ t, accentColor }: { t: ApiTransfer; accentColor: string }) {
  const s = STATUS_STYLE[t.status] ?? { bg: "#F3F4F6", color: "#6B7280" };
  return (
    <tr style={{ background: "#fff", borderBottom: "1px solid #F3F4F6" }}>
      <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: accentColor }}>{t.ref}</td>
      <td style={{ padding: "10px 16px", color: "#374151", fontSize: 13 }}>{t.from_warehouse_name}</td>
      <td style={{ padding: "10px 16px", color: "#374151", fontSize: 13 }}>{t.to_warehouse_name}</td>
      <td style={{ padding: "10px 16px", color: "#6B7280", fontSize: 13 }}>{t.product_name}</td>
      <td style={{ padding: "10px 16px", fontWeight: 600, color: "#111827", fontSize: 13 }}>{t.quantity.toLocaleString()}</td>
      <td style={{ padding: "10px 16px" }}>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3, background: s.bg, color: s.color }}>
          {t.status}
        </span>
      </td>
      <td style={{ padding: "10px 16px", color: "#9CA3AF", fontSize: 12 }}>
        {new Date(t.created_at).toLocaleDateString()}
      </td>
    </tr>
  );
}

export default function TransfersPage() {
  const { org } = useParams() as { org: string };

  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view transfers.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  // Fetch newly created transfers from in-memory API
  const { data: apiTransfers = [] } = useQuery<ApiTransfer[]>({
    queryKey: ["transfers", org],
    queryFn:  () => api.get<ApiTransfer[]>("/api/v1/transfers"),
    staleTime: 0,
  });

  const allTransfers: ApiTransfer[] = [...apiTransfers, ...DEMO_TRANSFERS];

  const stats = {
    draft:      allTransfers.filter((t) => t.status === "DRAFT").length,
    inTransit:  allTransfers.filter((t) => t.status === "IN_TRANSIT").length,
    pending:    allTransfers.filter((t) => ["SUBMITTED", "APPROVED"].includes(t.status)).length,
  };

  return (
    <div style={{ padding: "2rem" }}>
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
          <div key={s.label} style={{
            background: s.bg, color: s.color, fontSize: 12, fontWeight: 700,
            padding: "4px 12px", borderRadius: 20,
          }}>
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
                  <th key={h} style={{
                    padding: "10px 16px", textAlign: "left",
                    fontSize: 11, fontWeight: 700, color: "#6B7280",
                    textTransform: "uppercase", letterSpacing: "0.05em",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allTransfers.map((t) => (
                <TransferRow key={t.id} t={t} accentColor={tenant.color} />
              ))}
            </tbody>
          </table>
        </div>
        {allTransfers.length === 0 && (
          <p style={{ padding: "2rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>
            No transfers yet. Click "+ New Transfer" to create one.
          </p>
        )}
      </div>
    </div>
  );
}
