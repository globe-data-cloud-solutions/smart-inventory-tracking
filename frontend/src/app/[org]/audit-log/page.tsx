"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS } from "@/lib/demo-data";

const DARK = "#0f2d1f";

type Decision = "GRANTED" | "DENIED" | "CONDITIONAL";

interface AuditEntry {
  id: string;
  timestamp: string;
  user_name: string;
  role: string;
  action: string;
  resource_type: string;
  decision: Decision;
  reason: string;
}

const DECISION_STYLE: Record<Decision, { bg: string; color: string }> = {
  GRANTED:     { bg: "#DCFCE7", color: "#166534" },
  DENIED:      { bg: "#FEE2E2", color: "#991B1B" },
  CONDITIONAL: { bg: "#FEF3C7", color: "#92400E" },
};

function makeEntries(tenantName: string, users: Array<{ name: string; role: string }>): AuditEntry[] {
  const now   = Date.now();
  const entry = (
    offsetMs: number, user: { name: string; role: string }, action: string,
    resource: string, decision: Decision, reason: string
  ): AuditEntry => ({
    id:            crypto.randomUUID(),
    timestamp:     new Date(now - offsetMs).toISOString(),
    user_name:     user.name,
    role:          user.role,
    action,
    resource_type: resource,
    decision,
    reason,
  });

  const fallback = { name: "User", role: "TA" };
  const ta = users[0] ?? fallback;
  const nm = users[1] ?? fallback;
  const rm = users[2] ?? fallback;
  const wm = users[3] ?? fallback;

  return [
    entry(60_000,       wm,  "inventory:receive",        "InventoryTransaction", "GRANTED",     ""),
    entry(120_000,      wm,  "inventory:adjust",         "InventoryTransaction", "CONDITIONAL", "APPROVAL_REQUIRED"),
    entry(180_000,      rm,  "inventory:adjust:approve", "AdjustmentOrder",      "GRANTED",     ""),
    entry(300_000,      wm,  "inventory:transfer",       "TransferOrder",        "GRANTED",     ""),
    entry(600_000,      ta,  "product:create",           "Product",              "GRANTED",     ""),
    entry(900_000,      nm,  "report:view",              "Report",               "GRANTED",     ""),
    entry(1_200_000,    wm,  "dispatch:fefo_override",   "DispatchConfig",       "DENIED",      "RBAC_DENIED"),
    entry(1_800_000,    rm,  "tenant:configure",         "Tenant",               "DENIED",      "ABAC_DENIED: tenant mismatch"),
    entry(3_600_000,    ta,  "user:invite",              "User",                 "GRANTED",     ""),
    entry(7_200_000,    wm,  "inventory:cycle_count",    "StockCountSession",    "GRANTED",     ""),
    entry(14_400_000,   nm,  "ai:forecast_view",         "AIForecast",           "DENIED",      "RBAC_DENIED"),
    entry(86_400_000,   ta,  "tenant:set_org_type",      "Tenant",               "GRANTED",     ""),
  ];
}

export default function AuditLogPage() {
  const { org }     = useParams() as { org: string };
  const user        = getSession();
  const [filter, setFilter] = useState<"ALL" | Decision>("ALL");

  if (!user) return null;

  const isSA    = user.role === "SA";
  const tenant  = org === SA_ORG_SLUG ? null : DEMO_TENANTS.find((t) => t.slug === org);

  const tenantName = tenant?.name ?? "Platform";
  const users      = tenant?.users ?? [];

  const allEntries = makeEntries(tenantName, users);
  const entries    = filter === "ALL" ? allEntries : allEntries.filter((e) => e.decision === filter);

  const counts = {
    GRANTED:     allEntries.filter((e) => e.decision === "GRANTED").length,
    DENIED:      allEntries.filter((e) => e.decision === "DENIED").length,
    CONDITIONAL: allEntries.filter((e) => e.decision === "CONDITIONAL").length,
  };

  return (
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Audit Log</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
          {tenantName} · Append-only record of all permission decisions
        </p>
      </div>

      {/* Summary chips + filter */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "1.5rem", flexWrap: "wrap" }}>
        {(["ALL", "GRANTED", "DENIED", "CONDITIONAL"] as const).map((d) => {
          const count = d === "ALL" ? allEntries.length : counts[d];
          const s = d === "ALL"
            ? { bg: "#F3F4F6", color: "#374151" }
            : DECISION_STYLE[d];
          return (
            <button
              key={d}
              onClick={() => setFilter(d)}
              style={{
                fontSize: 12, fontWeight: 700, padding: "4px 12px", borderRadius: 20,
                border: filter === d ? "2px solid #0f2d1f" : "2px solid transparent",
                background: filter === d ? s.bg : "#F9FAFB",
                color: filter === d ? s.color : "#6B7280", cursor: "pointer",
              }}
            >
              {d} {count > 0 && `(${count})`}
            </button>
          );
        })}
        <span style={{ marginLeft: "auto", fontSize: 12, color: "#9CA3AF" }}>
          No UPDATE or DELETE — append-only enforced by PostgreSQL RULE
        </span>
      </div>

      {/* Table */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant?.color ?? "#FCDD09" }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                {["Timestamp", "User", "Role", "Action", "Resource", "Decision", "Reason"].map((h) => (
                  <th key={h} style={{
                    padding: "10px 14px", textAlign: "left",
                    fontSize: 11, fontWeight: 700, color: "#6B7280",
                    textTransform: "uppercase", letterSpacing: "0.05em",
                    whiteSpace: "nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((e, idx) => {
                const s = DECISION_STYLE[e.decision];
                return (
                  <tr key={e.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "9px 14px", color: "#9CA3AF", whiteSpace: "nowrap", fontFamily: "monospace", fontSize: 11 }}>
                      {new Date(e.timestamp).toLocaleString()}
                    </td>
                    <td style={{ padding: "9px 14px", fontWeight: 600, color: "#1F2937", whiteSpace: "nowrap" }}>{e.user_name || "—"}</td>
                    <td style={{ padding: "9px 14px" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, background: "#F3F4F6", color: "#374151", padding: "2px 6px", borderRadius: 3 }}>
                        {e.role}
                      </span>
                    </td>
                    <td style={{ padding: "9px 14px", fontFamily: "monospace", color: "#374151", whiteSpace: "nowrap" }}>{e.action}</td>
                    <td style={{ padding: "9px 14px", color: "#6B7280" }}>{e.resource_type}</td>
                    <td style={{ padding: "9px 14px" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 3, background: s.bg, color: s.color, whiteSpace: "nowrap" }}>
                        {e.decision}
                      </span>
                    </td>
                    <td style={{ padding: "9px 14px", color: "#9CA3AF", fontSize: 11 }}>{e.reason || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {entries.length === 0 && (
          <p style={{ padding: "2rem", textAlign: "center", color: "#9CA3AF", fontSize: 13 }}>
            No audit entries match the selected filter.
          </p>
        )}
      </div>

      {!isSA && (
        <p style={{ marginTop: "1rem", fontSize: 12, color: "#9CA3AF" }}>
          Showing last 24h demo entries. Production records are immutable — PostgreSQL RULE prevents UPDATE/DELETE on audit_logs.
        </p>
      )}
    </div>
  );
}
