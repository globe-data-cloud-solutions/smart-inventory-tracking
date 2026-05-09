"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSession, type SessionUser } from "@/lib/demo-auth";
import { DEMO_TENANTS, getLowStockProducts, getTotalStock, type DemoTenant } from "@/lib/demo-data";

export default function DashboardPage() {
  const [user, setUser] = useState<SessionUser | null>(null);

  useEffect(() => {
    setUser(getSession());
  }, []);

  if (!user) return null;

  const visibleTenants =
    user.role === "SA"
      ? DEMO_TENANTS
      : DEMO_TENANTS.filter((t) => t.id === user.tenantId);

  return (
    <div className="p-6 space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">
          Welcome back, {user.name.split(" ")[0]}
        </h2>
        <p className="text-gray-500 text-sm mt-1">
          {user.role === "SA"
            ? "System Administrator · Access to all tenants"
            : `${user.tenantName} · ${user.warehouseName ?? "All warehouses"}`}
        </p>
      </div>

      {user.role === "SA" && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: "Tenants", value: "2", icon: "🏢", color: "bg-blue-50 text-blue-700 border-blue-200" },
            { label: "Total Locations", value: "12", icon: "📍", color: "bg-purple-50 text-purple-700 border-purple-200" },
            { label: "Active SKUs", value: `${DEMO_TENANTS.reduce((a, t) => a + t.products.length, 0)}`, icon: "📦", color: "bg-teal-50 text-teal-700 border-teal-200" },
            { label: "Total Users", value: `${DEMO_TENANTS.reduce((a, t) => a + t.users.length, 0) + 1}`, icon: "👤", color: "bg-amber-50 text-amber-700 border-amber-200" },
          ].map((s) => (
            <div key={s.label} className={`rounded-xl border p-4 ${s.color}`}>
              <p className="text-2xl mb-1">{s.icon}</p>
              <p className="text-3xl font-bold">{s.value}</p>
              <p className="text-sm font-medium mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {user.role === "SA" && (
        <div>
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Tenants</h3>
          <div className="grid lg:grid-cols-2 gap-6">
            {visibleTenants.map((t) => (
              <TenantDashCard key={t.id} tenant={t} />
            ))}
          </div>
        </div>
      )}

      {user.role !== "SA" && visibleTenants[0] && (
        <TenantFullView tenant={visibleTenants[0]} user={user} />
      )}
    </div>
  );
}

function TenantDashCard({ tenant }: { tenant: DemoTenant }) {
  const lowStock = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((acc, p) => acc + getTotalStock(p), 0);

  return (
    <Link href={`/dashboard/tenants/${tenant.slug}`} className="block group">
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm group-hover:shadow-md group-hover:border-brand-200 transition-all">
        <div className={`${tenant.bgClass} p-5 flex items-center gap-4`}>
          <span className="text-4xl">{tenant.logo}</span>
          <div>
            <h4 className="text-white font-bold text-lg">{tenant.name}</h4>
            <p className="text-white/80 text-sm">{tenant.industry}</p>
          </div>
          <span className="ml-auto text-white/60 text-xs font-medium bg-white/10 px-2 py-1 rounded">
            {tenant.orgType}
          </span>
        </div>

        <div className="p-5 grid grid-cols-4 gap-4">
          {[
            { label: "Locations",   value: tenant.warehouses.length },
            { label: "SKUs",        value: tenant.products.length },
            { label: "Total Units", value: totalUnits.toLocaleString() },
            { label: "Low Stock",   value: lowStock.length, warn: lowStock.length > 0 },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <p className={`text-xl font-bold ${s.warn ? "text-red-500" : "text-gray-900"}`}>{s.value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        <div className="px-5 pb-4 flex flex-wrap gap-1.5">
          {tenant.warehouses.slice(0, 5).map((w) => (
            <span key={w.id} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{w.name}</span>
          ))}
          {tenant.warehouses.length > 5 && (
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">+{tenant.warehouses.length - 5} more</span>
          )}
        </div>
        <div className="px-5 pb-4">
          <span className="text-xs font-medium text-brand-600 group-hover:underline">Open tenant dashboard →</span>
        </div>
      </div>
    </Link>
  );
}

function TenantFullView({ tenant, user }: { tenant: DemoTenant; user: SessionUser }) {
  const myWarehouse = user.warehouseId
    ? tenant.warehouses.find((w) => w.id === user.warehouseId)
    : null;

  const relevantProducts = tenant.products.filter((p) =>
    user.warehouseId ? (p.stock[user.warehouseId] ?? 0) > 0 : true
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Products in scope", value: relevantProducts.length, icon: "📦" },
          { label: "Total units", value: relevantProducts.reduce((a, p) => a + (user.warehouseId ? (p.stock[user.warehouseId] ?? 0) : getTotalStock(p)), 0).toLocaleString(), icon: "📊" },
          { label: "Low stock alerts", value: getLowStockProducts(tenant).length, icon: "⚠️" },
          { label: "Warehouses in view", value: myWarehouse ? 1 : tenant.warehouses.length, icon: "🏗️" },
        ].map((s) => (
          <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-2xl mb-1">{s.icon}</p>
            <p className="text-2xl font-bold text-gray-900">{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900">Inventory</h3>
          {myWarehouse && <span className="text-sm text-gray-500">📍 {myWarehouse.name}</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">SKU</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Product</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Category</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  {user.warehouseId ? "My Stock" : "Total Stock"}
                </th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {relevantProducts.map((p) => {
                const qty = user.warehouseId ? (p.stock[user.warehouseId] ?? 0) : getTotalStock(p);
                const isLow = qty < p.reorderPoint;
                return (
                  <tr key={p.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3 font-mono text-xs text-gray-500">{p.sku}</td>
                    <td className="px-6 py-3 font-medium text-gray-900">{p.name}</td>
                    <td className="px-6 py-3 text-gray-500">{p.category}</td>
                    <td className="px-6 py-3 text-right font-semibold text-gray-900">{qty.toLocaleString()}</td>
                    <td className="px-6 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${isLow ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>
                        {isLow ? "⚠️ Low" : "✓ OK"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
