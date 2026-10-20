"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { t } from "@/lib/i18n";

const DARK = "#0f2d1f";

type GrantType = "FULL" | "CONDITIONAL" | "READ_ONLY" | "—";

interface Permission {
  id: string;
  domain: string;
  abac: string[];
}

// Subset of the 116 permissions from registry.py — key ones shown for SA review
const PERMISSIONS: Permission[] = [
  // Tenant & System
  { id: "tenant:create",           domain: "Tenant",    abac: ["platform_only"] },
  { id: "tenant:configure",        domain: "Tenant",    abac: ["tenant_id"] },
  { id: "tenant:set_org_type",     domain: "Tenant",    abac: ["tenant_id", "audit_required"] },
  // User Management
  { id: "user:invite",             domain: "User",      abac: ["tenant_id", "role_ceiling"] },
  { id: "user:deactivate",         domain: "User",      abac: ["tenant_id"] },
  // Product
  { id: "product:create",          domain: "Product",   abac: ["tenant_id", "sku_cap"] },
  { id: "product:update",          domain: "Product",   abac: ["tenant_id"] },
  { id: "product:delete",          domain: "Product",   abac: ["tenant_id"] },
  // Inventory
  { id: "inventory:receive",       domain: "Inventory", abac: ["tenant_id", "warehouse_id"] },
  { id: "inventory:adjust",        domain: "Inventory", abac: ["tenant_id", "warehouse_id", "approval_threshold"] },
  { id: "inventory:transfer",      domain: "Inventory", abac: ["tenant_id", "scope"] },
  { id: "inventory:cycle_count",   domain: "Inventory", abac: ["tenant_id", "warehouse_id"] },
  { id: "inventory:view",          domain: "Inventory", abac: ["tenant_id"] },
  // Dispatch
  { id: "dispatch:configure",      domain: "Dispatch",  abac: ["tenant_id"] },
  { id: "dispatch:fefo_override",  domain: "Dispatch",  abac: ["tenant_id", "override_permission", "reason_required"] },
  // Orders
  { id: "order:create",            domain: "Order",     abac: ["tenant_id"] },
  { id: "order:approve",           domain: "Order",     abac: ["tenant_id", "approval_threshold"] },
  // Reports
  { id: "report:view",             domain: "Report",    abac: ["tenant_id"] },
  { id: "report:export",           domain: "Report",    abac: ["tenant_id"] },
  // AI
  { id: "ai:forecast_view",        domain: "AI",        abac: ["tenant_id"] },
  { id: "ai:model_run",            domain: "AI",        abac: ["system_only"] },
  // Audit
  { id: "audit:view",              domain: "Audit",     abac: ["tenant_id"] },
];

