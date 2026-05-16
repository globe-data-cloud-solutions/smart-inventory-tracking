"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoWarehouse } from "@/lib/demo-data";
import { useAuditStore, type AuditLogEntry } from "@/lib/audit-log-state";

const DARK = "#0f2d1f";

const CATEGORY_STYLE: Record<string, { bg: string; color: string; icon: string }> = {
  TRANSFER:   { bg: "#DBEAFE", color: "#1E40AF", icon: "🔄" },
  INVENTORY:  { bg: "#DCFCE7", color: "#166534", icon: "📦" },
  ADJUSTMENT: { bg: "#FEF3C7", color: "#92400E", icon: "✏️" },
  SYSTEM:     { bg: "#F3F4F6", color: "#374151", icon: "⚙️" },
};

const SEL: React.CSSProperties = {
  padding: "6px 10px", fontSize: 12, border: "1px solid #D1D5DB",
  borderRadius: 6, background: "#fff", outline: "none", cursor: "pointer",
};

/* ─────────────────────────────────────────────────────────────────────────────
   Hierarchy scope helpers
   ─────────────────────────────────────────────────────────────────────────── */

/**
 * Returns the SET of warehouse NAMES the user is allowed to see in the audit log.
 * null = unrestricted (TA, SA, or NM at MWH — sees everything in the tenant).
 *
 * View rules:
 *   MWH (NM)     → all warehouses in org  (null)
 *   RWH (RM/NM)  → own WH + all descendants via parentId
 *   WH / SUB_WH  → own WH only
 *   TA / SA      → all  (null)
 */
function buildScopeNames(
  warehouseId: string | undefined,
  role: string,
  warehouses: DemoWarehouse[],
): Set<string> | null {
  if (!warehouseId || ["TA", "SA"].includes(role)) return null;

  const userWH = warehouses.find((w) => w.id === warehouseId);
  if (!userWH) return null;

  // MWH users see everything regardless of role
  if (userWH.type === "MWH") return null;

  // Build set of IDs: own + all descendants via parentId chain
  const scopeIds = new Set<string>([warehouseId]);
  function addDescendants(parentId: string) {
    for (const wh of warehouses) {
      if (wh.parentId === parentId && !scopeIds.has(wh.id)) {
        scopeIds.add(wh.id);
        addDescendants(wh.id);
      }
    }
  }
  addDescendants(warehouseId);

  // Translate to names so we can match against entry.fromWarehouse / toWarehouse
  return new Set(warehouses.filter((w) => scopeIds.has(w.id)).map((w) => w.name));
}

