"use client";

import { notFound } from "next/navigation";
import Link from "next/link";
import {
  getTenantBySlug,
  getTotalStock,
  getLowStockProducts,
  getChildren,
  type DemoWarehouse,
  type DemoProduct,
  type DemoTenant,
} from "@/lib/demo-data";

// Next.js 14: params is a plain object, not a Promise (Promise params is Next.js 15+)
export default function TenantPage({ params }: { params: { tenantId: string } }) {
  const { tenantId } = params;
  const tenant = getTenantBySlug(tenantId);
  if (!tenant) notFound();

  const lowStock = getLowStockProducts(tenant);
  const totalUnits = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
  const rootWarehouses = tenant.warehouses.filter((w) => w.parentId === null);

  return (
    <div className="p-6 space-y-8">
      <div className="flex items-center gap-4">
        <Link href="/dashboard" className="text-gray-400 hover:text-gray-600 transition-colors text-sm">
          ← Dashboard
        </Link>
        <div className={`w-12 h-12 rounded-xl ${tenant.bgClass} flex items-center justify-center text-2xl flex-shrink-0`}>
          {tenant.logo}
        </div>
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{tenant.name}</h2>
          <p className="text-gray-500 text-sm">{tenant.description}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {[
          { label: "Locations",     value: tenant.warehouses.length,    icon: "📍", sub: `${tenant.warehouses.filter(w => w.type === "MWH").length} main WH` },
          { label: "SKUs",          value: tenant.products.length,      icon: "📦", sub: `${Array.from(new Set(tenant.products.map(p => p.category))).length} categories` },
          { label: "Total Units",   value: totalUnits.toLocaleString(), icon: "📊", sub: "across all WH" },
          { label: "Low Stock",     value: lowStock.length,             icon: "⚠️", sub: lowStock.length > 0 ? "need restocking" : "all good", warn: lowStock.length > 0 },
          { label: "Staff Accounts",value: tenant.users.length,         icon: "👤", sub: `${tenant.users.filter(u => u.role === "WM").length} WM, ${tenant.users.filter(u => u.role === "NM").length} NM` },
        ].map((s) => (
          <div key={s.label} className={`bg-white rounded-xl border p-4 ${s.warn ? "border-red-200 bg-red-50" : "border-gray-200"}`}>
            <p className="text-2xl mb-1">{s.icon}</p>
            <p className={`text-2xl font-bold ${s.warn ? "text-red-600" : "text-gray-900"}`}>{s.value}</p>
            <p className="text-xs font-medium text-gray-700 mt-0.5">{s.label}</p>
            <p className="text-xs text-gray-400">{s.sub}</p>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100">
              <h3 className="font-semibold text-gray-900">Location Hierarchy</h3>
            </div>
            <div className="p-4 space-y-1">
              {rootWarehouses.map((w) => (
                <WarehouseNode key={w.id} warehouse={w} allWarehouses={tenant.warehouses} tenant={tenant} depth={0} />
              ))}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100">
              <h3 className="font-semibold text-gray-900">User Accounts</h3>
            </div>
            <div className="divide-y divide-gray-100">
              {tenant.users.map((u) => (
                <div key={u.id} className="px-5 py-3 flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{u.name}</p>
                    <p className="text-xs text-gray-500 font-mono truncate">{u.email}</p>
                    {u.warehouseName && (
                      <p className="text-xs text-gray-400 mt-0.5">📍 {u.warehouseName}</p>
                    )}
                  </div>
                  <RolePill role={u.role} />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {Array.from(new Set(tenant.products.map((p) => p.category))).map((cat) => (
            <CategoryTable
              key={cat}
              category={cat}
              products={tenant.products.filter((p) => p.category === cat)}
              warehouses={tenant.warehouses}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function WarehouseNode({ warehouse, allWarehouses, tenant, depth }: {
  warehouse: DemoWarehouse; allWarehouses: DemoWarehouse[]; tenant: DemoTenant; depth: number;
}) {
  const children = getChildren(allWarehouses, warehouse.id);
  const icons: Record<string, string> = { MWH: "🏭", RWH: "🏗️", WH: "🏗️", SUB_WH: "🔖" };
  const whStock = tenant.products.reduce((acc, p) => acc + (p.stock[warehouse.id] ?? 0), 0);

  return (
    /* --dp: depth-computed left padding converted to CSS custom property */
    <div style={{ "--dp": `${depth * 16}px` } as React.CSSProperties} className="pl-[var(--dp)]">
      <div className="flex items-start gap-2 py-2 rounded-lg hover:bg-gray-50 px-2 transition-colors">
        <span className="text-base mt-0.5 flex-shrink-0">{icons[warehouse.type] ?? "📦"}</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-900 truncate">{warehouse.name}</p>
          <p className="text-xs text-gray-400 truncate">{warehouse.location}</p>
          <p className="text-xs text-gray-500 mt-0.5">{whStock.toLocaleString()} units</p>
        </div>
        <TypeBadge type={warehouse.type} />
      </div>
      {children.length > 0 && (
        <div className="border-l border-dashed border-gray-200 ml-4">
          {children.map((c) => (
            <WarehouseNode key={c.id} warehouse={c} allWarehouses={allWarehouses} tenant={tenant} depth={1} />
          ))}
        </div>
      )}
    </div>
  );
}

function TypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    MWH:    "bg-orange-100 text-orange-700",
    RWH:    "bg-blue-100 text-blue-700",
    WH:     "bg-gray-100 text-gray-600",
    SUB_WH: "bg-purple-100 text-purple-700",
  };
  const labels: Record<string, string> = { MWH: "MWH", RWH: "RWH", WH: "WH", SUB_WH: "Sub" };
  return (
    <span className={`flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium ${styles[type] ?? "bg-gray-100 text-gray-600"}`}>
      {labels[type] ?? type}
    </span>
  );
}

function RolePill({ role }: { role: string }) {
  const colors: Record<string, string> = {
    TA: "bg-purple-100 text-purple-700",
    NM: "bg-blue-100 text-blue-700",
    WM: "bg-teal-100 text-teal-700",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${colors[role] ?? "bg-gray-100 text-gray-600"}`}>
      {role}
    </span>
  );
}

function CategoryTable({ category, products, warehouses }: {
  category: string; products: DemoProduct[]; warehouses: DemoWarehouse[];
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
        <h4 className="text-sm font-semibold text-gray-700">{category}</h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left px-4 py-2 font-semibold text-gray-500">SKU</th>
              <th className="text-left px-4 py-2 font-semibold text-gray-500">Product</th>
              {warehouses.slice(0, 4).map((w) => (
                <th key={w.id} className="text-right px-3 py-2 font-semibold text-gray-500 whitespace-nowrap">
                  {w.name.replace(" Production Center", "").replace(" WH", "").replace(" Subcenter", "-Sub")}
                </th>
              ))}
              <th className="text-right px-4 py-2 font-semibold text-gray-500">Total</th>
              <th className="text-left px-4 py-2 font-semibold text-gray-500">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {products.map((p) => {
              const total = getTotalStock(p);
              const isLow = total < p.reorderPoint * warehouses.length;
              return (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-gray-400">{p.sku}</td>
                  <td className="px-4 py-2 font-medium text-gray-900 whitespace-nowrap">{p.name}</td>
                  {warehouses.slice(0, 4).map((w) => (
                    <td key={w.id} className="px-3 py-2 text-right text-gray-600">
                      {(p.stock[w.id] ?? 0).toLocaleString()}
                    </td>
                  ))}
                  <td className="px-4 py-2 text-right font-bold text-gray-900">{total.toLocaleString()}</td>
                  <td className="px-4 py-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${isLow ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>
                      {isLow ? "Low" : "OK"}
                    </span>
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
