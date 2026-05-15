"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { useAuditStore } from "@/lib/audit-log-state";

const DARK = "#0f2d1f";

const CATEGORY_STYLE: Record<string, { bg: string; color: string; icon: string }> = {
  TRANSFER:   { bg: "#DBEAFE", color: "#1E40AF", icon: "🔄" },
  INVENTORY:  { bg: "#DCFCE7", color: "#166534", icon: "📦" },
  ADJUSTMENT: { bg: "#FEF3C7", color: "#92400E", icon: "✏️" },
  SYSTEM:     { bg: "#F3F4F6", color: "#374151", icon: "⚙️" },
};

export default function AuditLogPage() {
  const { org } = useParams() as { org: string };
  const user    = getSession();

  // Subscribe directly to entries so the component re-renders when entries change
  // (fixes the persistence bug where getForTenant() selector was stable and non-reactive)
  const allEntries = useAuditStore((s) => s.entries);

  const [categoryFilter, setCategoryFilter] = useState<"ALL" | "TRANSFER" | "INVENTORY" | "ADJUSTMENT">("ALL");
  const [search, setSearch] = useState("");

  if (!user) return null;
  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view the audit log.</p>;

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  // Filter to this tenant, most recent first
  const tenantEntries = allEntries
    .filter((e) => e.tenantSlug === org)
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));

  const filtered = tenantEntries.filter((e) => {
    if (categoryFilter !== "ALL" && e.category !== categoryFilter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        e.action.toLowerCase().includes(q) ||
        e.resourceRef.toLowerCase().includes(q) ||
        (e.productName ?? "").toLowerCase().includes(q) ||
        (e.fromWarehouse ?? "").toLowerCase().includes(q) ||
        (e.toWarehouse ?? "").toLowerCase().includes(q) ||
        e.userName.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const counts = {
    TRANSFER:   tenantEntries.filter((e) => e.category === "TRANSFER").length,
    INVENTORY:  tenantEntries.filter((e) => e.category === "INVENTORY").length,
    ADJUSTMENT: tenantEntries.filter((e) => e.category === "ADJUSTMENT").length,
  };

  return (
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Audit Log</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
          {tenant.name} · {tenantEntries.length} recorded events · append-only · persisted across sessions
        </p>
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1.5rem", flexWrap: "wrap", alignItems: "center" }}>
        {(["ALL", "TRANSFER", "INVENTORY", "ADJUSTMENT"] as const).map((cat) => {
          const count = cat === "ALL" ? tenantEntries.length : counts[cat];
          const s = cat !== "ALL" ? CATEGORY_STYLE[cat] : { bg: "#F3F4F6", color: "#374151", icon: "" };
          return (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              style={{
                fontSize: 12, fontWeight: 700, padding: "4px 12px", borderRadius: 20, cursor: "pointer",
                border: categoryFilter === cat ? "2px solid #0f2d1f" : "2px solid transparent",
                background: categoryFilter === cat ? s.bg : "#F9FAFB",
                color: categoryFilter === cat ? s.color : "#6B7280",
              }}
            >
              {s.icon ? `${s.icon} ` : ""}{cat} ({count})
            </button>
          );
        })}

        <div style={{ position: "relative", flex: 1, minWidth: 200 }}>
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#9CA3AF", fontSize: 13 }}>🔍</span>
          <input
            type="text" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search action, product, warehouse, user…"
            style={{ width: "100%", padding: "6px 10px 6px 30px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", boxSizing: "border-box" as const }}
          />
        </div>

        <span style={{ fontSize: 12, color: "#9CA3AF", whiteSpace: "nowrap" }}>
          {filtered.length} of {tenantEntries.length}
        </span>
      </div>

      {/* Table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                {["Timestamp", "User", "Role", "Category", "Action", "Ref", "Product", "Qty / Unit", "From", "To", "Notes"].map((h) => (
                  <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, idx) => {
                const cs = CATEGORY_STYLE[e.category] ?? CATEGORY_STYLE.SYSTEM;
                return (
                  <tr key={e.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "8px 12px", color: "#9CA3AF", whiteSpace: "nowrap", fontFamily: "monospace", fontSize: 10 }}>
                      {new Date(e.timestamp).toLocaleString()}
                    </td>
                    <td style={{ padding: "8px 12px", fontWeight: 600, color: "#1F2937", whiteSpace: "nowrap", fontSize: 11 }}>{e.userName}</td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, background: "#F3F4F6", color: "#374151", padding: "2px 6px", borderRadius: 3 }}>
                        {e.role}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 3, background: cs.bg, color: cs.color, whiteSpace: "nowrap" }}>
                        {cs.icon} {e.category}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace", color: "#374151", whiteSpace: "nowrap", fontSize: 11 }}>
                      {e.action}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace", color: "#6B7280", fontSize: 10 }}>
                      {e.resourceRef || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#1F2937", fontSize: 11, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {e.productName || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", fontWeight: 600, color: "#374151", whiteSpace: "nowrap", fontSize: 11 }}>
                      {e.quantityStr || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#6B7280", fontSize: 11, whiteSpace: "nowrap" }}>
                      {e.fromWarehouse || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#6B7280", fontSize: 11, whiteSpace: "nowrap" }}>
                      {e.toWarehouse || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#9CA3AF", fontSize: 11, maxWidth: 200 }}>
                      {e.notes || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filtered.length === 0 && (
          <div style={{ padding: "3rem", textAlign: "center" }}>
            {tenantEntries.length === 0 ? (
              <div>
                <p style={{ color: "#9CA3AF", fontSize: 14, margin: "0 0 0.5rem" }}>No activity logged yet.</p>
                <p style={{ color: "#D1D5DB", fontSize: 12, margin: 0 }}>
                  Create transfers, receive stock, or issue stock to generate audit entries.
                </p>
              </div>
            ) : (
              <p style={{ color: "#9CA3AF", fontSize: 13 }}>No entries match the current filter.</p>
            )}
          </div>
        )}
      </div>

      <p style={{ marginTop: "0.75rem", fontSize: 12, color: "#9CA3AF" }}>
        Persisted to localStorage · Completed and archived transfers are retained here permanently · Append-only
      </p>
    </div>
  );
}
