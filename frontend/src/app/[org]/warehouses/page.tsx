"use client";

import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";
import { t } from "@/lib/i18n";

function sortByHierarchy(warehouses: DemoWarehouse[]): DemoWarehouse[] {
  const result: DemoWarehouse[] = [];
  const placed = new Set<string>();
  function place(parentId: string | null) {
    for (const wh of warehouses) {
      if (wh.parentId === parentId && !placed.has(wh.id)) {
        result.push(wh); placed.add(wh.id); place(wh.id);
      }
    }
  }
  place(null);
  for (const wh of warehouses) { if (!placed.has(wh.id)) result.push(wh); }
  return result;
}

function getDepth(warehouseId: string, warehouses: DemoWarehouse[], visited = new Set<string>()): number {
  if (visited.has(warehouseId)) return 0;
  visited.add(warehouseId);
  const wh = warehouses.find((w) => w.id === warehouseId);
  if (!wh?.parentId) return 0;
  return 1 + getDepth(wh.parentId, warehouses, visited);
}

const TYPE_CLASS: Record<string, string> = {
  MWH:    "bg-amber-100 text-amber-800",
  RWH:    "bg-blue-100  text-blue-800",
  WH:     "bg-gray-100  text-gray-700",
  SUB_WH: "bg-violet-100 text-violet-800",
};

export default function WarehousesPage() {
  const { org } = useParams() as { org: string };
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const sorted = sortByHierarchy(tenant.warehouses);

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("warehouses.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{tenant.name} · {tenant.warehouses.length} {t("warehouses.locations")}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        {/* uses --tenant-color from [org]/layout.tsx */}
        <div className="h-[3px] bg-[var(--tenant-color)]" />
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-50 border-b-2 border-gray-200">
              {["warehouses.col_name","warehouses.col_location","table.type","warehouses.col_manager","table.total_units","table.skus"].map((key) => (
                <th key={key} className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">{t(key)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((w, idx) => {
              const whUnits = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
              const whSKUs  = tenant.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length;
              const typeClass = TYPE_CLASS[w.type] ?? "bg-gray-100 text-gray-500";
              const manager   = tenant.users.find((u) => u.warehouseId === w.id);
              const depth     = getDepth(w.id, tenant.warehouses);

              return (
                <tr key={w.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  {/* --dp: depth-computed left padding; px-4 becomes pr-4 + pl-[var(--dp)] */}
                  <td
                    className="pr-4 py-2.5 font-semibold text-gray-800 pl-[var(--dp)]"
                    style={{ "--dp": `${16 + depth * 24}px` } as React.CSSProperties}
                  >
                    {depth > 0 && <span className="text-gray-300 mr-1.5 font-mono">{"↳".repeat(depth)}</span>}
                    {w.name}
                  </td>
                  <td className="px-4 py-2.5 text-gray-500">{w.location}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                      {t(`warehouse_type.${w.type}`)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">{manager?.name ?? "—"}</td>
                  <td className="px-4 py-2.5 font-bold text-gray-900">{whUnits.toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-gray-700">{whSKUs}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
