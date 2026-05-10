"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, getTotalStock, type DemoProduct } from "@/lib/demo-data";

const DARK   = "#0f2d1f";
const FOREST = "#1B4332";
const GOLD   = "#FCDD09";

interface CountEntry {
  productId: string;
  warehouseId: string;
  counted: string;
}

function getVarianceColor(variance: number): string {
  if (variance > 0)  return "#059669";
  if (variance < 0)  return "#DC2626";
  return "#6B7280";
}

export default function StockCountPage() {
  const { org } = useParams() as { org: string };

  const [sessionActive, setSessionActive] = useState(false);
  const [submitted, setSubmitted]         = useState(false);
  const [counts, setCounts]               = useState<Record<string, string>>({});
  const [selectedWH, setSelectedWH]       = useState("");

  if (org === SA_ORG_SLUG) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to run a stock count.</p>;
  }

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const warehouse = tenant.warehouses.find((w) => w.id === selectedWH);

  const products: DemoProduct[] = selectedWH
    ? tenant.products.filter((p) => (p.stock[selectedWH] ?? 0) > 0)
    : tenant.products;

  function getExpected(p: DemoProduct): number {
    return selectedWH ? (p.stock[selectedWH] ?? 0) : getTotalStock(p);
  }

  function countKey(pid: string) { return `${pid}::${selectedWH}`; }

  const totalVariance = products.reduce((acc, p) => {
    const raw = counts[countKey(p.id)] ?? "";
    if (!raw) return acc;
    return acc + (parseFloat(raw) - getExpected(p));
  }, 0);

  const filledCount = products.filter((p) => counts[countKey(p.id)] !== undefined && counts[countKey(p.id)] !== "").length;

  if (submitted) {
    return (
      <div style={{ padding: "2rem", maxWidth: 560, margin: "4rem auto", textAlign: "center" }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "#DCFCE7", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 1.5rem", fontSize: 28 }}>
          ✓
        </div>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 800, color: DARK, margin: "0 0 0.5rem" }}>Count Submitted</h2>
        <p style={{ color: "#6B7280", fontSize: 14, margin: "0 0 1.5rem" }}>
          {filledCount} product count{filledCount !== 1 ? "s" : ""} submitted for approval.<br />
          Variances will be reviewed by your Regional Manager.
        </p>
        <button
          onClick={() => { setSubmitted(false); setSessionActive(false); setCounts({}); setSelectedWH(""); }}
          style={{ padding: "10px 24px", background: FOREST, color: GOLD, fontWeight: 700, fontSize: 14, borderRadius: 6, border: "none", cursor: "pointer" }}
        >
          Start New Count
        </button>
      </div>
    );
  }

  if (!sessionActive) {
    return (
      <div style={{ padding: "2rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: "0 0 0.5rem" }}>Stock Count</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "0 0 2rem" }}>{tenant.name} · Record physical stock counts</p>

        <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 8, padding: "2rem", maxWidth: 480 }}>
          <p style={{ fontWeight: 700, fontSize: 15, color: "#1F2937", margin: "0 0 1rem" }}>Start a Count Session</p>

          <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            Warehouse
          </label>
          <select
            value={selectedWH}
            onChange={(e) => setSelectedWH(e.target.value)}
            style={{ width: "100%", padding: "9px 12px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", marginBottom: 20, cursor: "pointer" }}
          >
            <option value="">All locations (full count)</option>
            {tenant.warehouses.map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>

          <div style={{ padding: "12px 14px", background: "#F0FDF4", borderRadius: 6, border: "1px solid #BBF7D0", marginBottom: 20, fontSize: 13, color: "#166534" }}>
            {selectedWH
              ? `${products.length} products to count in ${warehouse?.name}`
              : `${tenant.products.length} products across ${tenant.warehouses.length} locations`}
          </div>

          <button
            onClick={() => setSessionActive(true)}
            style={{ width: "100%", padding: "12px", background: FOREST, color: GOLD, fontWeight: 700, fontSize: 14, borderRadius: 6, border: "none", cursor: "pointer" }}
          >
            Start Count Session
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Stock Count — Active Session</h2>
          <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
            {tenant.name} · {warehouse?.name ?? "All locations"} · {filledCount}/{products.length} products counted
          </p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={() => { setSessionActive(false); setCounts({}); }}
            style={{ padding: "8px 16px", background: "#F3F4F6", border: "1px solid #E5E7EB", borderRadius: 4, fontSize: 13, fontWeight: 600, cursor: "pointer", color: "#374151" }}
          >
            Cancel
          </button>
          <button
            onClick={() => setSubmitted(true)}
            disabled={filledCount === 0}
            style={{
              padding: "8px 16px", background: filledCount > 0 ? "#059669" : "#E5E7EB",
              color: filledCount > 0 ? "#fff" : "#9CA3AF",
              fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none",
              cursor: filledCount > 0 ? "pointer" : "not-allowed",
            }}
          >
            Submit for Approval ({filledCount})
          </button>
        </div>
      </div>

      {/* Variance summary */}
      {filledCount > 0 && (
        <div style={{ display: "flex", gap: 12, marginBottom: "1.5rem" }}>
          {[
            { label: "Counted", value: filledCount, color: "#1B4332", bg: "#F0FDF4" },
            { label: "Variance", value: totalVariance > 0 ? `+${totalVariance.toFixed(0)}` : totalVariance.toFixed(0), color: getVarianceColor(totalVariance), bg: totalVariance !== 0 ? "#FEF2F2" : "#F9FAFB" },
          ].map((s) => (
            <div key={s.label} style={{ padding: "10px 20px", background: s.bg, borderRadius: 6, border: "1px solid #E5E7EB", textAlign: "center" }}>
              <p style={{ fontSize: "1.25rem", fontWeight: 800, color: s.color, margin: 0 }}>{s.value}</p>
              <p style={{ fontSize: 12, color: "#6B7280", margin: "2px 0 0" }}>{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Count table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
              {["SKU", "Product", "Expected", "Counted", "Variance"].map((h) => (
                <th key={h} style={{
                  padding: "10px 16px", textAlign: h === "Expected" || h === "Variance" || h === "Counted" ? "right" : "left",
                  fontSize: 11, fontWeight: 700, color: "#6B7280",
                  textTransform: "uppercase", letterSpacing: "0.05em",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {products.map((p, idx) => {
              const key      = countKey(p.id);
              const expected = getExpected(p);
              const raw      = counts[key] ?? "";
              const counted  = raw !== "" ? parseFloat(raw) : null;
              const variance = counted !== null ? counted - expected : null;

              return (
                <tr key={p.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{p.sku}</td>
                  <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                  <td style={{ padding: "10px 16px", textAlign: "right", color: "#6B7280" }}>{expected.toLocaleString()}</td>
                  <td style={{ padding: "8px 16px", textAlign: "right" }}>
                    <input
                      type="number" min={0} step={1}
                      value={raw}
                      onChange={(e) => setCounts((c) => ({ ...c, [key]: e.target.value }))}
                      placeholder="—"
                      style={{
                        width: 90, padding: "5px 8px", textAlign: "right",
                        border: raw ? "1px solid #059669" : "1px solid #D1D5DB",
                        borderRadius: 4, fontSize: 13, outline: "none",
                        background: raw ? "#F0FDF4" : "#fff",
                      }}
                    />
                  </td>
                  <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: variance !== null ? 700 : 400, color: variance !== null ? getVarianceColor(variance) : "#E5E7EB" }}>
                    {variance !== null ? (variance > 0 ? `+${variance.toFixed(0)}` : variance.toFixed(0)) : "—"}
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
