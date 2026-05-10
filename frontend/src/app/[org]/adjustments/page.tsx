"use client";

import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";

export default function AdjustmentsPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view adjustments.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const DEMO_ADJ = [
    { date: "2026-05-01", sku: "AW-500-P6",   wh: "North WH",  qty: -120, reason: "Damaged — moisture exposure",        status: "APPLIED" },
    { date: "2026-04-28", sku: "AW-1L-P12",   wh: "East WH",   qty:  200, reason: "Stock reconciliation — count higher", status: "APPLIED" },
    { date: "2026-04-20", sku: "AW-500-P24",  wh: "South WH",  qty:  -80, reason: "Expired stock disposal",              status: "APPLIED" },
    { date: "2026-05-09", sku: "AW-1.5L-P6",  wh: "West WH",   qty:  350, reason: "Bonus delivery — supplier goodwill", status: "PENDING" },
    { date: "2026-05-09", sku: "AW-SP500-P6", wh: "North WH",  qty: -150, reason: "Return to supplier — transit damage", status: "SUBMITTED" },
  ];

  return (
    <div style={{ padding: "2rem" }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: 0 }}>Adjustments</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>{tenant.name} · Stock corrections and write-offs</p>
      </div>

      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
              {["Date", "SKU", "Warehouse", "Quantity", "Reason", "Status"].map((h) => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DEMO_ADJ.map((a, idx) => (
              <tr key={idx} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                <td style={{ padding: "10px 16px", color: "#6B7280", fontSize: 12 }}>{a.date}</td>
                <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{a.sku}</td>
                <td style={{ padding: "10px 16px", color: "#374151" }}>{a.wh}</td>
                <td style={{ padding: "10px 16px", fontWeight: 700, color: a.qty < 0 ? "#DC2626" : "#059669" }}>
                  {a.qty > 0 ? "+" : ""}{a.qty.toLocaleString()}
                </td>
                <td style={{ padding: "10px 16px", color: "#6B7280" }}>{a.reason}</td>
                <td style={{ padding: "10px 16px" }}>
                  <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3,
                    background: a.status === "APPLIED" ? "#F0FDF4" : a.status === "PENDING" ? "#FEF3C7" : "#DBEAFE",
                    color: a.status === "APPLIED" ? "#059669" : a.status === "PENDING" ? "#92400E" : "#1E40AF",
                  }}>{a.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
