"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";

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

const GRANT_STYLE: Record<GrantType, { bg: string; color: string; short: string }> = {
  FULL:        { bg: "#DCFCE7", color: "#166534", short: "F" },
  CONDITIONAL: { bg: "#FEF3C7", color: "#92400E", short: "C" },
  READ_ONLY:   { bg: "#DBEAFE", color: "#1E40AF", short: "R" },
  "—":         { bg: "transparent", color: "#E5E7EB", short: "—" },
};

const DOMAINS = Array.from(new Set(PERMISSIONS.map((p) => p.domain)));

export default function PermissionsPage() {
  const { org }    = useParams() as { org: string };
  const user       = getSession();
  const [domain, setDomain] = useState("ALL");

  if (!user || (user.role !== "SA" && user.role !== "AU")) {
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Access restricted to System Admin and Auditor roles.</p>;
  }

  const filtered = domain === "ALL" ? PERMISSIONS : PERMISSIONS.filter((p) => p.domain === domain);

  return (
    <div style={{ padding: "2rem" }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Permissions</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
          Role–permission matrix · 116 actions · 10 roles · 3-layer enforcement (Gateway → Service → RLS)
        </p>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1rem", flexWrap: "wrap" }}>
        {(["FULL", "CONDITIONAL", "READ_ONLY"] as const).map((g) => {
          const s = GRANT_STYLE[g];
          return (
            <span key={g} style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 99, background: s.bg, color: s.color }}>
              {s.short} = {g}
            </span>
          );
        })}
        <span style={{ fontSize: 11, color: "#9CA3AF", marginLeft: 8 }}>— = No access</span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "#9CA3AF" }}>Showing {filtered.length} of 116 actions</span>
      </div>

      {/* Domain filter */}
      <div style={{ display: "flex", gap: 6, marginBottom: "1.25rem", flexWrap: "wrap" }}>
        {["ALL", ...DOMAINS].map((d) => (
          <button key={d} onClick={() => setDomain(d)} style={{
            fontSize: 12, fontWeight: 700, padding: "4px 12px", borderRadius: 20, cursor: "pointer",
            border: domain === d ? "2px solid #0f2d1f" : "2px solid #E5E7EB",
            background: domain === d ? "#0f2d1f" : "#fff",
            color: domain === d ? "#FCDD09" : "#374151",
          }}>{d}</button>
        ))}
      </div>

      {/* Matrix table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "auto" }}>
        <div style={{ height: 3, background: "#FCDD09" }} />
        <table style={{ borderCollapse: "collapse", fontSize: 12, minWidth: "100%" }}>
          <thead>
            <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
              <th style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", position: "sticky", left: 0, background: "#F9FAFB", zIndex: 1 }}>Action</th>
              <th style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase" }}>Domain</th>
              <th style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase" }}>ABAC</th>
              {ROLES.map((r) => (
                <th key={r} style={{ padding: "10px 8px", textAlign: "center", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", whiteSpace: "nowrap" }}>{r}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, idx) => (
              <tr key={p.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                <td style={{ padding: "8px 14px", fontFamily: "monospace", color: "#374151", whiteSpace: "nowrap", position: "sticky", left: 0, background: idx % 2 === 0 ? "#fff" : "#FAFAFA", zIndex: 1 }}>
                  {p.id}
                </td>
                <td style={{ padding: "8px 14px" }}>
                  <span style={{ fontSize: 11, fontWeight: 700, background: "#F3F4F6", color: "#374151", padding: "2px 6px", borderRadius: 3 }}>
                    {p.domain}
                  </span>
                </td>
                <td style={{ padding: "8px 14px", color: "#9CA3AF", fontSize: 11 }}>
                  {p.abac.join(", ")}
                </td>
                {ROLES.map((r) => {
                  const g = (MATRIX[p.id]?.[r] ?? "—") as GrantType;
                  const s = GRANT_STYLE[g];
                  return (
                    <td key={r} style={{ padding: "8px 6px", textAlign: "center" }}>
                      <span style={{ fontSize: 11, fontWeight: 800, padding: "2px 6px", borderRadius: 3, background: s.bg, color: s.color }}>
                        {s.short}
                      </span>
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
