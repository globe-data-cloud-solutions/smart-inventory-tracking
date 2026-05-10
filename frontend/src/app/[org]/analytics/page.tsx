"use client";

import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, getLowStockProducts, getTotalStock } from "@/lib/demo-data";

export default function AnalyticsPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view analytics.</p>;

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const low = getLowStockProducts(tenant);
  const total = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
  const byWH = tenant.warehouses.map((w) => ({
    name: w.name, units: tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0)
  })).sort((a, b) => b.units - a.units);
  const maxWH = byWH[0]?.units ?? 1;

  return (
    <div style={{ padding: "2rem" }}>
      <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: "0 0 1.5rem" }}>Analytics</h2>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem", marginBottom: "1.5rem" }}>
        {/* Inventory distribution */}
        <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, padding: "1.25rem" }}>
          <p style={{ fontSize: 13, fontWeight: 700, color: "#1F2937", margin: "0 0 1rem" }}>Stock by Location</p>
          {byWH.map((w) => (
            <div key={w.name} style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: "#374151", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "70%" }}>{w.name}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#111827" }}>{w.units.toLocaleString()}</span>
              </div>
              <div style={{ height: 8, background: "#F3F4F6", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${(w.units / maxWH) * 100}%`, background: tenant.color, borderRadius: 4 }} />
              </div>
            </div>
          ))}
        </div>

        {/* Reorder alerts */}
        <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, padding: "1.25rem" }}>
          <p style={{ fontSize: 13, fontWeight: 700, color: "#1F2937", margin: "0 0 1rem" }}>
            Low Stock Alerts <span style={{ background: "#FEE2E2", color: "#DC2626", fontSize: 11, padding: "2px 7px", borderRadius: 3, marginLeft: 6 }}>{low.length}</span>
          </p>
          {low.length === 0 && (
            <p style={{ fontSize: 13, color: "#059669", background: "#F0FDF4", padding: "0.75rem", borderRadius: 4 }}>✓ All products are adequately stocked.</p>
          )}
          {low.map((p) => (
            <div key={p.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid #F3F4F6" }}>
              <div>
                <p style={{ fontSize: 12, fontWeight: 600, color: "#1F2937", margin: 0 }}>{p.name}</p>
                <p style={{ fontSize: 11, color: "#9CA3AF", margin: 0 }}>{p.sku}</p>
              </div>
              <div style={{ textAlign: "right" }}>
                <p style={{ fontSize: 12, fontWeight: 700, color: "#DC2626", margin: 0 }}>{getTotalStock(p).toLocaleString()}</p>
                <p style={{ fontSize: 11, color: "#9CA3AF", margin: 0 }}>Reorder: {p.reorderPoint}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Summary stats */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, padding: "1.25rem" }}>
        <p style={{ fontSize: 13, fontWeight: 700, color: "#1F2937", margin: "0 0 1rem" }}>Inventory Summary</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: "1rem", textAlign: "center" }}>
          {[
            { label: "Total Units", value: total.toLocaleString() },
            { label: "Active SKUs", value: tenant.products.length },
            { label: "Locations",   value: tenant.warehouses.length },
            { label: "Low Stock",   value: low.length },
          ].map((s) => (
            <div key={s.label} style={{ padding: "1rem", background: "#F9FAFB", borderRadius: 4 }}>
              <p style={{ fontSize: "1.5rem", fontWeight: 800, color: "#1B4332", margin: 0 }}>{s.value}</p>
              <p style={{ fontSize: 12, color: "#6B7280", margin: "4px 0 0" }}>{s.label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
