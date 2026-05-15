"use client";

import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";

/**
 * Returns warehouses sorted in depth-first tree order so children always
 * appear immediately after their parent regardless of the raw array order.
 * Handles multiple roots (e.g. Harar chain + Ambo chain side-by-side).
 */
function sortByHierarchy(warehouses: DemoWarehouse[]): DemoWarehouse[] {
  const result: DemoWarehouse[] = [];
  const placed = new Set<string>();

  function place(parentId: string | null) {
    for (const wh of warehouses) {
      if (wh.parentId === parentId && !placed.has(wh.id)) {
        result.push(wh);
        placed.add(wh.id);
        place(wh.id); // recursively place children
      }
    }
  }

  place(null); // roots first

  // Safety: any orphaned nodes (parentId points to a missing WH)
  for (const wh of warehouses) {
    if (!placed.has(wh.id)) result.push(wh);
  }

  return result;
}

/** Number of ancestors in the parentId chain → used for visual indentation. */
function getDepth(warehouseId: string, warehouses: DemoWarehouse[], visited = new Set<string>()): number {
  if (visited.has(warehouseId)) return 0;
  visited.add(warehouseId);
  const wh = warehouses.find((w) => w.id === warehouseId);
  if (!wh?.parentId) return 0;
  return 1 + getDepth(wh.parentId, warehouses, visited);
}

export default function WarehousesPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view warehouses.</p>;

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const typeColors: Record<string, { bg: string; text: string; label: string }> = {
    MWH:    { bg: "#FEF3C7", text: "#92400E", label: "Main WH (MWH)" },
    RWH:    { bg: "#DBEAFE", text: "#1E40AF", label: "Regional WH (RWH)" },
    WH:     { bg: "#F3F4F6", text: "#374151", label: "Warehouse (WH)" },
    SUB_WH: { bg: "#EDE9FE", text: "#5B21B6", label: "Sub-Warehouse" },
  };

  const sorted = sortByHierarchy(tenant.warehouses);

  return (
    <div style={{ padding: "2rem" }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>Warehouses</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>{tenant.name} · {tenant.warehouses.length} locations</p>
      </div>

      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
              {["Name", "Location", "Type", "Manager", "Total Units", "SKUs"].map((h) => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((w, idx) => {
              const whUnits = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
              const whSKUs  = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
              const tc    = typeColors[w.type] ?? { bg: "#F3F4F6", text: "#6B7280", label: w.type };
              const user  = tenant.users.find((u) => u.warehouseId === w.id);
              const depth = getDepth(w.id, tenant.warehouses);

              return (
                <tr key={w.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937", paddingLeft: `${16 + depth * 24}px` }}>
                    {depth > 0 && (
                      <span style={{ color: "#9CA3AF", marginRight: 6, fontFamily: "monospace" }}>
                        {"↳".repeat(depth)}
                      </span>
                    )}
                    {w.name}
                  </td>
                  <td style={{ padding: "10px 16px", color: "#6B7280" }}>{w.location}</td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, background: tc.bg, color: tc.text, padding: "2px 8px", borderRadius: 3 }}>{tc.label}</span>
                  </td>
                  <td style={{ padding: "10px 16px", color: "#374151" }}>{user?.name ?? "—"}</td>
                  <td style={{ padding: "10px 16px", fontWeight: 700, color: "#111827" }}>{whUnits.toLocaleString()}</td>
                  <td style={{ padding: "10px 16px", color: "#374151" }}>{whSKUs}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