// Role-permission matrix — FULL=F, CONDITIONAL=C, READ_ONLY=R, denied=—
const MATRIX: Record<string, Partial<Record<string, GrantType>>> = {
  "tenant:create":          { SA: "FULL" },
  "tenant:configure":       { SA: "FULL", TA: "FULL" },
  "tenant:set_org_type":    { SA: "FULL", TA: "CONDITIONAL" },
  "user:invite":            { SA: "FULL", TA: "FULL", NM: "CONDITIONAL" },
  "user:deactivate":        { SA: "FULL", TA: "FULL" },
  "product:create":         { SA: "FULL", TA: "FULL", NM: "FULL", RM: "CONDITIONAL" },
  "product:update":         { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", WM: "CONDITIONAL" },
  "product:delete":         { SA: "FULL", TA: "FULL", NM: "CONDITIONAL" },
  "inventory:receive":      { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", WM: "FULL" },
  "inventory:adjust":       { SA: "FULL", TA: "FULL", NM: "FULL", RM: "CONDITIONAL", WM: "CONDITIONAL" },
  "inventory:transfer":     { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", WM: "FULL", LM: "FULL" },
  "inventory:cycle_count":  { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", WM: "FULL" },
  "inventory:view":         { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", WM: "FULL", LM: "READ_ONLY", SA_GT: "READ_ONLY", RT: "READ_ONLY", AU: "READ_ONLY" },
  "dispatch:configure":     { SA: "FULL", TA: "FULL", NM: "FULL" },
  "dispatch:fefo_override": { SA: "FULL", TA: "FULL", NM: "FULL", RM: "CONDITIONAL" },
  "order:create":           { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", SA_GT: "FULL", RT: "FULL" },
  "order:approve":          { SA: "FULL", TA: "FULL", NM: "FULL", RM: "CONDITIONAL" },
  "report:view":            { SA: "FULL", TA: "FULL", NM: "FULL", RM: "FULL", AU: "READ_ONLY" },
  "report:export":          { SA: "FULL", TA: "FULL", NM: "FULL" },
  "ai:forecast_view":       { SA: "FULL", TA: "FULL", NM: "FULL", RM: "READ_ONLY" },
  "ai:model_run":           { SYS: "FULL" },
  "audit:view":             { SA: "FULL", TA: "FULL", NM: "READ_ONLY", AU: "READ_ONLY" },
};

const ROLES = ["SA", "TA", "NM", "RM", "WM", "LM", "SA_GT", "RT", "AU", "SYS"];

const GRANT_CLASS: Record<GrantType, { cls: string; short: string }> = {
  FULL:        { cls: "bg-green-100 text-green-800",  short: "F" },
  CONDITIONAL: { cls: "bg-amber-100 text-amber-800",  short: "C" },
  READ_ONLY:   { cls: "bg-blue-100  text-blue-800",   short: "R" },
  "—":         { cls: "bg-transparent text-gray-200", short: "—" },
};

const DOMAINS = Array.from(new Set(PERMISSIONS.map((p) => p.domain)));

export default function PermissionsPage() {
  const { org }  = useParams() as { org: string };
  const user     = getSession();
  const [domain, setDomain] = useState("ALL");

  if (!user || (user.role !== "SA" && user.role !== "AU")) {
    return <p className="p-8 text-gray-500">{t("permissions.restricted")}</p>;
  }

  const filtered = domain === "ALL" ? PERMISSIONS : PERMISSIONS.filter((p) => p.domain === domain);

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("permissions.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{t("permissions.subtitle")}</p>
      </div>

      {/* Legend */}
      <div className="flex gap-2.5 mb-4 flex-wrap">
        {(["FULL", "CONDITIONAL", "READ_ONLY"] as const).map((g) => {
          const s = GRANT_CLASS[g];
          return (
            <span key={g} className={`text-xs font-bold px-2.5 py-0.5 rounded-full ${s.cls}`}>
              {s.short} = {g}
            </span>
          );
        })}
        <span className="text-xs text-gray-400 ml-2">{t("permissions.no_access")}</span>
        <span className="ml-auto text-xs text-gray-400">
          {t("permissions.showing")} {filtered.length} / 116
        </span>
      </div>

      {/* Domain filter */}
      <div className="flex gap-1.5 mb-5 flex-wrap">
        {["ALL", ...DOMAINS].map((d) => (
          <button key={d} onClick={() => setDomain(d)}
            className={`text-xs font-bold px-3 py-1 rounded-full cursor-pointer border-2 transition-all ${
              domain === d
                ? "bg-[#0f2d1f] text-eth-gold border-[#0f2d1f]"
                : "bg-white text-gray-700 border-gray-200 hover:border-gray-400"
            }`}
          >
            {d}
          </button>
        ))}
      </div>

      {/* Matrix table */}
      <div className="bg-white border border-gray-200 rounded overflow-auto">
        <div className="h-[3px] bg-eth-gold" />
        <table className="border-collapse text-xs min-w-full">
          <thead>
            <tr className="bg-gray-50 border-b-2 border-gray-200">
              <th className="px-3.5 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase sticky left-0 bg-gray-50 z-10">
                {t("permissions.action")}
              </th>
              <th className="px-3.5 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase">{t("permissions.domain")}</th>
              <th className="px-3.5 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase">{t("permissions.abac_column")}</th>
              {ROLES.map((r) => (
                <th key={r} className="px-2 py-2.5 text-center text-[11px] font-bold text-gray-500 uppercase whitespace-nowrap">{r}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, idx) => (
              <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                <td className={`px-3.5 py-2 font-mono text-gray-700 whitespace-nowrap sticky left-0 z-10 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  {p.id}
                </td>
                <td className="px-3.5 py-2">
                  <span className="text-[11px] font-bold bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">{p.domain}</span>
                </td>
                <td className="px-3.5 py-2 text-gray-400 text-[11px]">{p.abac.join(", ")}</td>
                {ROLES.map((r) => {
                  const g = (MATRIX[p.id]?.[r] ?? "—") as GrantType;
                  const s = GRANT_CLASS[g];
                  return (
                    <td key={r} className="px-1.5 py-2 text-center">
                      <span className={`text-[11px] font-extrabold px-1.5 py-0.5 rounded ${s.cls}`}>{s.short}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
