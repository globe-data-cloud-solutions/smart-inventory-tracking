"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSession, type SessionUser } from "@/lib/demo-auth";
import {
  DEMO_TENANTS,
  getLowStockProducts,
  getTotalStock,
  type DemoProduct,
  type DemoTenant,
} from "@/lib/demo-data";

/* ── Shared colours ──────────────────────────────────────────────────────── */
const DARK   = "#0f2d1f";
const FOREST = "#1B4332";
const GOLD   = "#FCDD09";

/* ── Summary rectangle component ─────────────────────────────────────────── */
function SummaryCard({
  title, subtitle, rows, accentColor,
}: {
  title: string;
  subtitle: string;
  rows: { label: string; value: string | number; warn?: boolean }[];
  accentColor: string;
}) {
  return (
    <div style={{
      background: "#fff",
      border: "1px solid #E5E7EB",
      borderRadius: 4,
      overflow: "hidden",
      marginBottom: "1.5rem",
    }}>
      {/* Coloured top strip */}
      <div style={{ height: 4, background: accentColor }} />
      {/* Header row */}
      <div style={{
        padding: "1rem 1.5rem",
        background: DARK,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div>
          <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>{title}</p>
          <p style={{ fontSize: 12, color: "#6ee7b7", margin: 0, marginTop: 2 }}>{subtitle}</p>
        </div>
        <div style={{ height: 5, width: "30%",
          background: "linear-gradient(to right,#078930 0% 33.33%,#FCDD09 33.33% 66.66%,#DA121A 66.66% 100%)",
          borderRadius: 2 }} />
      </div>
      {/* Metric rows */}
      <div style={{
        display: "grid",
        gridTemplateColumns: `repeat(${rows.length}, 1fr)`,
        borderTop: "1px solid #F3F4F6",
      }}>
        {rows.map((r, i) => (
          <div key={r.label} style={{
            padding: "1.25rem 1.5rem",
            textAlign: "center",
            borderRight: i < rows.length - 1 ? "1px solid #F3F4F6" : "none",
            background: r.warn ? "#FFF1F2" : "#fff",
          }}>
            <p style={{
              fontSize: "1.75rem", fontWeight: 800, margin: 0,
              color: r.warn ? "#DC2626" : FOREST,
            }}>
              {typeof r.value === "number" ? r.value.toLocaleString() : r.value}
            </p>
            <p style={{ fontSize: 12, color: "#6B7280", margin: "4px 0 0", fontWeight: 500 }}>
              {r.label}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Inventory table ──────────────────────────────────────────────────────── */
function InventoryTable({
  products, getQty, accentColor, title, subtitle,
}: {
  products: DemoProduct[];
  getQty: (p: DemoProduct) => number;
  accentColor: string;
  title: string;
  subtitle: string;
}) {
  const categories = [...new Set(products.map((p) => p.category))];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {categories.map((cat) => {
        const items = products.filter((p) => p.category === cat);
        const catTotal = items.reduce((a, p) => a + getQty(p), 0);
        return (
          <div key={cat} style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ height: 3, background: accentColor }} />
            <div style={{
              padding: "0.75rem 1.25rem",
              background: "#F9FAFB",
              borderBottom: "2px solid #E5E7EB",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <div>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#1F2937" }}>{title}</span>
                <span style={{ fontSize: 12, color: "#9CA3AF", marginLeft: 8 }}>· {subtitle} · {cat}</span>
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#6B7280", background: "#E5E7EB", padding: "2px 8px", borderRadius: 3 }}>
                {items.length} SKUs
              </span>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}>
                    {["SKU", "Product", "Category", "Stock", "Reorder Point", "Status"].map((h) => (
                      <th key={h} style={{
                        padding: "10px 16px", textAlign: h === "Stock" || h === "Reorder Point" ? "right" : "left",
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
                      <tr key={p.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                        <td style={{ padding: "10px 16px", fontFamily: "monospace", fontSize: 11, color: "#9CA3AF" }}>{p.sku}</td>
                        <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937" }}>{p.name}</td>
                        <td style={{ padding: "10px 16px", color: "#6B7280" }}>{p.category}</td>
                        <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: 700, color: "#111827" }}>{qty.toLocaleString()}</td>
                        <td style={{ padding: "10px 16px", textAlign: "right", color: "#9CA3AF" }}>{p.reorderPoint.toLocaleString()}</td>
                        <td style={{ padding: "10px 16px" }}>
                          <span style={{
                            display: "inline-flex", alignItems: "center", gap: 5,
                            fontSize: 11, fontWeight: 700,
                            padding: "3px 10px", borderRadius: 3,
                            background: isLow ? "#FEF2F2" : "#F0FDF4",
                            color: isLow ? "#DC2626" : "#059669",
                            border: `1px solid ${isLow ? "#FECACA" : "#BBF7D0"}`,
                          }}>
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: isLow ? "#DC2626" : "#059669" }} />
                            {isLow ? "Low Stock" : "In Stock"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr style={{ background: "#F3F4F6", borderTop: "2px solid #E5E7EB" }}>
                    <td colSpan={3} style={{ padding: "10px 16px", fontSize: 12, fontWeight: 600, color: "#6B7280" }}>
                      {items.length} products in this category
                    </td>
                    <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: 800, color: FOREST, fontSize: 14 }}>
                      {catTotal.toLocaleString()}
                    </td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const [user, setUser] = useState<SessionUser | null>(null);
  useEffect(() => { setUser(getSession()); }, []);
  if (!user) return null;

  if (user.role === "SA") return <SAView />;

  const tenant = DEMO_TENANTS.find((t) => t.id === user.tenantId);
  if (!tenant) return <p style={{ padding: "2rem", color: "#6B7280" }}>No tenant assigned.</p>;

  if (user.warehouseId) return <LocationView user={user} tenant={tenant} />;
  return <TenantAdminView user={user} tenant={tenant} />;
}

/* ── SA view ─────────────────────────────────────────────────────────────── */
function SAView() {
  const totalLoc   = DEMO_TENANTS.reduce((a, t) => a + t.warehouses.length, 0);
  const totalSKUs  = DEMO_TENANTS.reduce((a, t) => a + t.products.length,   0);
  const totalUnits = DEMO_TENANTS.reduce((a, t) => a + t.products.reduce((b, p) => b + getTotalStock(p), 0), 0);

  return (
    <div style={{ padding: "2rem" }}>
      {/* Platform summary rectangle */}
      <SummaryCard
        title="Platform Overview"
        subtitle="All tenants · System Administrator"
        accentColor={GOLD}
        rows={[
          { label: "Tenants",        value: DEMO_TENANTS.length },
          { label: "Total Locations",value: totalLoc },
          { label: "Active SKUs",    value: totalSKUs },
          { label: "Total Units",    value: totalUnits },
          { label: "Total Users",    value: DEMO_TENANTS.reduce((a, t) => a + t.users.length, 0) + 1 },
        ]}
      />

      {/* Tenant cards */}
      <h3 style={{ fontSize: 16, fontWeight: 700, color: DARK, margin: "0 0 1rem" }}>Tenants</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "1.5rem" }}>
        {DEMO_TENANTS.map((t) => <SATenantCard key={t.id} tenant={t} />)}
      </div>

      {/* Role reference */}
      <div style={{
        marginTop: "2rem", background: "#fff", border: "1px solid #E5E7EB",
        borderRadius: 4, padding: "1.25rem",
      }}>
        <p style={{ fontSize: 13, fontWeight: 700, color: "#374151", margin: "0 0 0.75rem" }}>
          Role-scoped access — users see only their data
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "0.75rem" }}>
          {ROLE_GUIDE.map((r) => (
            <div key={r.role} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
              <span style={{ fontSize: 10, fontWeight: 800, color: "#fff", background: r.color, padding: "3px 7px", borderRadius: 3, flexShrink: 0 }}>{r.role}</span>
              <p style={{ fontSize: 12, color: "#6B7280", margin: 0 }}>{r.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SATenantCard({ tenant }: { tenant: DemoTenant }) {
  const low   = getLowStockProducts(tenant);
  const units = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
  return (
    <Link href={`/dashboard/tenants/${tenant.slug}`} style={{ textDecoration: "none" }}>
      <div className="tenant-card">
        <div style={{ background: tenant.color, padding: "1rem 1.25rem", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: "2rem" }}>{tenant.logo}</span>
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>{tenant.name}</p>
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.75)", margin: 0 }}>{tenant.industry}</p>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", padding: "0.875rem", gap: "0.5rem", textAlign: "center" }}>
          {[
            { l: "Locations",  v: tenant.warehouses.length },
            { l: "SKUs",       v: tenant.products.length },
            { l: "Units",      v: units.toLocaleString() },
            { l: "Low Stock",  v: low.length, w: low.length > 0 },
          ].map((s) => (
            <div key={s.l}>
              <p style={{ fontSize: "1.25rem", fontWeight: 800, margin: 0, color: s.w ? "#DC2626" : "#111827" }}>{s.v}</p>
              <p style={{ fontSize: 11, color: "#9CA3AF", margin: 0 }}>{s.l}</p>
            </div>
          ))}
        </div>
        <div style={{ padding: "0.625rem 1.25rem", borderTop: "1px solid #F3F4F6", background: "#FAFAFA" }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: tenant.color }}>Open dashboard →</span>
        </div>
      </div>
    </Link>
  );
}

/* ── WM / NM — single location view ──────────────────────────────────────── */
function LocationView({ user, tenant }: { user: SessionUser; tenant: DemoTenant }) {
  const wh = tenant.warehouses.find((w) => w.id === user.warehouseId);
  if (!wh) return null;

  const myProducts  = tenant.products.filter((p) => (p.stock[user.warehouseId!] ?? 0) > 0);
  const totalUnits  = myProducts.reduce((a, p) => a + (p.stock[user.warehouseId!] ?? 0), 0);
  const lowStock    = myProducts.filter((p) => (p.stock[user.warehouseId!] ?? 0) < p.reorderPoint);
  const inStock     = myProducts.length - lowStock.length;

  const typeLabel: Record<string, string> = { PRODUCTION: "Production Center", WAREHOUSE: "Warehouse", SUBCENTER: "Sub-center" };

  return (
    <div style={{ padding: "2rem" }}>
      {/* Summary rectangle — 3 metric rows */}
      <SummaryCard
        title={`${wh.name}`}
        subtitle={`${typeLabel[wh.type] ?? "Location"} · ${wh.location ?? tenant.name} · ${user.role}`}
        accentColor={tenant.color}
        rows={[
          { label: "Total Units",        value: totalUnits, },
          { label: "SKUs with Stock",    value: myProducts.length },
          { label: "In Stock",           value: inStock },
          { label: "Low Stock Alerts",   value: lowStock.length, warn: lowStock.length > 0 },
        ]}
      />

      {/* Inventory table */}
      <InventoryTable
        products={myProducts}
        getQty={(p) => p.stock[user.warehouseId!] ?? 0}
        accentColor={tenant.color}
        title={wh.name}
        subtitle={`${user.role} view — ${wh.location ?? ""}`}
      />
    </div>
  );
}

/* ── TA — full tenant view ────────────────────────────────────────────────── */
function TenantAdminView({ user, tenant }: { user: SessionUser; tenant: DemoTenant }) {
  const lowStock   = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
  const prodCentres = tenant.warehouses.filter((w) => w.type === "PRODUCTION").length;

  return (
    <div style={{ padding: "2rem" }}>
      {/* Summary rectangle */}
      <SummaryCard
        title={tenant.name}
        subtitle={`${tenant.industry} · Tenant Admin — all locations`}
        accentColor={tenant.color}
        rows={[
          { label: "Locations",      value: tenant.warehouses.length },
          { label: "Production Ctrs",value: prodCentres },
          { label: "Active SKUs",    value: tenant.products.length },
          { label: "Total Units",    value: totalUnits },
          { label: "Low Stock",      value: lowStock.length, warn: lowStock.length > 0 },
        ]}
      />

      {/* Per-warehouse summary rows */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden", marginBottom: "1.5rem" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ padding: "0.75rem 1.25rem", background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#1F2937" }}>Inventory by Location</span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr>
              {["Location", "Type", "Active SKUs", "Total Units", "Low Stock"].map((h) => (
                <th key={h} style={{
                  padding: "10px 16px", background: "#F9FAFB",
                  textAlign: h === "Total Units" || h === "Active SKUs" ? "right" : "left",
                  fontSize: 11, fontWeight: 700, color: "#6B7280",
                  textTransform: "uppercase", letterSpacing: "0.05em",
                  borderBottom: "1px solid #E5E7EB",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tenant.warehouses.map((w, idx) => {
              const whUnits = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
              const whSKUs  = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
              const whLow   = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0 && (p.stock[w.id] ?? 0) < p.reorderPoint).length;
              const typeColors: Record<string, { bg: string; text: string }> = {
                PRODUCTION: { bg: "#FEF3C7", text: "#92400E" },
                WAREHOUSE:  { bg: "#DBEAFE", text: "#1E40AF" },
                SUBCENTER:  { bg: "#EDE9FE", text: "#5B21B6" },
              };
              const tc = typeColors[w.type] ?? { bg: "#F3F4F6", text: "#6B7280" };
              return (
                <tr key={w.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                  <td style={{ padding: "10px 16px", fontWeight: 600, color: "#1F2937" }}>
                    {w.parentId && <span style={{ color: "#D1D5DB", marginRight: 4 }}>↳</span>}
                    {w.name}
                    <p style={{ margin: 0, fontSize: 11, color: "#9CA3AF", fontWeight: 400 }}>{w.location}</p>
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, background: tc.bg, color: tc.text, padding: "2px 8px", borderRadius: 3 }}>
                      {w.type === "PRODUCTION" ? "Production" : w.type === "SUBCENTER" ? "Sub-center" : "Warehouse"}
                    </span>
                  </td>
                  <td style={{ padding: "10px 16px", textAlign: "right", color: "#374151" }}>{whSKUs}</td>
                  <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: 700, color: "#111827" }}>{whUnits.toLocaleString()}</td>
                  <td style={{ padding: "10px 16px" }}>
                    {whLow > 0
                      ? <span style={{ fontSize: 11, fontWeight: 700, background: "#FEF2F2", color: "#DC2626", border: "1px solid #FECACA", padding: "2px 8px", borderRadius: 3 }}>{whLow} low</span>
                      : <span style={{ fontSize: 11, fontWeight: 700, background: "#F0FDF4", color: "#059669", border: "1px solid #BBF7D0", padding: "2px 8px", borderRadius: 3 }}>OK</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Full product inventory */}
      <InventoryTable
        products={tenant.products}
        getQty={getTotalStock}
        accentColor={tenant.color}
        title={`${tenant.name} — Full Inventory`}
        subtitle={`All ${tenant.warehouses.length} locations combined`}
      />
    </div>
  );
}

const ROLE_GUIDE = [
  { role: "SA",  color: "#DC2626", desc: "Full platform — all tenants, all locations, all data" },
  { role: "TA",  color: "#7C3AED", desc: "Tenant Admin — all warehouses, all products in their tenant" },
  { role: "NM",  color: "#2563EB", desc: "National/Production Manager — their location only" },
  { role: "WM",  color: "#059669", desc: "Warehouse Manager — their warehouse only" },
];
