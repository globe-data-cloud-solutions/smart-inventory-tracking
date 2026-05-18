"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";
import { useAuditStore, type AuditLogEntry } from "@/lib/audit-log-state";
import { t } from "@/lib/i18n";

const CATEGORY_CLASS: Record<string, { bg: string; text: string; icon: string }> = {
  TRANSFER:   { bg: "bg-blue-100",   text: "text-blue-800",    icon: "🔄" },
  INVENTORY:  { bg: "bg-green-100",  text: "text-green-800",   icon: "📦" },
  ADJUSTMENT: { bg: "bg-amber-100",  text: "text-amber-800",   icon: "✏️" },
  SYSTEM:     { bg: "bg-gray-100",   text: "text-gray-700",    icon: "⚙️" },
};

function buildScopeNames(
  warehouseId: string | undefined,
  role: string,
  warehouses: DemoWarehouse[],
): Set<string> | null {
  if (!warehouseId || ["TA", "SA"].includes(role)) return null;
  const userWH = warehouses.find((w) => w.id === warehouseId);
  if (!userWH) return null;
  const scopeIds = new Set<string>([warehouseId]);
  function addDescendants(parentId: string) {
    for (const wh of warehouses) {
      if (wh.parentId === parentId && !scopeIds.has(wh.id)) {
        scopeIds.add(wh.id); addDescendants(wh.id);
      }
    }
  }
  addDescendants(warehouseId);
  return new Set(warehouses.filter((w) => scopeIds.has(w.id)).map((w) => w.name));
}

function entryInScope(entry: AuditLogEntry, scopeNames: Set<string> | null): boolean {
  if (!scopeNames) return true;
  return (!!entry.fromWarehouse && scopeNames.has(entry.fromWarehouse)) ||
         (!!entry.toWarehouse   && scopeNames.has(entry.toWarehouse));
}

const selectCls = "px-2.5 py-1.5 text-xs border border-gray-300 rounded-md bg-white outline-none cursor-pointer";

