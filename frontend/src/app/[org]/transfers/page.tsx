"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";

const STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  DRAFT:      { bg: "#F3F4F6", color: "#6B7280" },
  SUBMITTED:  { bg: "#DBEAFE", color: "#1E40AF" },
  APPROVED:   { bg: "#D1FAE5", color: "#065F46" },
  IN_TRANSIT: { bg: "#FEF3C7", color: "#92400E" },
  RECEIVED:   { bg: "#DCFCE7", color: "#166534" },
  CLOSED:     { bg: "#F3F4F6", color: "#374151" },
  REJECTED:   { bg: "#FEE2E2", color: "#991B1B" },
  CANCELLED:  { bg: "#F3F4F6", color: "#9CA3AF" },
};

export default function TransfersPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view transfers.</p>;

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  // Demo transfer data derived from warehouse pairs for display
  const DEMO_TRANSFERS = [
    { ref: "SHIP-2026-001", from: "Main Production Center", to: "North WH",            status: "CLOSED",     qty: 1200, product: "Multiple SKUs" },
    { ref: "SHIP-2026-002", from: "North WH",               to: "North-Subcenter WH",  status: "IN_TRANSIT", qty: 480,  product: "Multiple SKUs" },
    { ref: "SHIP-2026-003", from: "Main Production Center", to: "South WH",            status: "APPROVED",   qty: 860,  product: "Multiple SKUs" },
    { ref: "SHIP-2026-004", from: "Main Production Center", to: "East WH",             status: "DRAFT",      qty: 540,  product: "Multiple SKUs" },
    { ref: "SHIP-2026-005", from: "South WH",               to: "West WH",             status: "REJECTED",   qty: 200,  product: "Multiple SKUs" },
  ];

  return (
    <div style={{ padding: "2rem" }}>
      <div style={{ marginBottom: "1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>Transfers</h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>{tenant.name} · Stock movements between locations</p>
        </div>
        <Link href={`/${org}/dashboard`} style={{
          padding: "8px 16px", background: "#FCDD09", color: "#0f2d1f",
          fontWeight: 700, fontSize: 13, borderRadius: 4, textDecoration: "none",
        }}>
          + New Transfer
        </Link>
      </div>

      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
              {["Reference", "From", "To", "Product", "Quantity", "Status"].map((h) => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DEMO_TRANSFERS.map((t, idx) => {
              const s = STATUS_STYLE[t.status] ?? { bg: "#F3F4F6", color: "#6B7280" };
              return (
                <tr key={t.ref} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: "#1F2937" }}>{t.ref}</td>
                  <td style={{ padding: "10px 16px", color: "#374151" }}>{t.from}</td>
                  <td style={{ padding: "10px 16px", color: "#374151" }}>{t.to}</td>
                  <td style={{ padding: "10px 16px", color: "#6B7280" }}>{t.product}</td>
                  <td style={{ padding: "10px 16px", fontWeight: 600, color: "#111827" }}>{t.qty.toLocaleString()}</td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3, background: s.bg, color: s.color }}>{t.status}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
