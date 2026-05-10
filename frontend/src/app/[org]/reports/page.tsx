"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";

export default function ReportsPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view reports.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const REPORTS = [
    { name: "Inventory Valuation",   desc: "Current stock value across all locations",        icon: "📊", href: `/${org}/analytics` },
    { name: "Stock Movement",        desc: "All RECEIVE / TRANSFER / ISSUE transactions",     icon: "🔄", href: `/${org}/transfers` },
    { name: "Expiry Alerts",         desc: "Products approaching or past expiry date",        icon: "⚠️", href: `/${org}/inventory` },
    { name: "Low Stock Report",      desc: "Products at or below reorder point",              icon: "📉", href: `/${org}/analytics` },
    { name: "Lot Traceability",      desc: "Full batch-to-location tracing",                  icon: "🔍", href: `/${org}/inventory` },
    { name: "Dispatch Summary",      desc: "FEFO / FIFO / LIFO dispatch history by product", icon: "🚚", href: `/${org}/transfers` },
  ];

  return (
    <div style={{ padding: "2rem" }}>
      <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f2d1f", margin: "0 0 1.5rem" }}>Reports</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: "1rem" }}>
        {REPORTS.map((r) => (
          <Link key={r.name} href={r.href} style={{ textDecoration: "none" }}>
            <div style={{
              background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, padding: "1.25rem",
              display: "flex", alignItems: "flex-start", gap: 12,
              transition: "box-shadow 0.15s, border-color 0.15s",
            }}
              className="report-card"
            >
              <span style={{ fontSize: "2rem", lineHeight: 1, flexShrink: 0 }}>{r.icon}</span>
              <div>
                <p style={{ fontWeight: 700, fontSize: 14, color: "#1F2937", margin: 0 }}>{r.name}</p>
                <p style={{ fontSize: 12, color: "#6B7280", margin: "4px 0 0" }}>{r.desc}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>
      <style>{`.report-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-color: #1B4332 !important; }`}</style>
    </div>
  );
}
