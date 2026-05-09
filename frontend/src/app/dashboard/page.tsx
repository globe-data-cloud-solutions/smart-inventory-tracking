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
  type DemoWarehouse,
} from "@/lib/demo-data";

const C = {
  dark:   "#12291E",
  forest: "#1B4332",
  gold:   "#FCDD09",
};

export default function DashboardPage() {
  const [user, setUser] = useState<SessionUser | null>(null);

  useEffect(() => { setUser(getSession()); }, []);
  if (!user) return null;

  // ── SA: overview cards, NO inventory tables
  if (user.role === "SA") return <SAView />;

  // ── Tenant-scoped user
  const tenant = DEMO_TENANTS.find((t) => t.id === user.tenantId);
  if (!tenant) return <p className="p-8 text-gray-500">No tenant assigned to your account.</p>;

  // ── WM / NM: scoped to one location
  if (user.warehouseId) return <LocationView user={user} tenant={tenant} />;

  // ── TA: full tenant view
  return <TenantAdminView user={user} tenant={tenant} />;
}

// ══ SA Dashboard — overview only, no tables ═══════════════════════════════════

function SAView() {
  const totalLocations = DEMO_TENANTS.reduce((a, t) => a + t.warehouses.length, 0);
  const totalSKUs      = DEMO_TENANTS.reduce((a, t) => a + t.products.length,   0);
  const totalUsers     = DEMO_TENANTS.reduce((a, t) => a + t.users.length,      0) + 1;

  return (
    <div className="p-6 space-y-8">
      <div>
        <h2 className="text-2xl font-bold" style={{ color: C.dark }}>System Overview</h2>
        <p className="text-gray-500 text-sm mt-1">System Administrator · Full platform access</p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Tenants",    value: DEMO_TENANTS.length, icon: "🏢", color: "#DBEAFE", text: "#1E40AF" },
          { label: "Locations",  value: totalLocations,      icon: "📍", color: "#E9D5FF", text: "#6B21A8" },
          { label: "Active SKUs",value: totalSKUs,           icon: "📦", color: "#D1FAE5", text: "#065F46" },
          { label: "Users",      value: totalUsers,          icon: "👤", color: "#FEF3C7", text: "#92400E" },
        ].map((s) => (
          <div key={s.label} className="rounded border p-5" style={{ background: s.color, borderColor: s.color }}>
            <p className="text-2xl mb-1">{s.icon}</p>
            <p className="text-3xl font-extrabold" style={{ color: s.text }}>{s.value}</p>
            <p className="text-sm font-semibold mt-0.5" style={{ color: s.text }}>{s.label}</p>
          </div>
        ))}
      </div>

      {/* Tenant cards */}
      <div>
        <h3 className="text-lg font-bold mb-4" style={{ color: C.dark }}>Tenants</h3>
        <div className="grid lg:grid-cols-2 gap-6">
          {DEMO_TENANTS.map((t) => <SATenantCard key={t.id} tenant={t} />)}
        </div>
      </div>

      {/* Role guide */}
      <div className="rounded border border-gray-200 p-5 bg-gray-50">
        <h4 className="text-sm font-bold text-gray-700 mb-3">Role-scoped access guide</h4>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          {ROLE_GUIDE.map((r) => (
            <div key={r.role} className="flex items-start gap-2">
              <span className="px-1.5 py-0.5 rounded text-white font-bold shrink-0" style={{ background: r.color }}>{r.role}</span>
              <p className="text-gray-600">{r.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SATenantCard({ tenant }: { tenant: DemoTenant }) {
  const lowStock   = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
  return (
    <Link href={`/dashboard/tenants/${tenant.slug}`} className="block group">
      <div className="border-2 border-gray-200 group-hover:border-current group-hover:shadow-lg transition-all duration-200 overflow-hidden" style={{ borderRadius: 4 }}>
        <div className="px-5 py-4 flex items-center gap-3" style={{ background: tenant.color }}>
          <span className="text-4xl">{tenant.logo}</span>
          <div>
            <h4 className="font-bold text-white text-lg">{tenant.name}</h4>
            <p className="text-white/75 text-sm">{tenant.industry}</p>
          </div>
          <span className="ml-auto text-xs font-semibold bg-black/20 text-white px-2 py-0.5" style={{ borderRadius: 2 }}>{tenant.orgType}</span>
        </div>

        <div className="px-5 py-4 grid grid-cols-4 gap-3 text-center bg-white">
          {[
            { label: "Locations", value: tenant.warehouses.length },
            { label: "SKUs",      value: tenant.products.length },
            { label: "Units",     value: totalUnits.toLocaleString() },
            { label: "Low Stock", value: lowStock.length, warn: lowStock.length > 0 },
          ].map((s) => (
            <div key={s.label}>
              <p className={`text-xl font-extrabold ${s.warn ? "text-red-500" : "text-gray-900"}`}>{s.value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        <div className="px-5 py-2.5 border-t border-gray-100 bg-gray-50 flex flex-wrap gap-1.5">
          {tenant.warehouses.slice(0, 4).map((w) => (
            <span key={w.id} className="text-xs bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded">{w.name}</span>
          ))}
          {tenant.warehouses.length > 4 && (
            <span className="text-xs text-gray-400">+{tenant.warehouses.length - 4} more</span>
          )}
        </div>

        <div className="px-5 py-2.5 bg-white border-t border-gray-100">
          <span className="text-xs font-semibold group-hover:underline" style={{ color: tenant.color }}>
            Open tenant dashboard →
          </span>
        </div>
      </div>
    </Link>
  );
}

// ══ WM / NM Dashboard — single location scoped ════════════════════════════════

function LocationView({ user, tenant }: { user: SessionUser; tenant: DemoTenant }) {
  const warehouse = tenant.warehouses.find((w) => w.id === user.warehouseId);
  if (!warehouse) return null;

  const products = tenant.products.filter((p) => (p.stock[user.warehouseId!] ?? 0) > 0);
  const totalUnits = products.reduce((a, p) => a + (p.stock[user.warehouseId!] ?? 0), 0);
  const lowStock = products.filter((p) => (p.stock[user.warehouseId!] ?? 0) < p.reorderPoint);

  const typeLabel: Record<string, string> = {
    PRODUCTION: "Production Center",
    WAREHOUSE:  "Warehouse",
    SUBCENTER:  "Sub-center",
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="w-14 h-14 rounded flex items-center justify-center text-3xl shrink-0"
          style={{ background: tenant.color + "20", border: `2px solid ${tenant.color}` }}>
          {warehouse.type === "PRODUCTION" ? "🏭" : warehouse.type === "SUBCENTER" ? "🔖" : "🏗️"}
        </div>
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-gray-400">
            {tenant.name} · {typeLabel[warehouse.type]}
          </p>
          <h2 className="text-2xl font-extrabold mt-0.5" style={{ color: C.dark }}>{warehouse.name}</h2>
          <p className="text-sm text-gray-500">{warehouse.location} · {user.role} access</p>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Products with stock", value: products.length,             icon: "📦" },
          { label: "Total units",          value: totalUnits.toLocaleString(), icon: "📊" },
          { label: "Low stock alerts",     value: lowStock.length,             icon: "⚠️", warn: lowStock.length > 0 },
          { label: "Reorder needed",       value: lowStock.length > 0 ? "Yes" : "None", icon: "🔔", warn: lowStock.length > 0 },
        ].map((s) => (
          <div key={s.label} className="rounded border p-4 bg-white" style={{ borderRadius: 4, borderColor: s.warn ? "#FECACA" : "#E5E7EB", background: s.warn ? "#FFF1F2" : "#FFFFFF" }}>
            <p className="text-xl mb-1">{s.icon}</p>
            <p className={`text-2xl font-extrabold ${s.warn ? "text-red-600" : "text-gray-900"}`}>{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Inventory table — this location only */}
      <InventoryTable
        title={`${warehouse.name} — Inventory`}
        subtitle={`Showing all products with stock at this location`}
        products={products}
        getQty={(p) => p.stock[user.warehouseId!] ?? 0}
        singleLocation
        accentColor={tenant.color}
      />
    </div>
  );
}

// ══ TA Dashboard — full tenant summary ════════════════════════════════════════

function TenantAdminView({ user, tenant }: { user: SessionUser; tenant: DemoTenant }) {
  const lowStock   = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded flex items-center justify-center text-3xl shrink-0"
          style={{ background: tenant.color + "15", border: `2px solid ${tenant.color}` }}>
          {tenant.logo}
        </div>
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-gray-400">Tenant Admin</p>
          <h2 className="text-2xl font-extrabold mt-0.5" style={{ color: C.dark }}>{tenant.name}</h2>
          <p className="text-sm text-gray-500">{tenant.industry} · Full tenant access</p>
        </div>
        <Link href={`/dashboard/tenants/${tenant.slug}`}
          className="ml-auto text-sm font-semibold px-4 py-2 text-white"
          style={{ background: tenant.color, borderRadius: 4 }}>
          Full detail →
        </Link>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Locations",  value: tenant.warehouses.length,    icon: "📍" },
          { label: "SKUs",       value: tenant.products.length,      icon: "📦" },
          { label: "Total Units",value: totalUnits.toLocaleString(), icon: "📊" },
          { label: "Low Stock",  value: lowStock.length,             icon: "⚠️", warn: lowStock.length > 0 },
        ].map((s) => (
          <div key={s.label} className="border p-4 bg-white" style={{ borderRadius: 4, borderColor: "#E5E7EB" }}>
            <p className="text-xl mb-1">{s.icon}</p>
            <p className={`text-2xl font-extrabold ${s.warn ? "text-red-600" : "text-gray-900"}`}>{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Warehouse summary table */}
      <div className="bg-white border border-gray-200 overflow-hidden" style={{ borderRadius: 4 }}>
        <div className="px-5 py-4 border-b border-gray-100" style={{ background: tenant.color }}>
          <h3 className="font-bold text-white">Inventory Summary by Location</h3>
          <p className="text-white/70 text-xs mt-0.5">Total units per warehouse across all products</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Location</th>
                <th className="text-left px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Type</th>
                <th className="text-right px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Active SKUs</th>
                <th className="text-right px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Total Units</th>
                <th className="text-right px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Low Stock</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {tenant.warehouses.map((w, idx) => {
                const whUnits  = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
                const whSKUs   = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
                const whLow    = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0 && (p.stock[w.id] ?? 0) < p.reorderPoint).length;
                const typeLabels: Record<string, string> = { PRODUCTION: "Production", WAREHOUSE: "Warehouse", SUBCENTER: "Sub-center" };
                return (
                  <tr key={w.id} className={idx % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                    <td className="px-5 py-3 font-medium text-gray-900">
                      {w.parentId && <span className="text-gray-400 mr-1">↳</span>}
                      {w.name}
                      <p className="text-xs text-gray-400 font-normal">{w.location}</p>
                    </td>
                    <td className="px-5 py-3">
                      <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded ${
                        w.type === "PRODUCTION" ? "bg-orange-100 text-orange-700" :
                        w.type === "SUBCENTER"  ? "bg-purple-100 text-purple-700" :
                                                   "bg-blue-100 text-blue-700"
                      }`}>{typeLabels[w.type]}</span>
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums text-gray-700">{whSKUs}</td>
                    <td className="px-5 py-3 text-right tabular-nums font-bold text-gray-900">{whUnits.toLocaleString()}</td>
                    <td className="px-5 py-3 text-right">
                      {whLow > 0
                        ? <span className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded">{whLow} low</span>
                        : <span className="text-xs font-semibold text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded">OK</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-gray-200 bg-gray-50 font-bold">
                <td className="px-5 py-3 text-gray-700">Total</td>
                <td />
                <td className="px-5 py-3 text-right tabular-nums text-gray-700">{tenant.products.length}</td>
                <td className="px-5 py-3 text-right tabular-nums" style={{ color: "#1B4332" }}>
                  {totalUnits.toLocaleString()}
                </td>
                <td className="px-5 py-3 text-right">
                  {lowStock.length > 0
                    ? <span className="text-red-600">{lowStock.length} items</span>
                    : <span className="text-green-700">All OK</span>}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Full inventory table */}
      <InventoryTable
        title="Full Inventory — All Locations"
        subtitle={`${tenant.products.length} SKUs across ${tenant.warehouses.length} locations`}
        products={tenant.products}
        getQty={getTotalStock}
        singleLocation={false}
        accentColor={tenant.color}
      />
    </div>
  );
}

// ══ Shared inventory table component ══════════════════════════════════════════

function InventoryTable({
  title, subtitle, products, getQty, singleLocation, accentColor,
}: {
  title: string;
  subtitle: string;
  products: DemoProduct[];
  getQty: (p: DemoProduct) => number;
  singleLocation: boolean;
  accentColor: string;
}) {
  const categories = [...new Set(products.map((p) => p.category))];

  return (
    <div className="space-y-4">
      {categories.map((cat) => {
        const catProducts = products.filter((p) => p.category === cat);
        return (
          <div key={cat} className="bg-white border border-gray-200 overflow-hidden" style={{ borderRadius: 4 }}>
            <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
              <div>
                <h4 className="font-bold text-gray-800">{title}</h4>
                <p className="text-xs text-gray-500">{subtitle} · Category: {cat}</p>
              </div>
              <span className="text-xs font-semibold bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
                {catProducts.length} SKUs
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b-2 border-gray-200 bg-white">
                  <tr>
                    <th className="text-left px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">SKU</th>
                    <th className="text-left px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Product</th>
                    <th className="text-right px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">
                      {singleLocation ? "Stock (this location)" : "Total Stock"}
                    </th>
                    <th className="text-right px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Reorder Point</th>
                    <th className="px-5 py-3 text-xs font-bold text-gray-500 uppercase tracking-wider">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {catProducts.map((p, idx) => {
                    const qty   = getQty(p);
                    const isLow = qty < p.reorderPoint;
                    return (
                      <tr key={p.id} className={idx % 2 === 0 ? "bg-white" : "bg-gray-50/40"}>
                        <td className="px-5 py-3 font-mono text-xs text-gray-400">{p.sku}</td>
                        <td className="px-5 py-3 font-medium text-gray-900">{p.name}</td>
                        <td className="px-5 py-3 text-right font-bold text-gray-900 tabular-nums">{qty.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right text-gray-500 tabular-nums">{p.reorderPoint.toLocaleString()}</td>
                        <td className="px-5 py-3">
                          <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-0.5 border ${
                            isLow
                              ? "bg-red-50 text-red-600 border-red-200"
                              : "bg-green-50 text-green-700 border-green-200"
                          }`} style={{ borderRadius: 3 }}>
                            <span className={`w-1.5 h-1.5 rounded-full ${isLow ? "bg-red-500" : "bg-green-500"}`} />
                            {isLow ? "Low Stock" : "In Stock"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-gray-200 bg-gray-50 font-semibold">
                    <td colSpan={2} className="px-5 py-2.5 text-xs text-gray-600">{catProducts.length} products</td>
                    <td className="px-5 py-2.5 text-right text-sm tabular-nums font-bold" style={{ color: accentColor }}>
                      {catProducts.reduce((a, p) => a + getQty(p), 0).toLocaleString()}
                    </td>
                    <td /><td />
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

// ─── Static data ──────────────────────────────────────────────────────────────

const ROLE_GUIDE = [
  { role: "SA",  color: "#DC2626", desc: "Full platform — all tenants, all data" },
  { role: "TA",  color: "#7C3AED", desc: "Full tenant — all warehouses, all products" },
  { role: "NM",  color: "#2563EB", desc: "Production center — their location only" },
  { role: "WM",  color: "#0D9488", desc: "Warehouse — their location only" },
];
