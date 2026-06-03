"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";

/* ── Types ─────────────────────────────────────────────────────────────────── */

interface ApiStockRow {
  product_id: string;
  warehouse_id: string;
  warehouse_name: string;
  warehouse_type: string | null;
  current_stock: number;
}

interface OrgNodeRow {
  id: string;
  name: string;
  address: string | null;
  hierarchy_level: number;
  level_name: string | null;
  is_stock_holding: boolean;
  parent_node_id: string | null;
  manager_name: string | null;
  manager_role: string | null;
  children: OrgNodeRow[];
}

/* ── Demo helpers ───────────────────────────────────────────────────────────── */

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

/* ── Display helpers ────────────────────────────────────────────────────────── */

const TYPE_CLASS: Record<string, string> = {
  MWH:    "bg-amber-100 text-amber-800",
  RWH:    "bg-blue-100  text-blue-800",
  WH:     "bg-gray-100  text-gray-700",
  SUB_WH: "bg-violet-100 text-violet-800",
};
const DB_TYPE_MAP: Record<string, DemoWarehouse["type"]> = {
  FACTORY: "MWH", REGIONAL: "RWH", RETAIL: "WH", SUBCENTER: "SUB_WH",
};

function flattenNodes(nodes: OrgNodeRow[]): OrgNodeRow[] {
  const out: OrgNodeRow[] = [];
  function visit(list: OrgNodeRow[]) {
    for (const n of list) { out.push(n); visit(n.children); }
  }
  visit(nodes);
  return out;
}

/* ── Page ───────────────────────────────────────────────────────────────────── */

export default function WarehousesPage() {
  const { org } = useParams() as { org: string };
  const tenantName = useTenantName(org);
  const session    = getSession();
  const callerRole = session?.role ?? "WM";
  const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;

  // Resolve correct tenant UUID — same pattern as personnel page (BUG 4 fix)
  const isSAViewing = callerRole === "SA" && org !== SA_ORG_SLUG;
  const { data: tenantMeta } = useQuery<{ id: string; name: string }>({
    queryKey: ["tenant-meta", org],
    queryFn:  () => api.get<{ id: string; name: string }>(`/api/v1/tenants/${org}`),
    enabled:  isSAViewing,
    staleTime: 60_000,
    retry: false,
  });
  const tenantId = isSAViewing
    ? (tenantMeta?.id ?? "")
    : (session?.tenantId ?? "");

  // Stock analytics — used for units/SKU counts in both demo and gateway modes
  const { data: stockData = [] } = useQuery<ApiStockRow[]>({
    queryKey: ["analytics-stock", org],
    queryFn:  () => api.get<ApiStockRow[]>("/api/v1/inventory/analytics/stock"),
    enabled:  isGatewayMode,
    staleTime: 30_000,
  });

  // Org nodes — the single source of truth for facilities (BUG 3 fix)
  const { data: orgNodes = [] } = useQuery<OrgNodeRow[]>({
    queryKey: ["org-nodes", tenantId],
    queryFn:  () => api.get<OrgNodeRow[]>(`/api/v1/tenants/${tenantId}/nodes`),
    enabled:  isGatewayMode && !!tenantId,
    staleTime: 60_000,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);

  // In demo mode without a matching tenant, nothing to show
  if (!tenant && !isGatewayMode) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  // ── Gateway mode: build rows from org nodes (single source of truth) ────────
  // Org nodes created in Org Setup ARE the warehouses — no separate warehouses table.
  // Cross-reference with stock analytics for units/SKU counts by facility UUID.
  const stockById = new Map<string, { units: number; skus: Set<string> }>();
  for (const row of stockData) {
    const entry = stockById.get(row.warehouse_id) ?? { units: 0, skus: new Set<string>() };
    entry.units += Number(row.current_stock);
    if (Number(row.current_stock) > 0) entry.skus.add(row.product_id);
    stockById.set(row.warehouse_id, entry);
  }

  const flat = flattenNodes(orgNodes);

  // ── Demo mode: use tenant.warehouses with hierarchy sort ──────────────────
  const sorted = isGatewayMode || !tenant ? [] : sortByHierarchy(tenant.warehouses);
  const warehouseCount = isGatewayMode ? flat.length : (tenant?.warehouses.length ?? 0);

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("warehouses.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{tenantName ?? org} · {warehouseCount} {t("warehouses.locations")}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-50 border-b-2 border-gray-200">
              {["warehouses.col_name","warehouses.col_location","table.type","warehouses.col_manager","table.total_units","table.skus"].map((key) => (
                <th key={key} className="px-4 py-2.5 text-left text-xs font-bold text-gray-500 uppercase tracking-wide">{t(key)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isGatewayMode && flat.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-400">
                  {t("common.no_data")}
                </td>
              </tr>
            )}
            {isGatewayMode ? (
              flat.map((node, idx) => {
                const stock  = stockById.get(node.id) ?? { units: 0, skus: new Set() };
                const typeKey = DB_TYPE_MAP[node.level_name ?? ""] ?? "WH";
                const typeClass = TYPE_CLASS[typeKey] ?? "bg-gray-100 text-gray-500";
                return (
                  <tr key={node.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-4 py-2.5 font-semibold text-gray-800">
                      {node.hierarchy_level > 1 && (
                        <span className="text-gray-300 mr-1.5 font-mono">{"↳".repeat(node.hierarchy_level - 1)}</span>
                      )}
                      {node.name}
                      {!node.is_stock_holding && (
                        <span className="ml-2 text-[10px] text-gray-400 font-normal">(no stock)</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-gray-500">{node.address ?? "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${typeClass}`}>
                        {node.level_name ?? `L${node.hierarchy_level}`}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-700">
                      {node.manager_name
                        ? <>
                            {node.manager_name}
                            {node.manager_role && (
                              <span className="ml-1.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">
                                {node.manager_role}
                              </span>
                            )}
                          </>
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 font-bold text-gray-900">{stock.units.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-gray-700">{stock.skus.size}</td>
                  </tr>
                );
              })
            ) : (
              sorted.map((w, idx) => {
                const whUnits = tenant?.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0) ?? 0;
                const whSKUs  = tenant?.products.filter((p) => (p.stock[w.id] ?? 0) > 0).length ?? 0;
                const typeClass = TYPE_CLASS[w.type] ?? "bg-gray-100 text-gray-500";
                const manager   = tenant?.users.find((u) => u.warehouseId === w.id);
                const depth     = getDepth(w.id, tenant?.warehouses ?? []);
                return (
                  <tr key={w.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    {/* indent is dynamic (depth * 24px) — must use style for this one property */}
                    <td className="px-4 py-2.5 font-semibold text-gray-800" style={{ paddingLeft: `${16 + depth * 24}px` }}>
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
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
