"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoTenant } from "@/lib/demo-data";

const DARK = "#0f2d1f";

interface LotRecord {
  lot_number: string;
  product_id: string;
  product_name: string;
  product_sku: string;
  warehouse_id: string;
  warehouse_name: string;
  quantity: number;
  received_at: string;
  expiry_date: string | null;
  status: "ACTIVE" | "DEPLETED" | "EXPIRED";
}

const STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  ACTIVE:   { bg: "#DCFCE7", color: "#166534" },
  DEPLETED: { bg: "#F3F4F6", color: "#9CA3AF" },
  EXPIRED:  { bg: "#FEE2E2", color: "#991B1B" },
};

function daysUntilExpiry(expiry: string | null): number | null {
  if (!expiry) return null;
  return Math.round((new Date(expiry).getTime() - Date.now()) / 86_400_000);
}

/** Deterministically generate lot records from this tenant's batch-tracked products. */
function buildTenantLots(tenant: DemoTenant): LotRecord[] {
  const results: LotRecord[] = [];
  const year = 2026;
  let seq = 1;

  for (const p of tenant.products.filter((p) => p.batchTracking)) {
    const lotNum  = `LOT-${year}-${String(seq).padStart(3, "0")}`;
    // Deterministic date based on seq so it doesn't flicker on re-render
    const month   = String((seq % 4) + 1).padStart(2, "0");
    const recvd   = `${year}-${month}-01`;
    const expiry  = `${year + 1}-${month}-01`;
    seq++;

    for (const [whId, qty] of Object.entries(p.stock)) {
      const wh = tenant.warehouses.find((w) => w.id === whId);
      if (!wh) continue;

      const expDays = daysUntilExpiry(expiry);
      const status: LotRecord["status"] =
        qty === 0            ? "DEPLETED"
        : expDays !== null && expDays < 0 ? "EXPIRED"
        : "ACTIVE";

      results.push({
        lot_number:     lotNum,
        product_id:     p.id,
        product_name:   p.name,
        product_sku:    p.sku,
        warehouse_id:   whId,
        warehouse_name: wh.name,
        quantity:       qty,
        received_at:    recvd,
        expiry_date:    expiry,
        status,
      });
    }
  }

  return results;
}

