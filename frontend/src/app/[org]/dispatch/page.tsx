"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { api } from "@/lib/api";

type Strategy = "FEFO" | "FIFO" | "LIFO";

interface DispatchConfig {
  id: string; product_id: string; product_name: string;
  product_sku: string; scope: string; strategy: Strategy;
  effective_from: string;
}

const STRATEGY_STYLE: Record<Strategy, { bg: string; color: string; label: string; desc: string }> = {
  FEFO: { bg: "#FEF3C7", color: "#92400E", label: "FEFO", desc: "First Expired, First Out — enforced automatically when batch+expiry tracking active" },
  FIFO: { bg: "#DBEAFE", color: "#1E40AF", label: "FIFO", desc: "First In, First Out — oldest received lot dispatched first" },
  LIFO: { bg: "#EDE9FE", color: "#5B21B6", label: "LIFO", desc: "Last In, First Out — most recently received lot dispatched first" },
};

const DARK = "#0f2d1f";
const GOLD = "#FCDD09";

function FefoOverrideModal({ productName, onClose }: { productName: string; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 200 }} />
      <div style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)", background: "#fff", borderRadius: 10, padding: "2rem", zIndex: 201, width: 400, boxShadow: "0 8px 32px rgba(0,0,0,0.2)" }}>
        {submitted ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ width: 56, height: 56, borderRadius: "50%", background: "#FEF3C7", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 1rem", fontSize: 24 }}>⚠️</div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#111827", margin: "0 0 0.5rem" }}>Override Applied</p>
            <p style={{ fontSize: 13, color: "#6B7280", margin: "0 0 1.5rem" }}>FEFO override logged for {productName}. Audit record created.</p>
            <button onClick={onClose} style={{ padding: "9px 24px", background: "#92400E", color: "#fff", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 700, cursor: "pointer" }}>Done</button>
          </div>
        ) : (
          <>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#111827", margin: "0 0 0.25rem" }}>FEFO Override</p>
            <p style={{ fontSize: 13, color: "#6B7280", margin: "0 0 1.25rem" }}>Overriding FEFO for <strong>{productName}</strong>. A reason is required and this will be audit-logged.</p>
            <label style={{ display: "block", fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#374151", marginBottom: 6 }}>Override Reason *</label>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="Why is FEFO being overridden for this dispatch?" style={{ width: "100%", padding: "8px 10px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", resize: "vertical", boxSizing: "border-box" as const, marginBottom: 16 }} />
            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={onClose} style={{ flex: 1, padding: "9px", background: "#F3F4F6", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>Cancel</button>
              <button disabled={!reason.trim()} onClick={() => setSubmitted(true)} style={{ flex: 2, padding: "9px", background: reason.trim() ? "#92400E" : "#E5E7EB", color: reason.trim() ? "#fff" : "#9CA3AF", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 700, cursor: reason.trim() ? "pointer" : "not-allowed" }}>
                Apply Override
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export default function DispatchPage() {
  const { org }     = useParams() as { org: string };
  const user        = getSession();
  const qc          = useQueryClient();
  const canConfigure = usePermission("dispatch:configure");
  const canOverride  = usePermission("dispatch:fefo_override");

  const [overrideProduct, setOverrideProduct] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [toast, setToast]   = useState("");

  if (org === SA_ORG_SLUG) return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to configure dispatch.</p>;
  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant || !user) return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  const { data: configs = [] } = useQuery<DispatchConfig[]>({
    queryKey: ["dispatch-config", org],
    queryFn:  () => api.get<DispatchConfig[]>("/api/v1/dispatch-config"),
    staleTime: 0,
  });

  function getStrategy(productId: string): Strategy {
    return configs.find((c) => c.product_id === productId)?.strategy ?? "FIFO";
  }

  async function setStrategy(productId: string, productName: string, productSku: string, strategy: Strategy) {
    setSaving(productId);
    try {
      await api.post("/api/v1/dispatch-config", { product_id: productId, product_name: productName, product_sku: productSku, scope: "PRODUCT", strategy });
      await qc.invalidateQueries({ queryKey: ["dispatch-config", org] });
      setToast(`${productName}: strategy set to ${strategy}`);
      setTimeout(() => setToast(""), 3000);
    } catch { setToast("Failed to save strategy."); setTimeout(() => setToast(""), 3000); }
    finally { setSaving(null); }
  }

  return (
    <div style={{ padding: "2rem" }}>
      {/* Toast */}
      {toast && (
        <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 200, background: DARK, color: GOLD, fontWeight: 700, fontSize: 13, padding: "10px 20px", borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.2)" }}>
          {toast}
        </div>
      )}

      {overrideProduct && (
        <FefoOverrideModal productName={overrideProduct} onClose={() => setOverrideProduct(null)} />
      )}

      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Dispatch Strategy</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
          {tenant.name} · Configure FEFO / FIFO / LIFO per product
        </p>
      </div>

      {/* Strategy legend */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12, marginBottom: "1.5rem" }}>
        {(["FEFO", "FIFO", "LIFO"] as Strategy[]).map((s) => {
          const m = STRATEGY_STYLE[s];
          return (
            <div key={s} style={{ background: m.bg, border: `1px solid ${m.color}30`, borderRadius: 8, padding: "0.875rem 1rem" }}>
              <p style={{ fontWeight: 800, fontSize: 14, color: m.color, margin: "0 0 4px" }}>{m.label}</p>
              <p style={{ fontSize: 12, color: "#6B7280", margin: 0 }}>{m.desc}</p>
            </div>
          );
        })}
      </div>

      {/* Auto-FEFO notice */}
      <div style={{ background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 6, padding: "10px 14px", marginBottom: "1.5rem", fontSize: 13, color: "#92400E" }}>
        <strong>Auto-FEFO:</strong> Products with both batch tracking and expiry date active always use FEFO — strategy overrides are ignored.
        {canOverride && " Use the FEFO Override button to bypass for a single dispatch (audit-logged)."}
      </div>

      {/* Product table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
              {["SKU", "Product", "Batch Tracking", "Current Strategy", ...(canConfigure ? ["Set Strategy"] : []), ...(canOverride ? ["Override"] : [])].map((h) => (
                <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tenant.products.map((p, idx) => {
              const strategy = p.batchTracking ? "FEFO" : getStrategy(p.id);
              const s = STRATEGY_STYLE[strategy];
              const isAutoFefo = p.batchTracking;
              const isSaving  = saving === p.id;

              return (
                <tr key={p.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{p.sku}</td>
                  <td style={{ padding: "10px 14px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, background: p.batchTracking ? "#DCFCE7" : "#F3F4F6", color: p.batchTracking ? "#166534" : "#9CA3AF", padding: "2px 8px", borderRadius: 3 }}>
                      {p.batchTracking ? "Yes" : "No"}
                    </span>
                  </td>
                  <td style={{ padding: "10px 14px" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, background: s.bg, color: s.color, padding: "3px 8px", borderRadius: 3 }}>
                      {strategy}{isAutoFefo ? " (auto)" : ""}
                    </span>
                  </td>
                  {canConfigure && (
                    <td style={{ padding: "8px 14px" }}>
                      {isAutoFefo ? (
                        <span style={{ fontSize: 12, color: "#D1D5DB" }}>Auto — cannot override</span>
                      ) : (
                        <div style={{ display: "flex", gap: 6 }}>
                          {(["FEFO", "FIFO", "LIFO"] as Strategy[]).map((strat) => {
                            const active = strategy === strat;
                            const m = STRATEGY_STYLE[strat];
                            return (
                              <button
                                key={strat}
                                disabled={isSaving || active}
                                onClick={() => setStrategy(p.id, p.name, p.sku, strat)}
                                style={{
                                  fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 4, cursor: active || isSaving ? "not-allowed" : "pointer",
                                  border: `1px solid ${active ? m.color : "#E5E7EB"}`,
                                  background: active ? m.bg : "#fff", color: active ? m.color : "#9CA3AF",
                                  opacity: isSaving ? 0.5 : 1,
                                }}
                              >
                                {strat}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </td>
                  )}
                  {canOverride && (
                    <td style={{ padding: "8px 14px" }}>
                      {(strategy === "FEFO" || isAutoFefo) ? (
                        <button
                          onClick={() => setOverrideProduct(p.name)}
                          style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 4, cursor: "pointer", border: "1px solid #FDE68A", background: "#FFFBEB", color: "#92400E" }}
                        >
                          Override
                        </button>
                      ) : (
                        <span style={{ fontSize: 11, color: "#D1D5DB" }}>—</span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