function entryInScope(entry: AuditLogEntry, scopeNames: Set<string> | null): boolean {
  if (!scopeNames) return true;
  return (
    (!!entry.fromWarehouse && scopeNames.has(entry.fromWarehouse)) ||
    (!!entry.toWarehouse   && scopeNames.has(entry.toWarehouse))
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Page
   ─────────────────────────────────────────────────────────────────────────── */

export default function AuditLogPage() {
  const { org } = useParams() as { org: string };
  const user    = getSession();

  const allEntries = useAuditStore((s) => s.entries);

  const [categoryFilter, setCategoryFilter] =
    useState<"ALL" | "TRANSFER" | "INVENTORY" | "ADJUSTMENT">("ALL");
  const [search, setSearch]   = useState("");

  if (!user) return null;
  if (org === SA_ORG_SLUG)
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Select a tenant to view the audit log.</p>;

  const tenant = DEMO_TENANTS.find((t) => t.slug === org);
  if (!tenant)
    return <p style={{ padding: "2rem", color: "#6B7280" }}>Tenant not found.</p>;

  // ── 1. Scope by hierarchy ────────────────────────────────────────────────
  const scopeNames = buildScopeNames(user.warehouseId, user.role, tenant.warehouses);

  const scopedEntries = useMemo(
    () =>
      allEntries
        .filter((e) => e.tenantSlug === org && entryInScope(e, scopeNames))
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allEntries, org, user.warehouseId, user.role],
  );

  // ── 2. Source options (unique non-null fromWarehouse values in scope) ────
  const sourceOptions = useMemo(() => {
    const names = new Set<string>();
    for (const e of scopedEntries) {
      if (e.fromWarehouse) names.add(e.fromWarehouse);
    }
    return Array.from(names).sort();
  }, [scopedEntries]);

  // Default source: most recent entry's fromWarehouse (first scoped entry)
  const defaultSource = scopedEntries.find((e) => e.fromWarehouse)?.fromWarehouse ?? "";
  const [sourceFilter, setSourceFilter] = useState(defaultSource);

  // ── 3. Source-filtered entries ───────────────────────────────────────────
  const sourceFiltered = useMemo(
    () =>
      sourceFilter
        ? scopedEntries.filter((e) => e.fromWarehouse === sourceFilter)
        : scopedEntries,
    [scopedEntries, sourceFilter],
  );

  // ── 4. Destination options — cascade from source selection ───────────────
  const destinationOptions = useMemo(() => {
    const names = new Set<string>();
    for (const e of sourceFiltered) {
      if (e.toWarehouse) names.add(e.toWarehouse);
    }
    return Array.from(names).sort();
  }, [sourceFiltered]);

  const [destinationFilter, setDestinationFilter] = useState("");

  // Reset destination when source changes so stale selection is cleared
  function handleSourceChange(v: string) {
    setSourceFilter(v);
    setDestinationFilter("");
  }

  // ── 5. Final filter: category + destination + search ────────────────────
  const filtered = useMemo(() => {
    let rows = sourceFiltered;
    if (destinationFilter) rows = rows.filter((e) => e.toWarehouse === destinationFilter);
    if (categoryFilter !== "ALL") rows = rows.filter((e) => e.category === categoryFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (e) =>
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

  // Human-readable scope label for subtitle
  const userWH       = tenant.warehouses.find((w) => w.id === user.warehouseId);
  const scopeLabel   = !scopeNames
    ? "All facilities"
    : userWH
      ? `${userWH.name} and facilities under it`
      : "Your facilities";

  return (
    <div style={{ padding: "2rem" }}>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: DARK, margin: 0 }}>Audit Log</h2>
        <p style={{ fontSize: 13, color: "#6B7280", margin: "4px 0 0" }}>
          {tenant.name} · {scopeLabel} · {scopedEntries.length} events · append-only
        </p>
      </div>

      {/* ── Category chips ──────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 8, marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        {(["ALL", "TRANSFER", "INVENTORY", "ADJUSTMENT"] as const).map((cat) => {
          const count = cat === "ALL" ? scopedEntries.length : counts[cat];
          const s     = (cat !== "ALL" ? CATEGORY_STYLE[cat] : null) ?? { bg: "#F3F4F6", color: "#374151", icon: "" };
          return (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              style={{
                fontSize: 12, fontWeight: 700, padding: "4px 12px", borderRadius: 20, cursor: "pointer",
                border: categoryFilter === cat ? "2px solid #0f2d1f" : "2px solid transparent",
                background: categoryFilter === cat ? s.bg : "#F9FAFB",
                color:      categoryFilter === cat ? s.color : "#6B7280",
              }}
            >
              {s.icon ? `${s.icon} ` : ""}{cat} ({count})
            </button>
          );
        })}
      </div>

      {/* ── Source / Destination filters + search ──────────────────────── */}
      <div style={{ display: "flex", gap: 10, marginBottom: "1.25rem", flexWrap: "wrap", alignItems: "center" }}>

        {/* Source */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <label style={{ fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
            Source
          </label>
          <select value={sourceFilter} onChange={(e) => handleSourceChange(e.target.value)} style={SEL}>
            <option value="">All sources</option>
            {sourceOptions.map((wh) => (
              <option key={wh} value={wh}>{wh}</option>
            ))}
          </select>
        </div>

        {/* Destination — cascaded */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <label style={{ fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
            Destination
          </label>
          <select
            value={destinationFilter}
            onChange={(e) => setDestinationFilter(e.target.value)}
            style={SEL}
            disabled={destinationOptions.length === 0}
          >
            <option value="">All destinations</option>
            {destinationOptions.map((wh) => (
              <option key={wh} value={wh}>{wh}</option>
            ))}
          </select>
          {sourceFilter && destinationOptions.length > 0 && (
            <span style={{ fontSize: 11, color: "#9CA3AF" }}>
              ({destinationOptions.length} available)
            </span>
          )}
        </div>

        {/* Clear filters link */}
        {(sourceFilter || destinationFilter) && (
          <button
            onClick={() => { setSourceFilter(""); setDestinationFilter(""); }}
            style={{ fontSize: 11, color: "#6B7280", background: "none", border: "none", cursor: "pointer", textDecoration: "underline", padding: 0 }}
          >
            Clear filters
          </button>
        )}

        {/* Search */}
        <div style={{ position: "relative", flex: 1, minWidth: 200 }}>
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#9CA3AF", fontSize: 13 }}>🔍</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search action, product, user…"
            style={{ width: "100%", padding: "6px 10px 6px 30px", fontSize: 13, border: "1px solid #D1D5DB", borderRadius: 6, outline: "none", boxSizing: "border-box" as const }}
          />
        </div>

        <span style={{ fontSize: 12, color: "#9CA3AF", whiteSpace: "nowrap" }}>
          {filtered.length} of {scopedEntries.length}
        </span>
      </div>

      {/* ── Scope note ──────────────────────────────────────────────────── */}
      {scopeNames && (
        <div style={{ background: "#EFF6FF", border: "1px solid #BFDBFE", borderRadius: 6, padding: "8px 14px", marginBottom: "1rem", fontSize: 12, color: "#1E40AF" }}>
          <strong>Scoped view:</strong> showing only transfers and transactions involving{" "}
          <strong>{Array.from(scopeNames).join(", ")}</strong>.{" "}
          {userWH?.type === "RWH" && "Includes all warehouses under your regional hierarchy."}
        </div>
      )}

      {/* ── Table ───────────────────────────────────────────────────────── */}
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: 3, background: tenant.color }} />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ background: "#F9FAFB", borderBottom: "2px solid #E5E7EB" }}>
                {["Timestamp", "User", "Role", "Category", "Action", "Ref", "Product", "Qty / Unit", "From", "To", "Notes"].map((h) => (
                  <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, idx) => {
                const cs = CATEGORY_STYLE[e.category] ?? { bg: "#F3F4F6", color: "#374151", icon: "⚙️" };
                return (
                  <tr key={e.id} style={{ background: idx % 2 === 0 ? "#fff" : "#FAFAFA", borderBottom: "1px solid #F3F4F6" }}>
                    <td style={{ padding: "8px 12px", color: "#9CA3AF", whiteSpace: "nowrap", fontFamily: "monospace", fontSize: 10 }}>
                      {new Date(e.timestamp).toLocaleString()}
                    </td>
                    <td style={{ padding: "8px 12px", fontWeight: 600, color: "#1F2937", whiteSpace: "nowrap", fontSize: 11 }}>{e.userName}</td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, background: "#F3F4F6", color: "#374151", padding: "2px 6px", borderRadius: 3 }}>
                        {e.role}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 3, background: cs.bg, color: cs.color, whiteSpace: "nowrap" }}>
                        {cs.icon} {e.category}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace", color: "#374151", whiteSpace: "nowrap", fontSize: 11 }}>
                      {e.action}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace", color: "#6B7280", fontSize: 10 }}>
                      {e.resourceRef || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#1F2937", fontSize: 11, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {e.productName || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", fontWeight: 600, color: "#374151", whiteSpace: "nowrap", fontSize: 11 }}>
                      {e.quantityStr || "—"}
                    </td>
                    <td style={{ padding: "8px 12px", fontSize: 11, whiteSpace: "nowrap" }}>
                      {e.fromWarehouse
                        ? <span style={{ color: "#374151" }}>{e.fromWarehouse}</span>
                        : <span style={{ color: "#D1D5DB" }}>—</span>}
                    </td>
                    <td style={{ padding: "8px 12px", fontSize: 11, whiteSpace: "nowrap" }}>
                      {e.toWarehouse
                        ? <span style={{ color: "#374151" }}>{e.toWarehouse}</span>
                        : <span style={{ color: "#D1D5DB" }}>—</span>}
                    </td>
                    <td style={{ padding: "8px 12px", color: "#9CA3AF", fontSize: 11, maxWidth: 200 }}>
                      {e.notes || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {filtered.length === 0 && (
          <div style={{ padding: "3rem", textAlign: "center" }}>
            {scopedEntries.length === 0 ? (
              <div>
                <p style={{ color: "#9CA3AF", fontSize: 14, margin: "0 0 0.5rem" }}>No activity logged yet.</p>
                <p style={{ color: "#D1D5DB", fontSize: 12, margin: 0 }}>
                  Create transfers, receive stock, or issue stock to generate audit entries.
                </p>
              </div>
            ) : (
              <p style={{ color: "#9CA3AF", fontSize: 13 }}>No entries match the current filters.</p>
            )}
          </div>
        )}
      </div>

      <p style={{ marginTop: "0.75rem", fontSize: 12, color: "#9CA3AF" }}>
        Persisted to localStorage · Append-only · Completed transfers archived here permanently
      </p>
    </div>
  );
}