export default function LotsPage() {
  const { org } = useParams() as { org: string };
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "ACTIVE" | "DEPLETED" | "EXPIRED">("ALL");

  if (org === SA_ORG_SLUG)
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view lots.</p>;

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant)
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const tenantLots = buildTenantLots(tenant);

  if (tenantLots.length === 0) {
    return (
      <div style={{ padding: "2rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Lot Traceability</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 1.5rem" }}>
          {tenant.name} · No batch-tracked products configured
        </p>
        <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 6, padding: "3rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>
          Enable batch tracking on a product to see lot data here.
        </div>
      </div>
    );
  }

  const counts = {
    ACTIVE:   tenantLots.filter((l) => l.status === "ACTIVE").length,
    DEPLETED: tenantLots.filter((l) => l.status === "DEPLETED").length,
    EXPIRED:  tenantLots.filter((l) => l.status === "EXPIRED").length,
  };

  const filtered = tenantLots.filter((l) => {
    const matchSearch =
      !search.trim() ||
      l.lot_number.toLowerCase().includes(search.toLowerCase()) ||
      l.product_sku.toLowerCase().includes(search.toLowerCase()) ||
      l.product_name.toLowerCase().includes(search.toLowerCase());
    const matchStatus = statusFilter === "ALL" || l.status === statusFilter;
    return matchSearch && matchStatus;
  });

  const uniqueLots = Array.from(new Set(filtered.map((l) => l.lot_number)));

  return (
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Lot Traceability</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
          {tenant.name} · Batch-tracked products across all warehouse locations
        </p>
      </div>

      {/* Search + filter */}
      <div style={{ display: "flex", gap: 12, marginBottom: "1.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ position: "relative", flex: 1, minWidth: 240 }}>
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", fontSize: 14, color: "#9CA3AF" }}>🔍</span>
          <input
            type="text" value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search lot number, SKU or product…"
            style={{ width: "100%", padding: "9px 10px 9px 32px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", boxSizing: "border-box" as const }}
          />
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["ALL", "ACTIVE", "DEPLETED", "EXPIRED"] as const).map((s) => {
            const count = s === "ALL" ? tenantLots.length : counts[s];
            const st = s !== "ALL" ? (STATUS_STYLE[s] ?? { bg: "#F3F4F6", color: "#374151" }) : { bg: "#F3F4F6", color: "#374151" };
            return (
              <button key={s} onClick={() => setStatusFilter(s)} style={{
                fontSize: 12, fontWeight: 700, padding: "4px 12px", borderRadius: 20, cursor: "pointer",
                border: statusFilter === s ? "2px solid #0f2d1f" : "2px solid #E5E7EB",
                background: statusFilter === s ? st.bg : "#fff",
                color: statusFilter === s ? st.color : "#6B7280",
              }}>{s} ({count})</button>
            );
          })}
        </div>
      </div>

      {/* Results grouped by lot number */}
      {uniqueLots.length === 0 ? (
        <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 6, padding: "3rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>
          No lots found matching your search.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          {uniqueLots.map((lotNum) => {
            const rows     = filtered.filter((l) => l.lot_number === lotNum);
            const first    = rows[0]!;
            const total    = rows.reduce((a, r) => a + r.quantity, 0);
            const expDays  = daysUntilExpiry(first.expiry_date);
            const expSoon  = expDays !== null && expDays >= 0 && expDays <= 30;
            const expired  = expDays !== null && expDays < 0;
            const st       = STATUS_STYLE[first.status] ?? { bg: "#F3F4F6", color: "#6B7280" };

            return (
              <div key={lotNum} style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 6, overflow: "hidden" }}>
                {/* Lot header */}
                <div style={{ padding: "0.875rem 1.25rem", background: "#F9FAFB", borderBottom: "2px solid #E5E7EB", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontFamily: "monospace", fontSize: 14, fontWeight: 700, color: "#1F2937" }}>{lotNum}</span>
                    <span style={{ fontSize: 11, fontWeight: 700, background: st.bg, color: st.color, padding: "2px 8px", borderRadius: 3 }}>{first.status}</span>
                    {expSoon && <span style={{ fontSize: 11, fontWeight: 700, background: "#FEF3C7", color: "#92400E", padding: "2px 8px", borderRadius: 3 }}>⚠ Expires in {expDays}d</span>}
                    {expired && <span style={{ fontSize: 11, fontWeight: 700, background: "#FEE2E2", color: "#991B1B", padding: "2px 8px", borderRadius: 3 }}>Expired {Math.abs(expDays!)}d ago</span>}
                  </div>
                  <div style={{ display: "flex", gap: 20, fontSize: 12, color: "#6B7280", flexWrap: "wrap" }}>
                    <span><strong style={{ color: "#1F2937" }}>{first.product_name}</strong> · {first.product_sku}</span>
                    <span>Total: <strong style={{ color: "#1B4332" }}>{total.toLocaleString()}</strong> units</span>
                    {first.expiry_date && <span>Expires: <strong style={{ color: expired ? "#DC2626" : "#374151" }}>{first.expiry_date}</strong></span>}
                    <span>Received: {first.received_at}</span>
                  </div>
                </div>

                {/* Location breakdown */}
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: "#FAFAFA" }}>
                      {["Warehouse", "Location Type", "Quantity", "% of Lot"].map((h) => (
                        <th key={h} style={{ padding: "8px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => {
                      const wh  = tenant.warehouses.find((w) => w.id === r.warehouse_id);
                      const pct = total > 0 ? Math.round((r.quantity / total) * 100) : 0;
                      return (
                        <tr key={i} style={{ borderTop: "1px solid #F3F4F6" }}>
                          <td style={{ padding: "9px 14px", fontWeight: 600, color: "#1F2937" }}>{r.warehouse_name}</td>
                          <td style={{ padding: "9px 14px" }}>
                            <span style={{ fontSize: 11, fontWeight: 700, background: "#F3F4F6", color: "#374151", padding: "2px 6px", borderRadius: 3 }}>
                              {wh?.type ?? "WAREHOUSE"}
                            </span>
                          </td>
                          <td style={{ padding: "9px 14px", fontWeight: 700, color: r.quantity > 0 ? "#1B4332" : "#9CA3AF" }}>
                            {r.quantity.toLocaleString()}
                          </td>
                          <td style={{ padding: "9px 14px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <div style={{ flex: 1, height: 6, background: "#F3F4F6", borderRadius: 3, overflow: "hidden", maxWidth: 80 }}>
                                <div style={{ height: "100%", width: `${pct}%`, background: tenant.color, borderRadius: 3 }} />
                              </div>
                              <span style={{ fontSize: 12, color: "#6B7280" }}>{pct}%</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
