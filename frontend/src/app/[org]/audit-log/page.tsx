"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";

const CATEGORY_CLASS: Record<string, { bg: string; text: string; icon: string }> = {
  TRANSFER:   { bg: "bg-blue-100",   text: "text-blue-800",    icon: "🔄" },
  INVENTORY:  { bg: "bg-green-100",  text: "text-green-800",   icon: "📦" },
  ADJUSTMENT: { bg: "bg-amber-100",  text: "text-amber-800",   icon: "✏️" },
  SYSTEM:     { bg: "bg-gray-100",   text: "text-gray-700",    icon: "⚙️" },
};

const DECISION_CLASS: Record<string, string> = {
  GRANTED:     "bg-green-100 text-green-800",
  DENIED:      "bg-red-100 text-red-800",
  CONDITIONAL: "bg-amber-100 text-amber-800",
};

// TA/SA/AU see the entire tenant audit log; NM is tenant-wide by current
// scoping (see backend audit_log.py _TENANT_WIDE_ROLES). All other roles
// (RM/WM/LM) see only activity within their facility subtree.
const TENANT_WIDE_ROLES = new Set(["TA", "SA", "AU", "NM"]);

const PAGE_SIZE = 50;

interface AuditLogItem {
  id: string;
  timestamp: string;
  user_id: string | null;
  user_name: string | null;
  role: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  decision: string;
  reason: string | null;
  abac_context: Record<string, unknown> | null;
}

type Category = "TRANSFER" | "INVENTORY" | "ADJUSTMENT" | "SYSTEM";

function getCategory(action: string): Category {
  if (action.startsWith("transfer:"))   return "TRANSFER";
  if (action.startsWith("inventory:"))  return "INVENTORY";
  if (action.startsWith("adjustment:")) return "ADJUSTMENT";
  return "SYSTEM";
}

function getActionLabel(action: string): string {
  const key = `audit.actions.${action.replace(/:/g, "_")}`;
  const label = t(key);
  return label !== key ? label : action;
}

function getActedOnBehalfOf(abacContext: Record<string, unknown> | null): string | undefined {
  const v = abacContext?.["acted_on_behalf_of"];
  return typeof v === "string" ? v : undefined;
}

const selectCls = "px-2.5 py-1.5 text-xs border border-gray-300 rounded-md bg-white outline-none cursor-pointer";

export default function AuditLogPage() {
  const { org } = useParams() as { org: string };
  const tenantName = useTenantName(org);
  const user = getSession();
  const [page, setPage] = useState(0); // zero-based for display; backend pages are 1-based
  const [categoryFilter, setCategoryFilter] = useState<"ALL" | Category>("ALL");
  const [search, setSearch] = useState("");

  const { data: entries = [], isLoading } = useQuery<AuditLogItem[]>({
    queryKey: ["audit-log", org, page],
    queryFn: () => api.get<AuditLogItem[]>(`/api/v1/audit-log/?page=${page + 1}&limit=${PAGE_SIZE}`),
    enabled: IS_GATEWAY_MODE && org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  if (!user) return null;
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const isTenantWide = TENANT_WIDE_ROLES.has(user.role ?? "");
  const scopeLabel = isTenantWide ? t("audit.viewing_all_activity") : t("audit.viewing_facility_activity");

  const filtered = entries.filter((e) => {
    if (categoryFilter !== "ALL" && getCategory(e.action) !== categoryFilter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const haystack = [
        getActionLabel(e.action),
        e.action,
        e.resource_type ?? "",
        e.user_name ?? "",
        e.role ?? "",
      ].join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  const counts = {
    TRANSFER:   entries.filter((e) => getCategory(e.action) === "TRANSFER").length,
    INVENTORY:  entries.filter((e) => getCategory(e.action) === "INVENTORY").length,
    ADJUSTMENT: entries.filter((e) => getCategory(e.action) === "ADJUSTMENT").length,
  };

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("audit.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">
          {tenantName ?? org} · {scopeLabel} · {entries.length} {t("audit.events")} · {t("audit.subtitle")}
        </p>
      </div>

      {/* Category chips */}
      <div className="flex gap-2 mb-4 flex-wrap items-center">
        {(["ALL", "TRANSFER", "INVENTORY", "ADJUSTMENT"] as const).map((cat) => {
          const count = cat === "ALL" ? entries.length : counts[cat];
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
      <div className="flex gap-2.5 mb-4 flex-wrap items-center">
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
          {filtered.length} / {entries.length}
        </span>
      </div>

      {/* Scope note */}
      <div className="bg-blue-50 border border-blue-200 rounded-md px-3.5 py-2 mb-4 text-xs text-blue-800">
        <strong>{t("audit.scoped_view")}:</strong> {scopeLabel}
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="bg-gray-50 border-b-2 border-gray-200">
                {[
                  "audit.timestamp", "audit.user", "audit.role", "audit.category",
                  "audit.action", "audit.resource", "audit.decision",
                ].map((key) => (
                  <th key={key} className="px-3 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    {t(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, idx) => {
                const category = getCategory(e.action);
                const cs = CATEGORY_CLASS[category] ?? CATEGORY_CLASS.SYSTEM!;
                const actedOnBehalfOf = getActedOnBehalfOf(e.abac_context);
                const decisionCls = DECISION_CLASS[e.decision] ?? "bg-gray-100 text-gray-700";
                return (
                  <tr key={e.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                    <td className="px-3 py-2 text-gray-400 whitespace-nowrap font-mono text-[10px]">
                      {new Date(e.timestamp).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 font-semibold text-gray-800 whitespace-nowrap text-[11px]">
                      {e.user_name ?? t("common.unknown")}
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-[10px] font-bold bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">
                        {e.role ?? "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${cs.bg} ${cs.text}`}>
                        {cs.icon} {category}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-700 whitespace-nowrap text-[11px]">
                      {getActionLabel(e.action)}
                      {actedOnBehalfOf && (
                        <div className="text-[10px] text-gray-400 mt-0.5 font-sans whitespace-nowrap">
                          {t("audit.acted_on_behalf").replace("{warehouse}", actedOnBehalfOf)}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-500 text-[10px]">
                      {e.resource_type ?? "—"}
                      {e.resource_id && (
                        <span className="text-gray-300"> #{e.resource_id.slice(0, 8)}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${decisionCls}`}>
                        {t(`audit.${e.decision}`)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filtered.length === 0 && (
          <div className="p-12 text-center">
            {entries.length === 0 ? (
              <div>
                <p className="text-gray-400 text-sm m-0 mb-2">
                  {isLoading ? t("common.loading") : t("audit.no_activity")}
                </p>
                {!isLoading && <p className="text-gray-300 text-xs m-0">{t("audit.no_activity_hint")}</p>}
              </div>
            ) : (
              <p className="text-gray-400 text-sm">{t("audit.no_match")}</p>
            )}
          </div>
        )}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-3">
        <p className="text-xs text-gray-400 m-0">{t("audit.footer_note")}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="text-xs px-3 py-1.5 border border-gray-300 rounded-md bg-white disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            {t("common.previous")}
          </button>
          <span className="text-xs text-gray-500">{t("audit.page_label").replace("{n}", String(page + 1))}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={entries.length < PAGE_SIZE}
            className="text-xs px-3 py-1.5 border border-gray-300 rounded-md bg-white disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            {t("common.next")}
          </button>
        </div>
      </div>
    </div>
  );
}
