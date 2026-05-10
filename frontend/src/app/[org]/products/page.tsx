"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, getTotalStock } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { AddProductPanel } from "@/components/features/inventory/AddProductPanel";
import { api } from "@/lib/api";

type ApiProduct = {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; created_at: string;
};

type Row = {
  id: string; sku: string; name: string;
  category: string; unit: string; packSize: string;
  balance: number; batchTracking: boolean; isNew: boolean;
};

export default function ProductsPage() {
  const { org } = useParams() as { org: string };
  const canAdd = usePermission("product:create");

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);

  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!tenant && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  if (org === SA_ORG_SLUG) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view products.</p>;
  }
  if (!tenant) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;
  }

  // Merge demo products (static) + API products (newly created)
  const demoRows: Row[] = tenant.products.map((p) => ({
    id: p.id, sku: p.sku, name: p.name,
    category: p.category, unit: p.unit, packSize: "—",
    balance: getTotalStock(p), batchTracking: p.batchTracking, isNew: false,
  }));

  const apiRows: Row[] = apiProducts.map((p) => ({
    id: p.id, sku: p.sku, name: p.name,
    category: p.type_code, unit: p.unit, packSize: String(p.pack_size),
    balance: 0, batchTracking: false, isNew: true,
  }));

  const all = [...demoRows, ...apiRows];
  const total = all.length;

  const COLS = ["SKU", "Product Name", "Category / Type", "Unit", "Pack Size", "Balance", "Batch"];

  return (
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{
        marginBottom: "1.5rem", display: "flex", alignItems: "flex-start",
        justifyContent: "space-between", flexWrap: "wrap", gap: 12,
      }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>
            Products
          </h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
            {tenant.name} · {total} SKUs
            {apiProducts.length > 0 && (
              <span style={{
                marginLeft: 8, fontSize: 11, fontWeight: 700,
                background: "#DCFCE7", color: "#166534",
                padding: "1px 7px", borderRadius: 99,
              }}>
                {apiProducts.length} new
              </span>
            )}
          </p>
        </div>
        {canAdd && <AddProductPanel apiBase="/api/v1/products" />}
      </div>

      {/* Table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
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
              {all.map((p, idx) => (
                <tr key={p.id} style={{
                  background: idx % 2 === 0 ? "#fff" : "#FAFAFA",
                  borderBottom: "1px solid #F3F4F6",
                }}>
                  <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>
                    {p.sku}
                    {p.isNew && (
                      <span style={{
                        marginLeft: 6, fontSize: 10, fontWeight: 700,
                        background: "#DCFCE7", color: "#166534",
                        padding: "1px 5px", borderRadius: 3,
                      }}>NEW</span>
                    )}
                  </td>
                  <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                  <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.category}</td>
                  <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.unit}</td>
                  <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.packSize}</td>
                  <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: 700,
                    color: p.balance > 0 ? "#111827" : "#9CA3AF" }}>
                    {p.balance > 0 ? p.balance.toLocaleString() : "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 3,
                      background: p.batchTracking ? "#DCFCE7" : "#F3F4F6",
                      color: p.batchTracking ? "#166534" : "#6B7280",
                    }}>
                      {p.batchTracking ? "Yes" : "No"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