export default function AuditLogPage() {
  const { org } = useParams() as { org: string };
  const user    = getSession();
  const allEntries = useAuditStore((s) => s.entries);
  const [categoryFilter, setCategoryFilter] = useState<"ALL" | "TRANSFER" | "INVENTORY" | "ADJUSTMENT">("ALL");
  const [search, setSearch] = useState("");

  if (!user) return null;
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant)   return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const scopeNames = buildScopeNames(user.warehouseId, user.role, tenant.warehouses);

  const scopedEntries = useMemo(
    () => allEntries
      .filter((e) => e.tenantSlug === org && entryInScope(e, scopeNames))
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allEntries, org, user.warehouseId, user.role],
  );

  const sourceOptions = useMemo(() => {
    const names = new Set<string>();
    for (const e of scopedEntries) { if (e.fromWarehouse) names.add(e.fromWarehouse); }
    return Array.from(names).sort();
  }, [scopedEntries]);

  const defaultSource = scopedEntries.find((e) => e.fromWarehouse)?.fromWarehouse ?? "";
  const [sourceFilter, setSourceFilter] = useState(defaultSource);

  const sourceFiltered = useMemo(
    () => sourceFilter ? scopedEntries.filter((e) => e.fromWarehouse === sourceFilter) : scopedEntries,
    [scopedEntries, sourceFilter],
  );

  const destinationOptions = useMemo(() => {
    const names = new Set<string>();
    for (const e of sourceFiltered) { if (e.toWarehouse) names.add(e.toWarehouse); }
    return Array.from(names).sort();
  }, [sourceFiltered]);

  const [destinationFilter, setDestinationFilter] = useState("");

  function handleSourceChange(v: string) { setSourceFilter(v); setDestinationFilter(""); }

  const filtered = useMemo(() => {
    let rows = sourceFiltered;
    if (destinationFilter) rows = rows.filter((e) => e.toWarehouse === destinationFilter);
    if (categoryFilter !== "ALL") rows = rows.filter((e) => e.category === categoryFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter((e) =>
        e.action.toLowerCase().includes(q) ||
        e.resourceRef.toLowerCase().includes(q) ||
        (e.productName  ?? "").toLowerCase().includes(q) ||
        (e.fromWarehouse ?? "").toLowerCase().includes(q) ||
        (e.toWarehouse  ?? "").toLowerCase().includes(q) ||
        e.userName.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [sourceFiltered, destinationFilter, categoryFilter, search]);

  const counts = {
    TRANSFER:   scopedEntries.filter((e) => e.category === "TRANSFER").length,
    INVENTORY:  scopedEntries.filter((e) => e.category === "INVENTORY").length,
    ADJUSTMENT: scopedEntries.filter((e) => e.category === "ADJUSTMENT").length,
  };

  const userWH     = tenant.warehouses.find((w) => w.id === user.warehouseId);
  const scopeLabel = !scopeNames ? t("audit.all_facilities")
    : userWH ? `${userWH.name} ${t("audit.scope_and_below")}` : t("audit.your_facilities");

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("audit.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">
          {tenant.name} · {scopeLabel} · {scopedEntries.length} {t("audit.events")} · {t("audit.subtitle")}
        </p>
      </div>

      {/* Category chips */}
      <div className="flex gap-2 mb-4 flex-wrap items-center">
        {(["ALL", "TRANSFER", "INVENTORY", "ADJUSTMENT"] as const).map((cat) => {
          const count = cat === "ALL" ? scopedEntries.length : counts[cat];
          const cs    = (cat !== "ALL" ? CATEGORY_CLASS[cat] : null) ?? { bg: "bg-gray-100", text: "text-gray-700", icon: "" };
          const active = categoryFilter === cat;
          return (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`text-xs font-bold px-3 py-1 rounded-full cursor-pointer border-2 transition-all ${
                active
                  ? `${cs.bg} ${cs.text} border-[#0f2d1f]`
                  : "bg-gray-50 text-gray-500 border-transparent hover:border-gray-300"
              }`}
            >
              {cs.icon ? `${cs.icon} ` : ""}{cat} ({count})
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex gap-2.5 mb-5 flex-wrap items-center">
        <div className="flex items-center gap-1.5">
          <label className="text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
            {t("audit.source")}
          </label>
          <select value={sourceFilter} onChange={(e) => handleSourceChange(e.target.value)} className={selectCls}>
            <option value="">{t("audit.all_sources")}</option>
            {sourceOptions.map((wh) => <option key={wh} value={wh}>{wh}</option>)}
          </select>
        </div>

        <div className="flex items-center gap-1.5">
          <label className="text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
            {t("audit.destination")}
          </label>
          <select
            value={destinationFilter}
            onChange={(e) => setDestinationFilter(e.target.value)}
            className={selectCls}
            disabled={destinationOptions.length === 0}
          >
            <option value="">{t("audit.all_destinations")}</option>
            {destinationOptions.map((wh) => <option key={wh} value={wh}>{wh}</option>)}
          </select>
          {sourceFilter && destinationOptions.length > 0 && (
            <span className="text-[11px] text-gray-400">({destinationOptions.length})</span>
          )}
        </div>

        {(sourceFilter || destinationFilter) && (
          <button
            onClick={() => { setSourceFilter(""); setDestinationFilter(""); }}
            className="text-xs text-gray-500 bg-transparent border-0 cursor-pointer underline p-0"
          >
            {t("audit.clear_filters")}
          </button>
        )}

        <div className="relative flex-1 min-w-[200px]">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("audit.search_placeholder")}
            className="w-full pl-8 pr-2.5 py-1.5 text-sm border border-gray-300 rounded-md outline-none"
          />
        </div>

        <span className="text-xs text-gray-400 whitespace-nowrap">
          {filtered.length} / {scopedEntries.length}
        </span>
      </div>

      {/* Scope note */}
      {scopeNames && (
        <div className="bg-blue-50 border border-blue-200 rounded-md px-3.5 py-2 mb-4 text-xs text-blue-800">
          <strong>{t("audit.scoped_view")}:</strong>{" "}
          {Array.from(scopeNames).join(", ")}.{" "}
          {userWH?.type === "RWH" && t("audit.regional_hierarchy_note")}
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant.color }} />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {[
                  "audit.timestamp", "audit.user", "audit.role", "audit.category",
                  "audit.action", "audit.resource", "lots.product", "audit.qty_unit",
                  "audit.from", "audit.to", "audit.notes",
                ].map((key) => (
                  <th key={key} className="px-3 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    {t(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, idx) => {
                const cs = CATEGORY_CLASS[e.category] ?? CATEGORY_CLASS.SYSTEM!;
                return (
                  <tr key={e.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-3 py-2 text-gray-400 whitespace-nowrap font-mono text-[10px]">
                      {new Date(e.timestamp).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 font-semibold text-gray-800 whitespace-nowrap text-[11px]">{e.userName}</td>
                    <td className="px-3 py-2">
                      <span className="text-[10px] font-bold bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">{e.role}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${cs.bg} ${cs.text}`}>
                        {cs.icon} {e.category}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-700 whitespace-nowrap text-[11px]">{e.action}</td>
                    <td className="px-3 py-2 font-mono text-gray-500 text-[10px]">{e.resourceRef || "—"}</td>
                    <td className="px-3 py-2 text-gray-800 text-[11px] max-w-[160px] overflow-hidden text-ellipsis whitespace-nowrap">{e.productName || "—"}</td>
                    <td className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap text-[11px]">{e.quantityStr || "—"}</td>
                    <td className="px-3 py-2 text-[11px] whitespace-nowrap text-gray-700">{e.fromWarehouse || <span className="text-gray-300">—</span>}</td>
                    <td className="px-3 py-2 text-[11px] whitespace-nowrap text-gray-700">{e.toWarehouse   || <span className="text-gray-300">—</span>}</td>
                    <td className="px-3 py-2 text-gray-400 text-[11px] max-w-[200px]">{e.notes || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filtered.length === 0 && (
          <div className="p-12 text-center">
            {scopedEntries.length === 0 ? (
              <div>
                <p className="text-gray-400 text-sm m-0 mb-2">{t("audit.no_activity")}</p>
                <p className="text-gray-300 text-xs m-0">{t("audit.no_activity_hint")}</p>
              </div>
            ) : (
              <p className="text-gray-400 text-sm">{t("audit.no_match")}</p>
            )}
          </div>
        )}
      </div>

      <p className="mt-3 text-xs text-gray-400">{t("audit.footer_note")}</p>
    </div>
  );
}
