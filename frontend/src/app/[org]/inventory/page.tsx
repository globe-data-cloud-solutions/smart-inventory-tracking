"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SA_ORG_SLUG, getSession } from "@/lib/demo-auth";
import { DEMO_TENANTS, getTotalStock, type DemoProduct } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { AddProductPanel } from "@/components/features/inventory/AddProductPanel";
import { ReceiveStockPanel } from "@/components/features/inventory/ReceiveStockPanel";
import { IssueStockPanel } from "@/components/features/inventory/IssueStockPanel";
import { api } from "@/lib/api";

type ApiProduct = {
  id: string; sku: string; name: string; type_code: string;
  unit: string; pack_size: number; created_at: string;
};

const STATUS_STYLE = (low: boolean) => ({
  display: "inline-flex", alignItems: "center", gap: 5,
  fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 3,
  background: low ? "#FEF2F2" : "#F0FDF4",
  color:      low ? "#DC2626"  : "#059669",
  border:     `1px solid ${low ? "#FECACA" : "#BBF7D0"}`,
});

export default function InventoryPage() {
  const { org } = useParams() as { org: string };
  const user         = getSession();
  const canAddProduct = usePermission("product:create");

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);

  // Fetch newly created products from the API
  const { data: apiProducts = [] } = useQuery<ApiProduct[]>({
    queryKey: ["products", org],
    queryFn:  () => api.get<ApiProduct[]>("/api/v1/products"),
    enabled:  !!tenant && !!user && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  if (!user || org === SA_ORG_SLUG) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view inventory.</p>;
  }
  if (!tenant) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;
  }

  // Demo products (existing stock)
  const demoProducts: DemoProduct[] = user.warehouseId
    ? tenant.products.filter((p) => (p.stock[user.warehouseId!] ?? 0) > 0)
    : tenant.products;

  const getQty = (p: DemoProduct) =>
    user.warehouseId ? (p.stock[user.warehouseId] ?? 0) : getTotalStock(p);

  const categories = [...new Set(demoProducts.map((p) => p.category))];

  const stockCols = ["SKU", "Product", user.warehouseId ? "My Stock" : "Total Stock", "Reorder Point", "Status"];
  const newCols   = ["SKU", "Product", "Type", "Unit", "Pack Size", "Balance", "Status"];

  return (
    <div style={{ padding: "2rem" }}>
      {/* Page header */}
      <div style={{
        marginBottom: "1.5rem", display: "flex", alignItems: "flex-start",
        justifyContent: "space-between", flexWrap: "wrap", gap: 12,
      }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>
            Inventory
          </h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
            {tenant.name} · {user.warehouseId ? user.warehouseName : "All locations"} · {demoProducts.length + apiProducts.length} SKUs
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <ReceiveStockPanel products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
          <IssueStockPanel   products={tenant.products} warehouses={tenant.warehouses} orgSlug={org} />
          {canAddProduct && <AddProductPanel apiBase="/api/v1/products" />}
        </div>
      </div>

      {/* ── Existing demo products grouped by category ── */}
      {categories.map((cat) => {
        const items = demoProducts.filter((p) => p.category === cat);
        return (
          <div key={cat} style={{
            background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4,
            overflow: "hidden", marginBottom: "1.25rem",
          }}>
            <div style={{ height: 3, background: tenant.color }} />
            <div style={{
              padding: "0.75rem 1.25rem", background: "#F9FAFB",
              borderBottom: "2px solid #E5E7EB",
              display: "flex", justifyContent: "space-between",
            }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "#1F2937" }}>{cat}</span>
              <span style={{
                fontSize: 11, background: "#E5E7EB", color: "#6B7280",
                padding: "2px 8px", borderRadius: 3, fontWeight: 700,
              }}>{items.length} products</span>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}>
                    {stockCols.map((h) => (
                      <th key={h} style={{
                        padding: "10px 16px",
                        textAlign: (h.includes("Stock") || h.includes("Reorder")) ? "right" : "left",
                        fontSize: 11, fontWeight: 700, color: "#6B7280",
                        textTransform: "uppercase", letterSpacing: "0.05em",
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((p, idx) => {
                    const qty   = getQty(p);
                    const isLow = qty < p.reorderPoint;
                    return (
                      <tr key={p.id} style={{
                        background: idx % 2 === 0 ? "#fff" : "#FAFAFA",
                        borderBottom: "1px solid #F3F4F6",
                      }}>
                        <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{p.sku}</td>
                        <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                        <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: 700, color: "#111827" }}>{qty.toLocaleString()}</td>
                        <td style={{ padding: "10px 16px", textAlign: "right", color: "#9CA3AF" }}>{p.reorderPoint.toLocaleString()}</td>
                        <td style={{ padding: "10px 16px" }}>
                          <span style={STATUS_STYLE(isLow)}>
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: isLow ? "#DC2626" : "#059669" }} />
                            {isLow ? "Low Stock" : "In Stock"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      {/* ── New products created via Add Product panel (balance = 0) ── */}
      {apiProducts.length > 0 && (
        <div style={{
          background: "#fff", border: "1px solid #BBF7D0", borderRadius: 4,
          overflow: "hidden", marginBottom: "1.25rem",
        }}>
          <div style={{ height: 3, background: "#059669" }} />
          <div style={{
            padding: "0.75rem 1.25rem", background: "#F0FDF4",
            borderBottom: "2px solid #BBF7D0",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#166534" }}>New Products</span>
            <span style={{
              fontSize: 11, background: "#DCFCE7", color: "#166534",
              padding: "2px 8px", borderRadius: 3, fontWeight: 700,
            }}>{apiProducts.length} products · awaiting stock receipt</span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#F0FDF4", borderBottom: "1px solid #BBF7D0" }}>
                  {newCols.map((h) => (
                    <th key={h} style={{
                      padding: "10px 16px", textAlign: "left",
                      fontSize: 11, fontWeight: 700, color: "#6B7280",
                      textTransform: "uppercase", letterSpacing: "0.05em",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {apiProducts.map((p, idx) => (
                  <tr key={p.id} style={{
                    background: idx % 2 === 0 ? "#fff" : "#FAFAFA",
                    borderBottom: "1px solid #F3F4F6",
                  }}>
                    <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>
                      {p.sku}
                      <span style={{
                        marginLeft: 6, fontSize: 10, fontWeight: 700,
                        background: "#DCFCE7", color: "#166534",
                        padding: "1px 5px", borderRadius: 3,
                      }}>NEW</span>
                    </td>
                    <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                    <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.type_code}</td>
                    <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.unit}</td>
                    <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.pack_size}</td>
                    <td style={{ padding: "10px 16px", fontWeight: 700, color: "#9CA3AF" }}>0</td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 3,
                        background: "#FEF9C3", color: "#854D0E",
                        border: "1px solid #FDE68A",
                      }}>
                        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#854D0E" }} />
                        No Stock
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
