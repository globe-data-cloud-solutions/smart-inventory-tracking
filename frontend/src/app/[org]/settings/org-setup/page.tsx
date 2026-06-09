"use client";

import { useState, useCallback, useMemo, Fragment } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

/* ── Types ─────────────────────────────────────────────────────────────────── */

interface HierarchyLevel {
  level_number: number;
  level_name: string;
  default_role_code: string;
  role_display_label: string;
  is_stock_holding: boolean;
}

interface OrgNode {
  id: string;
  name: string;
  code: string;
  address?: string | null;
  hierarchy_level: number;
  parent_node_id: string | null;
  is_stock_holding: boolean;
  is_active: boolean;
  children: OrgNode[];
}

/* ── Constants ─────────────────────────────────────────────────────────────── */

// Allowed roles in hierarchy config — never SA or TA (§28, FIX 4)
const ROLE_OPTIONS = [
  { code: "NM", label: "National Manager" },
  { code: "RM", label: "Regional Manager" },
  { code: "LM", label: "Logistics Manager" },
  { code: "WM", label: "Warehouse Manager" },
  { code: "AU", label: "Auditor" },
] as const;

// Auto-suggest role by level position (FIX 4)
function suggestRole(levelNumber: number): string {
  if (levelNumber === 1) return "NM";
  if (levelNumber <= 3) return "RM";
  return "WM";
}

// Default display label for a role code
function defaultDisplayLabel(code: string): string {
  return ROLE_OPTIONS.find((r) => r.code === code)?.label ?? code;
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */

function flattenNodes(nodes: OrgNode[]): OrgNode[] {
  const out: OrgNode[] = [];
  function visit(list: OrgNode[]) {
    for (const n of list) { out.push(n); visit(n.children); }
  }
  visit(nodes);
  return out;
}

/* ── Tab 1: Organisation Levels ───────────────────────────────────────────── */

function LevelsTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();

  const { data: savedLevels = [], isLoading } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn: () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });

  // Local editable copy — initialised with defaults so inputs are editable on first render
  // (before server data arrives). Synced to server data once on first successful load.
  const [levels, setLevels] = useState<HierarchyLevel[]>(() =>
    Array.from({ length: 3 }, (_, i) => {
      const role = suggestRole(i + 1);
      return {
        level_number: i + 1,
        level_name: "",
        default_role_code: role,
        role_display_label: defaultDisplayLabel(role),
        is_stock_holding: i + 1 > 1,
      };
    })
  );
  const [initialised, setInitialised] = useState(false);

  // Sync from server on first load (replaces defaults with saved values)
  if (!initialised && savedLevels.length > 0) {
    setLevels(savedLevels);
    setInitialised(true);
  }

  const [levelCount, setLevelCount] = useState<number>(
    savedLevels.length > 0 ? savedLevels.length : 3
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk]       = useState(false);

  // When level count changes rebuild the levels array
  function handleCountChange(n: number) {
    setLevelCount(n);
    setLevels((prev) =>
      Array.from({ length: n }, (_, i) => {
        const existing = prev.find((l) => l.level_number === i + 1);
        if (existing) return existing;
        const role = suggestRole(i + 1);
        return {
          level_number: i + 1,
          level_name: "",
          default_role_code: role,
          role_display_label: defaultDisplayLabel(role),
          is_stock_holding: i + 1 > 1, // L1 is often admin-only; rest default to stock-holding
        };
      })
    );
  }

  function updateLevel(idx: number, patch: Partial<HierarchyLevel>) {
    setLevels((prev) => prev.map((l, i) => i === idx ? { ...l, ...patch } : l));
    setSaveOk(false);
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put(`/api/v1/tenants/${tenantId}/hierarchy/config`, levels),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hierarchy-config", tenantId] });
      setSaveOk(true);
      setSaveError(null);
    },
    onError: (e: unknown) => {
      setSaveError(e instanceof Error ? e.message : t("common.error"));
      setSaveOk(false);
    },
  });

  if (isLoading) {
    return <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      {/* Level count picker */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t("org_setup.level_count")}
        </label>
        <div className="flex gap-3">
          {[2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => handleCountChange(n)}
              className={`w-14 h-14 rounded-lg border-2 text-lg font-bold transition-all ${
                levelCount === n
                  ? "border-emerald-600 bg-emerald-50 text-emerald-700"
                  : "border-gray-200 bg-white text-gray-600 hover:border-gray-400"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-2">{t("org_setup.level_count_hint")}</p>
      </div>

      {/* Editable levels table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 w-12">No</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Level Name *</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Role *</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Display Label</th>
              <th className="px-3 py-2 text-center text-xs font-semibold text-gray-500 w-24">Holds Stock</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {levels.map((lv, idx) => (
              <tr key={lv.level_number} className="hover:bg-gray-50">
                <td className="px-3 py-2">
                  <span className="w-7 h-7 rounded-full bg-emerald-600 text-white text-xs font-bold flex items-center justify-center">
                    {lv.level_number}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <input
                    type="text"
                    value={lv.level_name}
                    onChange={(e) => updateLevel(idx, { level_name: e.target.value })}
                    placeholder={["Main Factory", "Region", "Warehouse", "Sub-Warehouse", "Counter"][idx] ?? ""}
                    className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </td>
                <td className="px-3 py-2">
                  <select
                    value={lv.default_role_code}
                    onChange={(e) => updateLevel(idx, {
                      default_role_code: e.target.value,
                      role_display_label: lv.role_display_label || defaultDisplayLabel(e.target.value),
                    })}
                    className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r.code} value={r.code}>{r.code} — {r.label}</option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2">
                  <input
                    type="text"
                    value={lv.role_display_label}
                    onChange={(e) => updateLevel(idx, { role_display_label: e.target.value })}
                    placeholder={defaultDisplayLabel(lv.default_role_code)}
                    className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={lv.is_stock_holding}
                    onChange={(e) => updateLevel(idx, { is_stock_holding: e.target.checked })}
                    className="w-4 h-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {saveError && <p className="text-sm text-red-600">{saveError}</p>}
      {saveOk && <p className="text-sm text-emerald-600 font-medium">Levels saved.</p>}

      <button
        type="button"
        onClick={() => saveMutation.mutate()}
        disabled={saveMutation.isPending}
        className="px-5 py-2 bg-emerald-700 text-white text-sm font-semibold rounded-lg hover:bg-emerald-800 disabled:opacity-50"
      >
        {saveMutation.isPending ? t("common.saving") : "Save Levels"}
      </button>
    </div>
  );
}

/* ── Inline node form ──────────────────────────────────────────────────────── */

interface NodeFormState {
  name: string;
  location: string;
  parent_node_id: string;
  primary_source_id: string;
  is_stock_holding: boolean;
  level_number: number;
}

function NodeForm({
  tenantId,
  flat,
  levels,
  editingNode,
  defaultParentId,
  onSaved,
  onCancel,
}: {
  tenantId: string;
  flat: OrgNode[];
  levels: HierarchyLevel[];
  editingNode: OrgNode | null;
  defaultParentId: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const parentNode = flat.find((n) => n.id === defaultParentId) ?? null;
  const childLevel = parentNode ? parentNode.hierarchy_level + 1 : 1;

  const [form, setForm] = useState<NodeFormState>(() => ({
    name:              editingNode?.name ?? "",
    location:          editingNode?.address ?? "",
    parent_node_id:    editingNode?.parent_node_id ?? defaultParentId,
    primary_source_id: "",
    is_stock_holding:  editingNode?.is_stock_holding ?? true,
    level_number:      editingNode?.hierarchy_level ?? childLevel,
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  async function save() {
    if (!form.name.trim()) { setError("Name is required."); return; }
    setSaving(true);
    setError(null);
    try {
      if (editingNode) {
        await api.patch(`/api/v1/tenants/${tenantId}/nodes/${editingNode.id}`, {
          name: form.name.trim(),
          address: form.location.trim() || null,
        });
      } else {
        await api.post(`/api/v1/tenants/${tenantId}/nodes`, {
          name:             form.name.trim(),
          level_number:     form.level_number,
          parent_node_id:   form.parent_node_id || null,
          is_stock_holding: form.is_stock_holding,
          address:          form.location.trim() || null,
        });
      }
      // Wire up primary source as SUPPLY_FROM if selected
      if (!editingNode && form.primary_source_id) {
        const nodeId = await api.get<OrgNode[]>(`/api/v1/tenants/${tenantId}/nodes`)
          .then((tree) => {
            const all = flattenNodes(tree);
            return all.find((n) => n.name === form.name.trim() && !editingNode)?.id;
          });
        if (nodeId) {
          await api.post(`/api/v1/tenants/${tenantId}/nodes/${nodeId}/supply-routes`, {
            primary_source_id: form.primary_source_id,
          }).catch(() => { /* non-fatal — user can set routes later */ });
        }
      }
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  const levelLabel = levels.find((l) => l.level_number === form.level_number)?.level_name
    ?? `Level ${form.level_number}`;

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3 mt-2">
      <p className="text-xs font-semibold text-blue-800">
        {editingNode ? `Edit: ${editingNode.name}` : `New node — ${levelLabel}`}
      </p>

      {/* Name */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Name *</label>
        <input
          type="text"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="e.g. North Addis Warehouse"
          autoFocus
          className="w-full text-sm border border-gray-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Location (optional) */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Location / Address (optional)</label>
        <input
          type="text"
          value={form.location}
          onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
          placeholder="e.g. Kirkos, Addis Ababa"
          className="w-full text-sm border border-gray-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Primary source (optional, not shown when editing) */}
      {!editingNode && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Primary supply source (optional)</label>
          <select
            value={form.primary_source_id}
            onChange={(e) => setForm((f) => ({ ...f, primary_source_id: e.target.value }))}
            className="w-full text-sm border border-gray-300 rounded px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">None</option>
            {flat.filter((n) => n.is_stock_holding).map((n) => (
              <option key={n.id} value={n.id}>
                L{n.hierarchy_level} — {n.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Holds stock */}
      {!editingNode && (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_stock_holding}
            onChange={(e) => setForm((f) => ({ ...f, is_stock_holding: e.target.checked }))}
            className="w-4 h-4 rounded border-gray-300 text-blue-600"
          />
          <span className="text-xs text-gray-700">{t("org_setup.is_stock_holding")}</span>
        </label>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="px-4 py-1.5 bg-blue-600 text-white text-sm font-semibold rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? t("common.saving") : "Save Node"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-1.5 border border-gray-300 text-gray-600 text-sm font-medium rounded hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ── Tab 2: Organisation Tree ─────────────────────────────────────────────── */

function TreeTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();

  const { data: levels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn: () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });

  const { data: nodes = [], isLoading } = useQuery<OrgNode[]>({
    queryKey: ["org-nodes", tenantId],
    queryFn: () => api.get<OrgNode[]>(`/api/v1/tenants/${tenantId}/nodes`),
    staleTime: 0,
  });

  const flat = flattenNodes(nodes);

  // "add child" or "add root" form state — null = no form open
  const [addParentId, setAddParentId] = useState<string | null>(null);
  // "edit node" form state — null = no form open
  const [editNodeId, setEditNodeId]   = useState<string | null>(null);

  const [deleteError, setDeleteError] = useState<string | null>(null);

  const refreshNodes = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["org-nodes", tenantId] });
  }, [qc, tenantId]);

  const deleteMutation = useMutation({
    mutationFn: (nodeId: string) =>
      api.delete(`/api/v1/tenants/${tenantId}/nodes/${nodeId}`),
    onSuccess: refreshNodes,
    onError: (e: unknown) => {
      setDeleteError(e instanceof Error ? e.message : t("common.error"));
    },
  });

  function renderNode(node: OrgNode, depth: number): React.ReactNode {
    const levelLabel = levels.find((l) => l.level_number === node.hierarchy_level)?.level_name
      ?? `Level ${node.hierarchy_level}`;
    const maxLevel = levels.length > 0 ? Math.max(...levels.map((l) => l.level_number)) : 5;
    const canAddChild = node.hierarchy_level < maxLevel;
    const isEditOpen = editNodeId === node.id;
    const isAddOpen  = addParentId === node.id;

    return (
      <div key={node.id}>
        <div
          className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${
            node.is_stock_holding ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-gray-50"
          }`}
          style={{ marginLeft: `${depth * 24}px` }}
        >
          <span className="text-sm shrink-0">{node.is_stock_holding ? "🏭" : "📋"}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 m-0 truncate">{node.name}</p>
            <p className="text-xs text-gray-400 m-0">
              {node.code} · {levelLabel}
            </p>
            {node.address && (
              <p className="text-xs text-gray-400 m-0 truncate">📍 {node.address}</p>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {canAddChild && (
              <button
                type="button"
                title="Add child node"
                onClick={() => { setAddParentId(node.id); setEditNodeId(null); }}
                className="w-6 h-6 flex items-center justify-center text-xs rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-100 bg-white"
              >
                +
              </button>
            )}
            <button
              type="button"
              title="Edit node"
              onClick={() => { setEditNodeId(node.id); setAddParentId(null); }}
              className="w-6 h-6 flex items-center justify-center text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-100 bg-white"
            >
              ✏
            </button>
            <button
              type="button"
              title="Delete node"
              onClick={() => {
                setDeleteError(null);
                if (confirm(`Delete "${node.name}"? This cannot be undone.`)) {
                  deleteMutation.mutate(node.id);
                }
              }}
              className="w-6 h-6 flex items-center justify-center text-xs rounded border border-red-200 text-red-500 hover:bg-red-50 bg-white"
            >
              🗑
            </button>
          </div>
        </div>

        {isEditOpen && (
          <div style={{ marginLeft: `${depth * 24}px` }}>
            <NodeForm
              tenantId={tenantId}
              flat={flat}
              levels={levels}
              editingNode={node}
              defaultParentId={node.parent_node_id ?? ""}
              onSaved={() => { setEditNodeId(null); refreshNodes(); }}
              onCancel={() => setEditNodeId(null)}
            />
          </div>
        )}

        {isAddOpen && (
          <div style={{ marginLeft: `${(depth + 1) * 24}px` }}>
            <NodeForm
              tenantId={tenantId}
              flat={flat}
              levels={levels}
              editingNode={null}
              defaultParentId={node.id}
              onSaved={() => { setAddParentId(null); refreshNodes(); }}
              onCancel={() => setAddParentId(null)}
            />
          </div>
        )}

        {node.children.length > 0 && (
          <div className="mt-1">{node.children.map((c) => renderNode(c, depth + 1))}</div>
        )}
      </div>
    );
  }

  if (isLoading) {
    return <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-4">
      {/* Legend */}
      {levels.length > 0 && (
        <div className="flex flex-wrap gap-3 bg-gray-50 border border-gray-200 rounded-lg p-3">
          {levels.map((lv) => (
            <span key={lv.level_number} className="flex items-center gap-1.5 text-xs text-gray-600">
              <span className="w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold flex items-center justify-center">
                {lv.level_number}
              </span>
              {lv.level_name || `Level ${lv.level_number}`}
              <span className="text-gray-400">({lv.default_role_code})</span>
            </span>
          ))}
        </div>
      )}

      {deleteError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {deleteError}
        </p>
      )}

      {/* Add root node button */}
      {addParentId === "" ? (
        <NodeForm
          tenantId={tenantId}
          flat={flat}
          levels={levels}
          editingNode={null}
          defaultParentId=""
          onSaved={() => { setAddParentId(null); refreshNodes(); }}
          onCancel={() => setAddParentId(null)}
        />
      ) : (
        <button
          type="button"
          onClick={() => { setAddParentId(""); setEditNodeId(null); }}
          className="px-4 py-2 border-2 border-dashed border-emerald-300 text-emerald-700 text-sm font-medium rounded-lg hover:bg-emerald-50 w-full"
        >
          + Add root node (L1)
        </button>
      )}

      {/* Tree */}
      {nodes.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-6">
          {t("org_setup.no_nodes_yet")}
        </p>
      ) : (
        <div className="space-y-1.5">
          {nodes.map((n) => renderNode(n, 0))}
        </div>
      )}
    </div>
  );
}

/* ── Tab 3: Approval Rules ────────────────────────────────────────────────── */

interface ApprovalTier {
  id: string;
  max_quantity: number | null;  // null = unlimited (last tier)
  approver_role: string;
  auto_approve: boolean;
  notify_above: boolean;
  notify_all: boolean;
}

interface SavedApprovalRule {
  transaction_type: string;
  min_quantity: number | null;
  max_quantity: number | null;
  approver_role: string;
  authority_level?: number;
  approval_order: number;
  auto_approve?: boolean;
  notify_levels?: number[];
}

type TxTabKey = "PULL" | "PUSH" | "ADJUSTMENT" | "RECEIVE" | "ISSUE";

const TX_TABS: { key: TxTabKey; label: string }[] = [
  { key: "PULL",       label: "PULL / SISTER" },
  { key: "PUSH",       label: "PUSH" },
  { key: "ADJUSTMENT", label: "Adjustment" },
  { key: "RECEIVE",    label: "Receive" },
  { key: "ISSUE",      label: "Issue" },
];

const ALL_NOTIFY_LEVELS = [1, 2, 3, 4];
const ROLE_AUTH: Record<string, number> = {
  SA: 1, TA: 1, NM: 1, RM: 2, LM: 3, WM: 4,
};

function mkTier(
  role = "",
  maxQty: number | null = null,
  autoApprove = false,
): ApprovalTier {
  return {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
    max_quantity: maxQty,
    approver_role: role,
    auto_approve: autoApprove,
    notify_above: false,
    notify_all: false,
  };
}

// Build pre-populated tiers from hierarchy levels when no saved rules exist.
// Sorted bottom→top: highest level_number (WH) → lowest level_number (NM/Main).
// Ground tier: qty=100, auto_approve=true. Top tier: unlimited, auto_approve=false.
function buildDefaultTiers(levels: HierarchyLevel[]): ApprovalTier[] {
  if (levels.length === 0) return [mkTier()];
  const sorted = [...levels].sort((a, b) => b.level_number - a.level_number);
  return sorted.map((lv, i) => {
    const isLast = i === sorted.length - 1;
    // 10^(i+2): i=0→100, i=1→1000, i=2→10000 ...
    const maxQty = isLast ? null : Math.pow(10, i + 2);
    return mkTier(lv.default_role_code, maxQty, i === 0);
  });
}

function tiersFromRules(rules: SavedApprovalRule[]): ApprovalTier[] {
  if (!rules.length) return [mkTier()];
  return rules
    .slice()
    .sort((a, b) => a.approval_order - b.approval_order)
    .map((r, idx) => ({
      id: `saved_${idx}`,
      max_quantity: r.max_quantity,
      approver_role: r.approver_role,
      auto_approve: r.auto_approve ?? false,
      notify_above: r.notify_levels?.length === 1,
      notify_all: (r.notify_levels?.length ?? 0) >= 4,
    }));
}

function tiersToRules(tiers: ApprovalTier[], txType: string): SavedApprovalRule[] {
  let prev: number | null = null;
  return tiers.map((tier, idx) => {
    const authLevel = ROLE_AUTH[tier.approver_role] ?? 4;
    const notifyLevels: number[] = tier.auto_approve
      ? tier.notify_all
        ? ALL_NOTIFY_LEVELS
        : tier.notify_above
          ? [Math.max(1, authLevel - 1)]
          : []
      : [];
    const rule: SavedApprovalRule = {
      transaction_type: txType,
      min_quantity: prev,
      max_quantity: tier.max_quantity,
      approver_role: tier.approver_role,
      authority_level: authLevel,
      approval_order: idx + 1,
      auto_approve: tier.auto_approve,
      notify_levels: notifyLevels,
    };
    prev = tier.max_quantity;
    return rule;
  });
}

function validateTiers(tiers: ApprovalTier[]): string | null {
  if (tiers.length === 0) return "At least one tier is required.";
  const last = tiers[tiers.length - 1];
  if (!last) return "At least one tier is required.";
  if (last.max_quantity !== null) return "Last tier must be unlimited.";
  for (let i = 0; i < tiers.length; i++) {
    const tier = tiers[i];
    if (!tier) continue;
    const isLast = i === tiers.length - 1;
    if (!isLast && tier.max_quantity === null) {
      return `Tier ${i + 1}: enter an upper bound — only the last tier can be unlimited.`;
    }
    if (!tier.approver_role) return `Tier ${i + 1}: please select an approver.`;
    if (!isLast) {
      const nxt = tiers[i + 1];
      if (nxt && nxt.max_quantity !== null && tier.max_quantity !== null && tier.max_quantity >= nxt.max_quantity) {
        return `Upper bounds must be ascending: tier ${i + 1} (${tier.max_quantity.toLocaleString()} units) must be less than tier ${i + 2} (${nxt.max_quantity.toLocaleString()} units).`;
      }
    }
  }
  return null;
}

function TierTable({
  tiers,
  setTiers,
  levels,
}: {
  tiers: ApprovalTier[];
  setTiers: (fn: (prev: ApprovalTier[]) => ApprovalTier[]) => void;
  levels: HierarchyLevel[];
}) {
  function updateTier(i: number, patch: Partial<ApprovalTier>) {
    setTiers((prev) => prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  }

  function deleteTier(i: number) {
    setTiers((prev) => {
      const next = prev.filter((_, idx) => idx !== i);
      if (next.length === 0) return [mkTier()];
      const lastItem = next[next.length - 1];
      if (lastItem !== undefined && lastItem.max_quantity !== null) {
        const updated: ApprovalTier = { ...lastItem, max_quantity: null };
        next[next.length - 1] = updated;
      }
      return next;
    });
  }

  function addTier() {
    setTiers((prev) => {
      const maxSoFar = prev
        .slice(0, -1)
        .reduce((m, tier) => Math.max(m, tier.max_quantity ?? 0), 0);
      const proposed = maxSoFar > 0 ? maxSoFar * 10 : 100;
      const updated = prev.map((tier, i) =>
        i === prev.length - 1 ? { ...tier, max_quantity: proposed } : tier
      );
      return [...updated, mkTier()];
    });
  }

  const lastTier = tiers[tiers.length - 1];
  // Hide "+ Add Tier" when the last tier already requires the highest authority (Level 1 = NM/TA/SA)
  const canAddTier = !lastTier || (ROLE_AUTH[lastTier.approver_role] ?? 5) > 1;

  return (
    <div className="space-y-3">
      {/* Enhancement 5 — helper instruction note */}
      <div className="flex gap-2 items-start px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
        <span className="text-blue-500 shrink-0 mt-0.5">ℹ</span>
        <p className="text-xs text-blue-800 whitespace-pre-line">{t("approval.tier_help")}</p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 w-10">No</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 w-40">Up To (units)</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500">Approver</th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 w-32">{t("approval.auto_approve")}</th>
              <th className="px-3 py-2 w-10"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {tiers.map((tier, i) => {
              const isLastTier = i === tiers.length - 1;
              const approverAuthLevel = ROLE_AUTH[tier.approver_role] ?? 5;
              const isLevel1Approver = approverAuthLevel === 1;
              return (
                <Fragment key={tier.id}>
                  <tr className="hover:bg-gray-50">
                    <td className="px-3 py-2.5 text-gray-400 font-mono text-xs">{i + 1}</td>
                    <td className="px-3 py-2.5">
                      {isLastTier ? (
                        <span className="text-sm text-gray-400 italic">unlimited</span>
                      ) : (
                        <input
                          type="number"
                          min={1}
                          value={tier.max_quantity ?? ""}
                          onChange={(e) =>
                            updateTier(i, {
                              max_quantity: e.target.value ? Number(e.target.value) : null,
                            })
                          }
                          className="w-28 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                        />
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <select
                        value={tier.approver_role}
                        onChange={(e) => updateTier(i, { approver_role: e.target.value })}
                        className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                      >
                        <option value="">— select —</option>
                        {levels.map((lv) => (
                          <option key={lv.default_role_code} value={lv.default_role_code}>
                            {lv.level_name} ({lv.role_display_label})
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={tier.auto_approve}
                          onChange={(e) =>
                            updateTier(i, {
                              auto_approve: e.target.checked,
                              notify_above: e.target.checked ? tier.notify_above : false,
                              notify_all: e.target.checked ? tier.notify_all : false,
                            })
                          }
                          className="rounded"
                        />
                        <span className="text-xs text-gray-600">{t("approval.auto_approve")}</span>
                      </label>
                    </td>
                    {/* Enhancement 4 — delete button on every tier */}
                    <td className="px-3 py-2.5">
                      <button
                        type="button"
                        onClick={() => deleteTier(i)}
                        className="text-red-400 hover:text-red-600 text-base leading-none"
                        aria-label="Remove tier"
                      >
                        🗑
                      </button>
                    </td>
                  </tr>
                  {tier.auto_approve && (
                    <tr key={`${tier.id}-notify`}>
                      <td></td>
                      <td colSpan={3} className="px-3 py-2 bg-blue-50">
                        <div className="flex items-center gap-4 text-xs text-gray-600 pl-2 border-l-2 border-blue-300">
                          <span className="font-medium">Notify:</span>
                          {/* Enhancement 3 — hide "Notify level above" for Level 1 approvers */}
                          {!isLevel1Approver && (
                            <label className="flex items-center gap-1 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={tier.notify_above}
                                onChange={(e) => updateTier(i, { notify_above: e.target.checked })}
                                className="rounded"
                              />
                              {t("approval.notify_above")}
                            </label>
                          )}
                          <label className="flex items-center gap-1 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={tier.notify_all}
                              onChange={(e) => updateTier(i, { notify_all: e.target.checked })}
                              className="rounded"
                            />
                            {t("approval.notify_all")}
                          </label>
                        </div>
                      </td>
                      <td className="bg-blue-50"></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* Enhancement 2 — hide "+ Add Tier" when already at highest authority (Level 1) */}
      {canAddTier && (
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={addTier}
            className="px-3 py-1.5 border border-dashed border-emerald-400 text-emerald-700 text-sm rounded hover:bg-emerald-50"
          >
            + {t("approval.add_tier")}
          </button>
          <p className="text-xs text-gray-400">{t("approval.tier_hint")}</p>
        </div>
      )}
    </div>
  );
}

function defaultCustomTiers(): Record<TxTabKey, ApprovalTier[]> {
  return {
    PULL:       [mkTier()],
    PUSH:       [mkTier()],
    ADJUSTMENT: [mkTier()],
    RECEIVE:    [mkTier()],
    ISSUE:      [mkTier()],
  };
}

function ApprovalRulesTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [simpleMode, setSimpleMode] = useState(true);
  const [simpleTiers, setSimpleTiers] = useState<ApprovalTier[]>([mkTier()]);
  const [customTiers, setCustomTiers] = useState<Record<TxTabKey, ApprovalTier[]>>(
    defaultCustomTiers
  );
  const [activeCustomTab, setActiveCustomTab] = useState<TxTabKey>("PULL");
  const [initialized, setInitialized] = useState(false);
  const [pendingSwitch, setPendingSwitch] = useState(false);
  const [switchNotice, setSwitchNotice] = useState<string | null>(null);
  const [gapError, setGapError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const { data: levels = [], isLoading: levelsLoading } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn: () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });

  const { data: savedRules = [], isLoading: rulesLoading } = useQuery<SavedApprovalRule[]>({
    queryKey: ["approval-rules", tenantId],
    queryFn: () => api.get<SavedApprovalRule[]>(`/api/v1/tenants/${tenantId}/approval-rules`),
    staleTime: 30_000,
  });

  if (!initialized && !rulesLoading && !levelsLoading) {
    if (savedRules.length > 0) {
      const pullTiers = tiersFromRules(
        savedRules.filter((r) => r.transaction_type === "PULL")
      );
      const allSame = (["PUSH", "ADJUSTMENT", "RECEIVE", "ISSUE"] as const).every((tx) => {
        const compare = tiersFromRules(savedRules.filter((r) => r.transaction_type === tx));
        return (
          JSON.stringify(
            compare.map(({ approver_role, max_quantity, auto_approve }) => ({
              approver_role, max_quantity, auto_approve,
            }))
          ) ===
          JSON.stringify(
            pullTiers.map(({ approver_role, max_quantity, auto_approve }) => ({
              approver_role, max_quantity, auto_approve,
            }))
          )
        );
      });

      if (allSame) {
        setSimpleMode(true);
        setSimpleTiers(pullTiers.length > 0 ? pullTiers : [mkTier()]);
      } else {
        setSimpleMode(false);
        setCustomTiers({
          PULL:       tiersFromRules(savedRules.filter((r) => r.transaction_type === "PULL")),
          PUSH:       tiersFromRules(savedRules.filter((r) => r.transaction_type === "PUSH")),
          ADJUSTMENT: tiersFromRules(savedRules.filter((r) => r.transaction_type === "ADJUSTMENT")),
          RECEIVE:    tiersFromRules(savedRules.filter((r) => r.transaction_type === "RECEIVE")),
          ISSUE:      tiersFromRules(savedRules.filter((r) => r.transaction_type === "ISSUE")),
        });
      }
    } else if (levels.length > 0) {
      const baseTiers = buildDefaultTiers(levels);
      const freshCopy = () =>
        baseTiers.map((tier) => ({
          ...tier,
          id: `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
        }));
      setSimpleTiers(freshCopy());
      setCustomTiers({
        PULL:       freshCopy(),
        PUSH:       freshCopy(),
        ADJUSTMENT: freshCopy(),
        RECEIVE:    freshCopy(),
        ISSUE:      freshCopy(),
      });
    }
    setInitialized(true);
  }

  function buildRules(mode?: boolean): SavedApprovalRule[] {
    const useSimple = mode ?? simpleMode;
    if (useSimple) {
      return (["PULL", "SISTER", "PUSH", "ADJUSTMENT", "RECEIVE", "ISSUE"] as const).flatMap(
        (tx) => tiersToRules(simpleTiers, tx)
      );
    }
    return [
      ...tiersToRules(customTiers["PULL"],       "PULL"),
      ...tiersToRules(customTiers["PULL"],       "SISTER"),
      ...tiersToRules(customTiers["PUSH"],       "PUSH"),
      ...tiersToRules(customTiers["ADJUSTMENT"], "ADJUSTMENT"),
      ...tiersToRules(customTiers["RECEIVE"],    "RECEIVE"),
      ...tiersToRules(customTiers["ISSUE"],      "ISSUE"),
    ];
  }

  function handleConfirmSwitch() {
    const newMode = !simpleMode;
    const notice = newMode
      ? t("approval.switched_to_simple")
      : t("approval.switched_to_custom");
    setSimpleMode(newMode);
    setPendingSwitch(false);
    setSwitchNotice(notice);
    setSaveOk(false);
    saveMutation.mutate({ rules: buildRules(newMode), simple_mode: newMode });
  }

  function handleSave() {
    const tierSets = simpleMode
      ? [simpleTiers]
      : Object.values(customTiers);
    for (const ts of tierSets) {
      const err = validateTiers(ts);
      if (err) { setGapError(err); return; }
    }
    setGapError(null);
    setSwitchNotice(null);
    saveMutation.mutate({ rules: buildRules(), simple_mode: simpleMode });
  }

  function copyToAll() {
    const src = customTiers[activeCustomTab];
    setCustomTiers({
      PULL:       src.map((t) => ({ ...t, id: `${Date.now()}_${Math.random()}` })),
      PUSH:       src.map((t) => ({ ...t, id: `${Date.now()}_${Math.random()}` })),
      ADJUSTMENT: src.map((t) => ({ ...t, id: `${Date.now()}_${Math.random()}` })),
      RECEIVE:    src.map((t) => ({ ...t, id: `${Date.now()}_${Math.random()}` })),
      ISSUE:      src.map((t) => ({ ...t, id: `${Date.now()}_${Math.random()}` })),
    });
  }

  const saveMutation = useMutation({
    mutationFn: ({ rules, simple_mode }: { rules: SavedApprovalRule[]; simple_mode: boolean }) =>
      api.put(`/api/v1/tenants/${tenantId}/approval-rules`, { simple_mode, rules }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approval-rules", tenantId] });
      setSaveOk(true);
      setSaveErr(null);
    },
    onError: (e: unknown) => {
      setSaveErr(e instanceof Error ? e.message : t("common.error"));
      setSaveOk(false);
    },
  });

  const customTabCls = (k: TxTabKey) =>
    `px-3 py-1.5 text-xs font-semibold border-b-2 transition-all ${
      activeCustomTab === k
        ? "border-emerald-600 text-emerald-700"
        : "border-transparent text-gray-500 hover:text-gray-700"
    }`;

  if (rulesLoading) {
    return <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-gray-900">{t("approval_rules.section")}</h3>
        <p className="text-sm text-gray-500 mt-0.5">
          {t("approval.rules_desc")}
        </p>
      </div>

      {/* Mode selector */}
      <div className="space-y-3">
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => !simpleMode && setPendingSwitch(true)}
            className={`flex-1 text-left rounded-lg border-2 px-4 py-3 transition-all ${
              simpleMode
                ? "border-emerald-500 bg-emerald-50"
                : "border-gray-200 bg-white hover:border-gray-300"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-semibold text-gray-900">{t("approval.simple_mode_title")}</span>
              {simpleMode ? (
                <span className="text-xs font-medium text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full">
                  {"●"} {t("approval.active")}
                </span>
              ) : (
                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                  {"○"} {t("approval.saved")}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500">{t("approval.simple_mode_desc")}</p>
          </button>

          <button
            type="button"
            onClick={() => simpleMode && setPendingSwitch(true)}
            className={`flex-1 text-left rounded-lg border-2 px-4 py-3 transition-all ${
              !simpleMode
                ? "border-emerald-500 bg-emerald-50"
                : "border-gray-200 bg-white hover:border-gray-300"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-semibold text-gray-900">{t("approval.custom_mode_title")}</span>
              {!simpleMode ? (
                <span className="text-xs font-medium text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full">
                  {"●"} {t("approval.active")}
                </span>
              ) : (
                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                  {"○"} {t("approval.saved")}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500">{t("approval.custom_mode_desc")}</p>
          </button>
        </div>

        {pendingSwitch && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 space-y-2">
            <p className="text-sm text-amber-800">
              {"⚠"} {simpleMode ? t("approval.switch_warning_custom") : t("approval.switch_warning_simple")}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleConfirmSwitch}
                className="px-3 py-1.5 bg-emerald-700 text-white text-xs font-semibold rounded hover:bg-emerald-800"
              >
                {t("approval.confirm_switch")}
              </button>
              <button
                type="button"
                onClick={() => setPendingSwitch(false)}
                className="px-3 py-1.5 border border-gray-300 text-gray-700 text-xs rounded hover:bg-gray-50"
              >
                {t("common.cancel")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Simple mode — one table for all transaction types */}
      {simpleMode && (
        <TierTable tiers={simpleTiers} setTiers={setSimpleTiers} levels={levels} />
      )}

      {/* Custom mode — per-type tabs */}
      {!simpleMode && (
        <div className="space-y-4">
          <div className="flex border-b border-gray-200">
            {TX_TABS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                className={customTabCls(key)}
                onClick={() => setActiveCustomTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {activeCustomTab === "PULL" && (
            <p className="text-xs text-gray-500 italic">
              {t("approval.sister_shares_pull")}
            </p>
          )}

          <TierTable
            tiers={customTiers[activeCustomTab]}
            setTiers={(fn) =>
              setCustomTiers((prev) => ({
                ...prev,
                [activeCustomTab]: fn(prev[activeCustomTab]),
              }))
            }
            levels={levels}
          />

          <button
            type="button"
            onClick={copyToAll}
            className="px-3 py-1.5 border border-gray-300 text-gray-600 text-sm rounded hover:bg-gray-50"
          >
            {t("approval.copy_to_all")}
          </button>
        </div>
      )}

      {gapError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {gapError}
        </p>
      )}
      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}
      {saveOk && !switchNotice && <p className="text-sm text-emerald-600 font-medium">{t("approval_rules.saved")}</p>}
      {switchNotice && <p className="text-sm text-emerald-600 font-medium">{switchNotice}</p>}

      <button
        type="button"
        onClick={handleSave}
        disabled={saveMutation.isPending}
        className="px-5 py-2 bg-emerald-700 text-white text-sm font-semibold rounded-lg hover:bg-emerald-800 disabled:opacity-50"
      >
        {saveMutation.isPending ? t("common.saving") : t("approval_rules.save_button")}
      </button>
    </div>
  );
}

/* ── Shared position types ──────────────────────────────────────────────────── */

interface SelfApprovalPolicy {
  id: string; tenant_id: string; role_code: string; level_number: number;
  transfer_types: string[]; threshold_type: string;
  qty_limit: number | null; value_limit: number | null; is_active: boolean;
}

interface Position {
  id: string;
  title: string;
  role_code: string;
  reports_to_position_id: string | null;
  reports_to_title: string | null;
  current_holder: { user_id: string; name: string; email: string; assignment_type: string } | null;
  is_active: boolean;
}
interface NodePositionGroup { node_id: string; node_name: string; level_number: number; positions: Position[] }

const POSITION_ROLES = [
  { code: "NM", label: "National Manager" },
  { code: "RM", label: "Regional Manager" },
  { code: "LM", label: "Logistics Manager" },
  { code: "WM", label: "Warehouse Manager" },
  { code: "AU", label: "Auditor" },
  { code: "RT", label: "Retailer" },
] as const;

/* ── Tab 3: Positions ───────────────────────────────────────────────────────── */

function PositionsTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm]         = useState(false);
  const [editPosId, setEditPosId]             = useState<string | null>(null);
  const [formTitle, setFormTitle]             = useState("");
  const [formRole, setFormRole]               = useState("WM");
  const [formReportsTo, setFormReportsTo]     = useState<string>("");
  const [formErr, setFormErr]                 = useState<string | null>(null);
  const [saving, setSaving]                   = useState(false);

  // Self-approval form state
  const [formSAEnabled, setFormSAEnabled]         = useState(false);
  const [formSATypes, setFormSATypes]             = useState<string[]>(["PULL","PUSH","SISTER"]);
  const [formSAThreshold, setFormSAThreshold]     = useState<"QUANTITY"|"VALUE"|"EITHER">("QUANTITY");
  const [formSAQtyLimit, setFormSAQtyLimit]       = useState("");
  const [formSAValueLimit, setFormSAValueLimit]   = useState("");

  const { data: levels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });
  const { data: nodes = [], isLoading: nodesLoading } = useQuery<OrgNode[]>({
    queryKey: ["org-nodes", tenantId],
    queryFn:  () => api.get<OrgNode[]>(`/api/v1/tenants/${tenantId}/nodes`),
    staleTime: 0,
  });
  const { data: posGroups = [], isLoading: posLoading } = useQuery<NodePositionGroup[]>({
    queryKey: ["positions", tenantId],
    queryFn:  () => api.get<NodePositionGroup[]>(`/api/v1/tenants/${tenantId}/positions`),
    staleTime: 0,
    enabled:  !!tenantId,
  });
  const { data: selfApprovalPolicies = [] } = useQuery<SelfApprovalPolicy[]>({
    queryKey: ["self-approval-policies", tenantId],
    queryFn:  () => api.get<SelfApprovalPolicy[]>(`/api/v1/tenants/${tenantId}/self-approval-policies`),
    staleTime: 0,
    enabled:  !!tenantId,
  });

  const allPositions: Position[] = posGroups.flatMap((g) => g.positions);
  const selectedGroup = posGroups.find((g) => g.node_id === selectedNodeId);

  const policyMap = useMemo(() => {
    const map = new Map<string, SelfApprovalPolicy>();
    selfApprovalPolicies.forEach((p) => map.set(`${p.role_code}-${p.level_number}`, p));
    return map;
  }, [selfApprovalPolicies]);

  function resetSAState(policy?: SelfApprovalPolicy) {
    setFormSAEnabled(policy?.is_active ?? false);
    setFormSATypes(policy?.transfer_types ?? ["PULL","PUSH","SISTER"]);
    setFormSAThreshold((policy?.threshold_type ?? "QUANTITY") as "QUANTITY"|"VALUE"|"EITHER");
    setFormSAQtyLimit(policy?.qty_limit != null ? String(policy.qty_limit) : "");
    setFormSAValueLimit(policy?.value_limit != null ? String(policy.value_limit) : "");
  }

  function openAdd() {
    setEditPosId(null); setFormTitle(""); setFormRole("WM"); setFormReportsTo(""); setFormErr(null);
    resetSAState();
    setShowAddForm(true);
  }
  function openEdit(pos: Position) {
    setEditPosId(pos.id); setFormTitle(pos.title); setFormRole(pos.role_code);
    setFormReportsTo(pos.reports_to_position_id ?? ""); setFormErr(null);
    const existing = policyMap.get(`${pos.role_code}-${selectedGroup?.level_number ?? 0}`);
    resetSAState(existing);
    setShowAddForm(false);
  }
  function cancelForm() { setShowAddForm(false); setEditPosId(null); resetSAState(); }

  async function savePosition() {
    if (!formTitle.trim()) { setFormErr(t("position.title") + " is required."); return; }
    setSaving(true); setFormErr(null);
    try {
      const body = {
        title: formTitle.trim(), role_code: formRole,
        reports_to_position_id: formReportsTo || null,
      };
      if (editPosId) {
        await api.patch(`/api/v1/tenants/${tenantId}/positions/${editPosId}`, body);
      } else {
        await api.post(`/api/v1/tenants/${tenantId}/nodes/${selectedNodeId}/positions`, body);
      }
      void qc.invalidateQueries({ queryKey: ["positions", tenantId] });
      // Save self-approval policy (upsert enabled or disabled state)
      if (selectedGroup) {
        const levelNumber = selectedGroup.level_number;
        const roleToSave = editPosId ? formRole : formRole;
        const existingPolicy = policyMap.get(`${roleToSave}-${levelNumber}`);
        if (formSAEnabled || existingPolicy) {
          await api.put(`/api/v1/tenants/${tenantId}/self-approval-policies`, [{
            role_code:       roleToSave,
            level_number:    levelNumber,
            transfer_types:  formSATypes,
            threshold_type:  formSAThreshold,
            qty_limit:       formSAQtyLimit ? parseFloat(formSAQtyLimit) : null,
            value_limit:     formSAValueLimit ? parseFloat(formSAValueLimit) : null,
            is_active:       formSAEnabled,
          }]);
          void qc.invalidateQueries({ queryKey: ["self-approval-policies", tenantId] });
        }
      }
      cancelForm();
    } catch (e) { setFormErr(e instanceof Error ? e.message : t("common.error")); }
    setSaving(false);
  }

  async function deletePosition(posId: string, title: string) {
    if (!confirm(`Delete position "${title}"?`)) return;
    try {
      await api.delete(`/api/v1/tenants/${tenantId}/positions/${posId}`);
      void qc.invalidateQueries({ queryKey: ["positions", tenantId] });
      if (editPosId === posId) cancelForm();
    } catch (e) { alert(e instanceof Error ? e.message : t("common.error")); }
  }

  function renderTreeNode(node: OrgNode, depth: number): React.ReactNode {
    const levelLabel = levels.find((l) => l.level_number === node.hierarchy_level)?.level_name ?? `L${node.hierarchy_level}`;
    const isSelected = node.id === selectedNodeId;
    const groupCount = posGroups.find((g) => g.node_id === node.id)?.positions.length ?? 0;
    return (
      <div key={node.id}>
        <button
          type="button"
          onClick={() => { setSelectedNodeId(node.id); cancelForm(); }}
          className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-all ${
            isSelected ? "border-emerald-500 bg-emerald-50 font-semibold" : "border-gray-200 bg-white hover:bg-gray-50"
          }`}
          style={{ marginLeft: `${depth * 16}px` }}
        >
          <span className="shrink-0">{node.is_stock_holding ? "🏭" : "📋"}</span>
          <span className="flex-1 truncate">{node.name}</span>
          <span className="text-xs text-gray-400 shrink-0">{levelLabel}</span>
          {groupCount > 0 && <span className="text-xs bg-emerald-100 text-emerald-700 px-1.5 rounded-full shrink-0">{groupCount}</span>}
        </button>
        {node.children.map((c) => renderTreeNode(c, depth + 1))}
      </div>
    );
  }

  const selectedNode = flattenNodes(nodes).find((n) => n.id === selectedNodeId);

  return (
    <div className="flex gap-4" style={{ minHeight: "480px" }}>
      {/* Left: tree */}
      <div className="w-64 shrink-0 space-y-1 border-r border-gray-200 pr-4 overflow-y-auto" style={{ maxHeight: "600px" }}>
        {nodesLoading ? <p className="text-xs text-gray-400 py-4 text-center">{t("common.loading")}</p>
          : nodes.length === 0 ? <p className="text-xs text-gray-400 py-4 text-center">No nodes. Set up the Tree first.</p>
          : nodes.map((n) => renderTreeNode(n, 0))}
      </div>

      {/* Right: positions */}
      <div className="flex-1 min-w-0">
        {!selectedNodeId ? (
          <p className="text-sm text-gray-400 py-8 text-center">{t("position.select_node")}</p>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-800">
                {t("wizard.positions_tab")}: {selectedGroup?.node_name ?? ""}
              </h3>
              {!showAddForm && !editPosId && (
                <button type="button" onClick={openAdd}
                  className="px-3 py-1 bg-emerald-600 text-white text-xs font-semibold rounded hover:bg-emerald-700">
                  + {t("position.add")}
                </button>
              )}
            </div>

            {/* Add/edit form */}
            {(showAddForm || editPosId) && (
              <div className="border border-emerald-300 rounded-lg p-4 bg-emerald-50 space-y-3">
                <p className="text-xs font-bold uppercase text-emerald-700">{editPosId ? "Edit Position" : t("position.add")}</p>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">{t("position.title")} *</label>
                  <input value={formTitle} onChange={(e) => setFormTitle(e.target.value)}
                    className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm" placeholder="e.g. Warehouse Manager" />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">{t("position.role")} *</label>
                  <select value={formRole} onChange={(e) => setFormRole(e.target.value)}
                    className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm bg-white">
                    {POSITION_ROLES.map((r) => <option key={r.code} value={r.code}>{r.label} ({r.code})</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">{t("position.reports_to")}</label>
                  <select value={formReportsTo} onChange={(e) => setFormReportsTo(e.target.value)}
                    className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm bg-white">
                    <option value="">— none —</option>
                    {allPositions.filter((p) => p.id !== editPosId).map((p) => (
                      <option key={p.id} value={p.id}>{p.title} ({p.role_code})</option>
                    ))}
                  </select>
                </div>

                {/* Self-approval section */}
                <div className="border border-blue-200 rounded-lg p-3 bg-blue-50 space-y-3">
                  <p className="text-xs font-bold uppercase text-blue-700">{t("org_setup.self_approval_title")}</p>
                  <p className="text-xs text-gray-600">{t("org_setup.self_approval_desc")}</p>
                  {selectedGroup && (
                    <p className="text-xs text-blue-600 bg-blue-100 rounded px-2 py-1">
                      {t("org_setup.self_approval_level_note")
                        .replace("{role}", (() => {
                          const lv = levels.find((l) => l.default_role_code === formRole);
                          return lv ? `${lv.role_display_label} (${formRole})` : formRole;
                        })())
                        .replace("{level}", levels.find((l) => l.level_number === selectedGroup.level_number)?.level_name ?? `L${selectedGroup.level_number}`)}
                    </p>
                  )}
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" checked={formSAEnabled}
                      onChange={(e) => setFormSAEnabled(e.target.checked)}
                      className="rounded border-gray-300 text-blue-600" />
                    <span className="text-xs font-medium text-gray-700">{t("org_setup.self_approval_enable")}</span>
                  </label>
                  {formSAEnabled && (
                    <div className="space-y-3 pt-1">
                      <div>
                        <label className="block text-xs font-bold text-gray-700 mb-1">{t("org_setup.self_approval_transfer_types")}</label>
                        <div className="flex gap-3">
                          {(["PULL","PUSH","SISTER"] as const).map((tt) => (
                            <label key={tt} className="flex items-center gap-1 text-xs cursor-pointer">
                              <input type="checkbox"
                                checked={formSATypes.includes(tt)}
                                onChange={(e) => setFormSATypes(e.target.checked
                                  ? [...formSATypes, tt]
                                  : formSATypes.filter((x) => x !== tt))}
                                className="rounded border-gray-300 text-blue-600" />
                              {tt}
                            </label>
                          ))}
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs font-bold text-gray-700 mb-1">{t("org_setup.self_approval_threshold_type")}</label>
                        <div className="flex gap-4">
                          {(["QUANTITY","VALUE","EITHER"] as const).map((thr) => (
                            <label key={thr} className="flex items-center gap-1 text-xs cursor-pointer">
                              <input type="radio" name="sa-threshold" value={thr}
                                checked={formSAThreshold === thr}
                                onChange={() => setFormSAThreshold(thr)}
                                className="border-gray-300 text-blue-600" />
                              {t(`org_setup.threshold_${thr.toLowerCase()}`)}
                            </label>
                          ))}
                        </div>
                      </div>
                      {(formSAThreshold === "QUANTITY" || formSAThreshold === "EITHER") && (
                        <div>
                          <label className="block text-xs font-bold text-gray-700 mb-1">{t("org_setup.self_approval_qty_limit")}</label>
                          <input type="number" min="0" value={formSAQtyLimit}
                            onChange={(e) => setFormSAQtyLimit(e.target.value)}
                            placeholder={t("org_setup.self_approval_unlimited")}
                            className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm" />
                        </div>
                      )}
                      {(formSAThreshold === "VALUE" || formSAThreshold === "EITHER") && (
                        <div>
                          <label className="block text-xs font-bold text-gray-700 mb-1">{t("org_setup.self_approval_value_limit")}</label>
                          <input type="number" min="0" value={formSAValueLimit}
                            onChange={(e) => setFormSAValueLimit(e.target.value)}
                            placeholder={t("org_setup.self_approval_unlimited")}
                            className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm" />
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {formErr && <p className="text-xs text-red-600">{formErr}</p>}
                <div className="flex gap-2">
                  <button type="button" onClick={() => void savePosition()} disabled={saving}
                    className="px-3 py-1.5 bg-emerald-600 text-white text-xs font-semibold rounded hover:bg-emerald-700 disabled:opacity-50">
                    {saving ? t("common.saving") : t("position.save")}
                  </button>
                  <button type="button" onClick={cancelForm}
                    className="px-3 py-1.5 border border-gray-300 text-gray-600 text-xs rounded hover:bg-gray-50">
                    {t("common.cancel")}
                  </button>
                </div>
              </div>
            )}

            {/* Positions list */}
            {posLoading ? <p className="text-xs text-gray-400">{t("common.loading")}</p>
              : (selectedGroup?.positions ?? []).length === 0 && !showAddForm ? (
                <p className="text-sm text-gray-400 py-4 text-center">{t("position.no_positions")}</p>
              ) : (
                <div className="space-y-2">
                  {(selectedGroup?.positions ?? []).filter((p) => p.is_active).map((pos) => (
                    <div key={pos.id} className={`border rounded-lg p-3 flex items-start justify-between gap-3 ${
                      editPosId === pos.id ? "border-blue-300 bg-blue-50" : "border-gray-200 bg-white"}`}>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-gray-800 m-0">{pos.title}</p>
                        <p className="text-xs text-gray-500 m-0">{t("position.role")}: {pos.role_code}{pos.reports_to_title ? ` · Reports to: ${pos.reports_to_title}` : ""}</p>
                        <p className="text-xs m-0 mt-0.5">
                          {t("position.holder")}: {pos.current_holder
                            ? <span className="text-emerald-700 font-medium">{pos.current_holder.name}</span>
                            : <span className="text-gray-400">{t("position.vacant")}</span>}
                        </p>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button type="button" onClick={() => openEdit(pos)}
                          className="w-6 h-6 flex items-center justify-center text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-100 bg-white">✏</button>
                        <button type="button" onClick={() => void deletePosition(pos.id, pos.title)}
                          className="w-6 h-6 flex items-center justify-center text-xs rounded border border-red-200 text-red-500 hover:bg-red-50 bg-white">🗑</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Tab 4: Transfer Types ──────────────────────────────────────────────────── */

interface LevelPermission { level_number: number; level_name?: string | null; can_initiate: boolean; can_receive: boolean }
interface TransferTypeConfig { id: string; underlying_type: "PULL" | "PUSH" | "SISTER"; display_name: string; description: string | null; is_active: boolean; sort_order: number; level_permissions: LevelPermission[] }

const UNDERLYING_TYPES: Array<{ key: "PULL" | "PUSH" | "SISTER"; labelKey: string; icon: string }> = [
  { key: "PULL",   labelKey: "transfer_type.request_stock", icon: "📥" },
  { key: "PUSH",   labelKey: "transfer_type.send_stock",    icon: "📤" },
  { key: "SISTER", labelKey: "transfer_type.exchange",      icon: "🔄" },
];

function TransferTypesTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const { data: levels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });
  const { data: savedTypes = [], isLoading } = useQuery<TransferTypeConfig[]>({
    queryKey: ["transfer-types", tenantId],
    queryFn:  () => api.get<TransferTypeConfig[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    staleTime: 0,
    enabled:  !!tenantId,
  });

  // Local editable state — initialise from saved or defaults
  const [configs, setConfigs] = useState<TransferTypeConfig[]>([]);
  const [initialized, setInitialized] = useState(false);

  if (!initialized && !isLoading) {
    const defaults: TransferTypeConfig[] = UNDERLYING_TYPES.map((ut) => {
      const saved = savedTypes.find((s) => s.underlying_type === ut.key);
      return saved ?? {
        id: "", underlying_type: ut.key,
        display_name: ut.key === "PULL" ? "Request Stock" : ut.key === "PUSH" ? "Send Stock" : "Branch Exchange",
        description: null, is_active: ut.key !== "SISTER", sort_order: UNDERLYING_TYPES.indexOf(ut),
        level_permissions: levels.map((l) => ({
          level_number: l.level_number, level_name: l.level_name,
          can_initiate: l.level_number >= 2, can_receive: true,
        })),
      };
    });
    setConfigs(defaults);
    setInitialized(true);
  }

  function updateConfig(idx: number, patch: Partial<TransferTypeConfig>) {
    setConfigs((prev) => prev.map((c, i) => i === idx ? { ...c, ...patch } : c));
  }
  function updatePerm(configIdx: number, levelNum: number, field: "can_initiate" | "can_receive", val: boolean) {
    setConfigs((prev) => prev.map((c, i) => {
      if (i !== configIdx) return c;
      const perms = c.level_permissions.map((p) => p.level_number === levelNum ? { ...p, [field]: val } : p);
      // Ensure all current levels are represented
      const existing = new Set(perms.map((p) => p.level_number));
      const merged = [...perms];
      for (const lv of levels) {
        if (!existing.has(lv.level_number)) merged.push({ level_number: lv.level_number, level_name: lv.level_name, can_initiate: false, can_receive: true });
      }
      return { ...c, level_permissions: merged.sort((a, b) => a.level_number - b.level_number) };
    }));
  }

  async function save() {
    setSaving(true); setSaveOk(false); setSaveErr(null);
    try {
      const body = configs.map((c) => ({
        underlying_type: c.underlying_type, display_name: c.display_name,
        description: c.description, is_active: c.is_active, sort_order: c.sort_order,
        level_permissions: levels.map((lv) => {
          const p = c.level_permissions.find((x) => x.level_number === lv.level_number);
          return { level_number: lv.level_number, can_initiate: p?.can_initiate ?? false, can_receive: p?.can_receive ?? true };
        }),
      }));
      await api.put(`/api/v1/tenants/${tenantId}/transfer-types`, body);
      void qc.invalidateQueries({ queryKey: ["transfer-types", tenantId] });
      setSaveOk(true);
    } catch (e) { setSaveErr(e instanceof Error ? e.message : t("common.error")); }
    setSaving(false);
  }

  if (isLoading) return <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>;

  return (
    <div className="space-y-4">
      {configs.map((cfg, idx) => {
        const meta = UNDERLYING_TYPES[idx];
        return (
          <div key={cfg.underlying_type} className={`border-2 rounded-xl p-4 ${cfg.is_active ? "border-emerald-400 bg-emerald-50" : "border-gray-200 bg-gray-50"}`}>
            <div className="flex items-start gap-3 mb-3">
              <input type="checkbox" checked={cfg.is_active} id={`tt-${cfg.underlying_type}`}
                onChange={(e) => updateConfig(idx, { is_active: e.target.checked })}
                className="mt-1 w-4 h-4 accent-emerald-600" />
              <label htmlFor={`tt-${cfg.underlying_type}`} className="text-sm font-bold text-gray-800 cursor-pointer">
                {meta?.icon} {t(meta?.labelKey ?? "")}
              </label>
            </div>
            {cfg.is_active && (
              <div className="pl-7 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-bold text-gray-600 mb-1">{t("transfer_type.display_name")}</label>
                    <input value={cfg.display_name} onChange={(e) => updateConfig(idx, { display_name: e.target.value })}
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-600 mb-1">{t("transfer_type.description")}</label>
                    <input value={cfg.description ?? ""} onChange={(e) => updateConfig(idx, { description: e.target.value || null })}
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                  </div>
                </div>
                {levels.length > 0 && (
                  <div>
                    <p className="text-xs font-bold text-gray-600 mb-1">{t("transfer_type.who_can_initiate")}</p>
                    <div className="flex flex-wrap gap-2">
                      {levels.map((lv) => {
                        const perm = cfg.level_permissions.find((p) => p.level_number === lv.level_number);
                        const canInit = perm?.can_initiate ?? false;
                        return (
                          <label key={lv.level_number} className="flex items-center gap-1.5 text-xs cursor-pointer">
                            <input type="checkbox" checked={canInit}
                              onChange={(e) => updatePerm(idx, lv.level_number, "can_initiate", e.target.checked)}
                              className="w-3.5 h-3.5 accent-emerald-600" />
                            L{lv.level_number}: {lv.level_name}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}
      {saveOk && <p className="text-sm text-emerald-600 font-medium">✓ {t("common.save")}d</p>}
      <button type="button" onClick={() => void save()} disabled={saving}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded hover:bg-blue-700 disabled:opacity-50">
        {saving ? t("common.saving") : t("transfer_type.save")}
      </button>
    </div>
  );
}

/* ── Tab 5: Approval Rules (new transfer_approval_rules API) ────────────────── */

const ADJ_REASON_CODES = [
  "DAMAGE", "EXPIRY", "THEFT", "COUNT_DISCREPANCY",
  "RETURN", "PRODUCTION_USE", "SAMPLE", "OTHER",
];

const ADJ_ROLE_CODES = ["WM", "RM", "LM", "NM", "TA"];

interface AdjRuleLocal {
  id?: string;
  role_code: string;
  level_number: number;
  mode: "GLOBAL" | "PER_CODE";
  reason_code: string | null;
  threshold_type: "QUANTITY" | "VALUE" | "EITHER";
  qty_limit: string;
  value_limit: string;
  approver_role_code: string | null;
  priority: number;
  is_active: boolean;
}

function AdjustmentRulesSection({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [adjMode, setAdjMode] = useState<"GLOBAL" | "PER_CODE">("GLOBAL");
  const [ruleList, setRuleList] = useState<AdjRuleLocal[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const { data: levels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });

  const { data: savedRules = [], isLoading } = useQuery<Array<{
    id: string; role_code: string; level_number: number; mode: string;
    reason_code: string | null; threshold_type: string;
    qty_limit: string | null; value_limit: string | null;
    approver_role_code: string | null; priority: number; is_active: boolean;
  }>>({
    queryKey: ["adj-approval-rules", tenantId],
    queryFn:  () => api.get(`/api/v1/tenants/${tenantId}/adjustment-approval-rules`),
    staleTime: 0,
    enabled:  !!tenantId,
  });

  const effectiveRules: AdjRuleLocal[] = ruleList ?? savedRules.map((r) => ({
    id: r.id,
    role_code: r.role_code,
    level_number: r.level_number,
    mode: (r.mode as "GLOBAL" | "PER_CODE"),
    reason_code: r.reason_code,
    threshold_type: (r.threshold_type as "QUANTITY" | "VALUE" | "EITHER"),
    qty_limit: r.qty_limit ?? "",
    value_limit: r.value_limit ?? "",
    approver_role_code: r.approver_role_code,
    priority: r.priority,
    is_active: r.is_active,
  }));

  const displayMode: "GLOBAL" | "PER_CODE" = ruleList
    ? adjMode
    : effectiveRules.length > 0
    ? effectiveRules[0]!.mode
    : adjMode;

  function getList(): AdjRuleLocal[] { return ruleList ?? effectiveRules; }

  function addRule() {
    setRuleList([...getList(), {
      role_code: "", level_number: 0,
      mode: displayMode, reason_code: null,
      threshold_type: "QUANTITY", qty_limit: "", value_limit: "",
      approver_role_code: null, priority: getList().length + 1, is_active: true,
    }]);
  }
  function removeRule(idx: number) { setRuleList(getList().filter((_, i) => i !== idx)); }
  function updateRule(idx: number, patch: Partial<AdjRuleLocal>) {
    setRuleList(getList().map((r, i) => i === idx ? { ...r, ...patch } : r));
  }
  function handleModeChange(m: "GLOBAL" | "PER_CODE") {
    setAdjMode(m);
    setRuleList(getList().map((r) => ({ ...r, mode: m, reason_code: m === "GLOBAL" ? null : r.reason_code })));
  }

  async function save() {
    setSaving(true); setSaveOk(false); setSaveErr(null);
    try {
      const body = getList().map((r) => ({
        role_code: r.role_code,
        level_number: r.level_number,
        mode: displayMode,
        reason_code: displayMode === "GLOBAL" ? null : (r.reason_code ?? null),
        threshold_type: r.threshold_type,
        qty_limit: r.qty_limit ? parseFloat(r.qty_limit) : null,
        value_limit: r.value_limit ? parseFloat(r.value_limit) : null,
        approver_role_code: r.approver_role_code ?? null,
        priority: r.priority,
        is_active: r.is_active,
      }));
      await api.put(`/api/v1/tenants/${tenantId}/adjustment-approval-rules`, body);
      void qc.invalidateQueries({ queryKey: ["adj-approval-rules", tenantId] });
      setRuleList(null);
      setSaveOk(true);
    } catch (e) { setSaveErr(e instanceof Error ? e.message : t("common.error")); }
    setSaving(false);
  }

  if (isLoading) return <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>;

  const currentList = getList();

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <div className="border border-gray-200 rounded-xl p-4 bg-gray-50">
        <p className="text-sm font-semibold text-gray-700 mb-3">{t("approval_rule.adj_mode_title")}</p>
        <div className="space-y-2">
          {(["GLOBAL", "PER_CODE"] as const).map((m) => (
            <label key={m} className="flex items-start gap-2 cursor-pointer">
              <input type="radio" name="adj-mode" value={m} checked={displayMode === m}
                onChange={() => handleModeChange(m)} className="mt-0.5 accent-emerald-600" />
              <span className="text-sm text-gray-700">
                {t(m === "GLOBAL" ? "approval_rule.adj_mode_global" : "approval_rule.adj_mode_per_code")}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Rule cards */}
      {currentList.length === 0 ? (
        <p className="text-sm text-gray-400 italic py-4 text-center">{t("approval_rule.adj_no_rules")}</p>
      ) : (
        <div className="space-y-3">
          {currentList.map((rule, idx) => (
            <div key={idx} className="border border-gray-200 rounded-xl p-4 bg-white space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase text-gray-500">Rule {idx + 1}</span>
                <div className="flex items-center gap-2">
                  <label className="text-[10px] font-semibold text-gray-400 uppercase">{t("approval_rule.priority_label")}</label>
                  <input type="number" min={0} value={rule.priority}
                    onChange={(e) => updateRule(idx, { priority: Number(e.target.value) })}
                    className="w-14 border border-gray-200 rounded px-1.5 py-0.5 text-xs text-center focus:border-emerald-400 focus:outline-none" />
                  <button type="button" onClick={() => removeRule(idx)}
                    className="w-6 h-6 flex items-center justify-center text-xs rounded border border-red-200 text-red-500 hover:bg-red-50">✕</button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-600 mb-1">{t("approval_rule.adj_role_code")}</label>
                <select
                  value={rule.level_number ?? 0}
                  onChange={(e) => {
                    const lv = levels.find((l) => l.level_number === Number(e.target.value));
                    if (lv) updateRule(idx, { role_code: lv.default_role_code, level_number: lv.level_number });
                    else updateRule(idx, { role_code: "", level_number: 0 });
                  }}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
                >
                  <option value={0}>— {t("approval_rule.adj_select_level")} —</option>
                  {levels.map((l) => (
                    <option key={l.level_number} value={l.level_number}>
                      {l.role_display_label} ({l.default_role_code}) — {l.level_name} (L{l.level_number})
                    </option>
                  ))}
                </select>
              </div>

              {displayMode === "PER_CODE" && (
                <div>
                  <label className="block text-xs font-bold text-gray-600 mb-1">{t("approval_rule.adj_reason_code")}</label>
                  <select value={rule.reason_code ?? ""} onChange={(e) => updateRule(idx, { reason_code: e.target.value || null })}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
                    <option value="">{t("approval_rule.adj_reason_all")}</option>
                    {ADJ_REASON_CODES.map((rc) => <option key={rc} value={rc}>{rc}</option>)}
                  </select>
                </div>
              )}

              <div>
                <p className="text-xs font-bold text-gray-600 mb-1">{t("approval_rule.threshold_type")}</p>
                <div className="flex gap-3 flex-wrap">
                  {(["QUANTITY", "VALUE", "EITHER"] as const).map((tt) => (
                    <label key={tt} className="flex items-center gap-1 text-xs cursor-pointer">
                      <input type="radio" name={`adj-thresh-${idx}`} value={tt} checked={rule.threshold_type === tt}
                        onChange={() => updateRule(idx, { threshold_type: tt })} className="accent-emerald-600" />
                      {t(`approval_rule.${tt.toLowerCase()}`)}
                    </label>
                  ))}
                </div>
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  {(rule.threshold_type === "QUANTITY" || rule.threshold_type === "EITHER") && (
                    <>
                      <input type="number" min={0} value={rule.qty_limit} placeholder={t("approval_rule.adj_qty_limit")}
                        onChange={(e) => updateRule(idx, { qty_limit: e.target.value })}
                        className="w-32 border border-gray-300 rounded px-2 py-1 text-xs" />
                      <span className="text-xs text-gray-400">{t("approval_rule.qty")}</span>
                    </>
                  )}
                  {(rule.threshold_type === "VALUE" || rule.threshold_type === "EITHER") && (
                    <>
                      <input type="number" min={0} value={rule.value_limit} placeholder={t("approval_rule.adj_value_limit")}
                        onChange={(e) => updateRule(idx, { value_limit: e.target.value })}
                        className="w-32 border border-gray-300 rounded px-2 py-1 text-xs" />
                      <span className="text-xs text-gray-400">ETB</span>
                    </>
                  )}
                </div>
              </div>

              <div>
                <p className="text-xs font-bold text-gray-600 mb-1">{t("approval_rule.adj_approval_type")}</p>
                <div className="space-y-1.5">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name={`adj-approv-${idx}`} checked={rule.approver_role_code === null}
                      onChange={() => updateRule(idx, { approver_role_code: null })} className="accent-emerald-600" />
                    <span className="text-xs text-gray-700">{t("approval_rule.adj_self_approve")}</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name={`adj-approv-${idx}`} checked={rule.approver_role_code !== null}
                      onChange={() => updateRule(idx, { approver_role_code: rule.approver_role_code ?? "RM" })} className="accent-emerald-600" />
                    <span className="text-xs text-gray-700">{t("approval_rule.adj_route_to")}:</span>
                    {rule.approver_role_code !== null && (
                      <select value={rule.approver_role_code} onChange={(e) => updateRule(idx, { approver_role_code: e.target.value })}
                        className="border border-gray-300 rounded px-2 py-1 text-xs bg-white">
                        {ADJ_ROLE_CODES.map((rc) => {
                          const lv = levels.find((l) => l.default_role_code === rc);
                          return (
                            <option key={rc} value={rc}>
                              {lv ? `${lv.role_display_label} (${rc}) — ${lv.level_name} (L${lv.level_number})` : rc}
                            </option>
                          );
                        })}
                      </select>
                    )}
                  </label>
                </div>
              </div>

              <div className="flex items-start gap-1.5 text-[11px] text-blue-600">
                <span className="font-bold shrink-0">ℹ</span>
                <span>{t("approval_rule.priority_hint")}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <button type="button" onClick={addRule}
        className="w-full py-2 border-2 border-dashed border-gray-300 text-gray-500 text-sm rounded-xl hover:border-emerald-400 hover:text-emerald-600">
        + {t("approval_rule.add_rule")}
      </button>

      <p className="text-xs text-gray-400 italic">{t("approval_rule.adj_rules_note")}</p>

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}
      {saveOk && <p className="text-sm text-emerald-600 font-medium">✓ {t("approval_rule.save")}</p>}
      <button type="button" onClick={() => void save()} disabled={saving}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded hover:bg-blue-700 disabled:opacity-50">
        {saving ? t("common.saving") : t("approval_rule.save")}
      </button>
    </div>
  );
}

interface ApprovalStepLocal { sequence: number; position_id: string; position_title: string; location: string; mode: string; sla_hours: number | null }
interface ApprovalRuleLocal {
  id: string;
  source_level: number | null; destination_level: number | null;
  quantity_min: number; quantity_max: number | null;
  value_min: number; value_max: number | null;
  threshold_type: "QUANTITY" | "VALUE" | "EITHER" | "BOTH";
  priority: number;
  steps: ApprovalStepLocal[];
}

const LOCATION_OPTIONS = [
  { v: "SOURCE",      l: "approval_rule.source_node" },
  { v: "DESTINATION", l: "approval_rule.dest_node" },
  { v: "TENANT_WIDE", l: "approval_rule.tenant_wide" },
];
const MODE_OPTIONS = [
  { v: "any",        l: "approval_rule.mode_any" },
  { v: "SEQUENTIAL", l: "approval_rule.mode_all" },
];

function ApprovalRulesV2Tab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [subTab, setSubTab] = useState<"transfer" | "adjustment">("transfer");
  const [activeType, setActiveType] = useState<string | null>(null);
  const [rules, setRules] = useState<Record<string, ApprovalRuleLocal[]>>({});
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const { data: levels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn:  () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });
  const { data: ttypes = [], isLoading: ttLoading } = useQuery<TransferTypeConfig[]>({
    queryKey: ["transfer-types", tenantId],
    queryFn:  () => api.get<TransferTypeConfig[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    staleTime: 0,
    enabled:  !!tenantId,
  });
  const { data: posGroups = [] } = useQuery<NodePositionGroup[]>({
    queryKey: ["positions", tenantId],
    queryFn:  () => api.get<NodePositionGroup[]>(`/api/v1/tenants/${tenantId}/positions`),
    staleTime: 30_000,
    enabled:  !!tenantId,
  });
  const { data: savedRules = [], isLoading: rulesLoading } = useQuery<Array<{ id: string; transfer_type_config_id: string; source_level: number | null; destination_level: number | null; quantity_min: number; quantity_max: number | null; value_min: number; value_max: number | null; threshold_type: string; approval_steps: ApprovalStepLocal[]; priority: number; is_active: boolean }>>({
    queryKey: ["transfer-approval-rules", tenantId],
    queryFn:  () => api.get(`/api/v1/tenants/${tenantId}/transfer-approval-rules`),
    staleTime: 0,
    enabled:  !!tenantId,
  });

  const activeTypes = ttypes.filter((t) => t.is_active);
  const allPositions = posGroups.flatMap((g) => g.positions);

  // Init active tab and load saved rules
  if (!activeType && activeTypes.length > 0) setActiveType(activeTypes[0]?.id ?? null);

  function getRules(typeId: string): ApprovalRuleLocal[] {
    if (rules[typeId]) return rules[typeId];
    const saved = savedRules.filter((r) => r.transfer_type_config_id === typeId);
    return saved.map((r, idx) => ({
      id: r.id,
      source_level: r.source_level, destination_level: r.destination_level,
      quantity_min: r.quantity_min, quantity_max: r.quantity_max,
      value_min: r.value_min, value_max: r.value_max,
      threshold_type: (r.threshold_type as "QUANTITY" | "VALUE" | "EITHER" | "BOTH") ?? "QUANTITY",
      priority: r.priority ?? idx,
      steps: r.approval_steps ?? [],
    }));
  }

  function setTypeRules(typeId: string, fn: (prev: ApprovalRuleLocal[]) => ApprovalRuleLocal[]) {
    setRules((prev) => ({ ...prev, [typeId]: fn(prev[typeId] ?? getRules(typeId)) }));
  }

  function addRule(typeId: string) {
    setTypeRules(typeId, (prev) => [...prev, {
      id: `local_${Date.now()}`, source_level: null, destination_level: null,
      quantity_min: 0, quantity_max: null, value_min: 0, value_max: null,
      threshold_type: "QUANTITY", priority: prev.length + 1, steps: [],
    }]);
  }
  function removeRule(typeId: string, idx: number) {
    setTypeRules(typeId, (prev) => prev.filter((_, i) => i !== idx));
  }
  function updateRule(typeId: string, idx: number, patch: Partial<ApprovalRuleLocal>) {
    setTypeRules(typeId, (prev) => prev.map((r, i) => i === idx ? { ...r, ...patch } : r));
  }
  function addStep(typeId: string, ruleIdx: number) {
    setTypeRules(typeId, (prev) => prev.map((r, i) => {
      if (i !== ruleIdx) return r;
      return { ...r, steps: [...r.steps, { sequence: r.steps.length + 1, position_id: "", position_title: "", location: "TENANT_WIDE", mode: "any", sla_hours: 24 }] };
    }));
  }
  function updateStep(typeId: string, ruleIdx: number, stepIdx: number, patch: Partial<ApprovalStepLocal>) {
    setTypeRules(typeId, (prev) => prev.map((r, i) => {
      if (i !== ruleIdx) return r;
      return { ...r, steps: r.steps.map((s, j) => j === stepIdx ? { ...s, ...patch } : s) };
    }));
  }
  function removeStep(typeId: string, ruleIdx: number, stepIdx: number) {
    setTypeRules(typeId, (prev) => prev.map((r, i) => {
      if (i !== ruleIdx) return r;
      return { ...r, steps: r.steps.filter((_, j) => j !== stepIdx).map((s, j) => ({ ...s, sequence: j + 1 })) };
    }));
  }

  async function save() {
    setSaving(true); setSaveOk(false); setSaveErr(null);
    try {
      const body = activeTypes.flatMap((tt) => {
        const typeRules = rules[tt.id] ?? getRules(tt.id);
        return typeRules.map((r, idx) => ({
          transfer_type_config_id: tt.id,
          source_level: r.source_level, destination_level: r.destination_level,
          quantity_min: r.quantity_min, quantity_max: r.quantity_max,
          value_min: r.value_min, value_max: r.value_max,
          threshold_type: r.threshold_type, currency: "ETB",
          approval_steps: r.steps.map((s) => ({
            sequence: s.sequence, position_title: s.position_title || null,
            resolution: s.location, execution_mode: s.mode, sla_hours: s.sla_hours,
          })),
          priority: r.priority ?? idx, is_active: true,
        }));
      });
      await api.put(`/api/v1/tenants/${tenantId}/transfer-approval-rules`, body);
      void qc.invalidateQueries({ queryKey: ["transfer-approval-rules", tenantId] });
      setSaveOk(true);
    } catch (e) { setSaveErr(e instanceof Error ? e.message : t("common.error")); }
    setSaving(false);
  }

  const levelOptions = [{ value: null, label: t("approval_rule.any_level") }, ...levels.map((l) => ({ value: l.level_number, label: `${l.level_name} (L${l.level_number})` }))];
  const currentRules = getRules(activeType ?? "");

  return (
    <div className="space-y-4">
      {/* Sub-tab nav: Transfer Rules | Adjustment Rules */}
      <div className="flex border-b border-gray-200">
        <button type="button" onClick={() => setSubTab("transfer")}
          className={`px-4 py-2 text-sm font-medium transition-all ${subTab === "transfer" ? "border-b-2 border-emerald-600 text-emerald-700" : "text-gray-500 hover:text-gray-700"}`}>
          {t("approval_rule.transfer_rules_tab")}
        </button>
        <button type="button" onClick={() => setSubTab("adjustment")}
          className={`px-4 py-2 text-sm font-medium transition-all ${subTab === "adjustment" ? "border-b-2 border-emerald-600 text-emerald-700" : "text-gray-500 hover:text-gray-700"}`}>
          {t("approval_rule.adj_rules_tab")}
        </button>
      </div>

      {subTab === "transfer" && (
        <>
          {(ttLoading || rulesLoading) && <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>}
          {!ttLoading && !rulesLoading && activeTypes.length === 0 && (
            <p className="text-sm text-gray-400 py-8 text-center">No active transfer types. Configure them in the Transfer Types tab first.</p>
          )}
          {!ttLoading && !rulesLoading && activeTypes.length > 0 && (<>
            {/* Type tabs */}
            <div className="flex border-b border-gray-200">
              {activeTypes.map((tt) => (
                <button key={tt.id} type="button"
                  onClick={() => setActiveType(tt.id)}
                  className={`px-4 py-2 text-sm font-medium transition-all ${activeType === tt.id ? "border-b-2 border-emerald-600 text-emerald-700" : "text-gray-500 hover:text-gray-700"}`}>
                  {tt.display_name}
                </button>
              ))}
            </div>

      {/* Rules for active type */}
      {activeType && (
        <div className="space-y-3">
          {/* Orientation hint — clarifies which side is "source" to prevent
              the common misconfiguration of inverted source/destination levels */}
          {(() => {
            const meta = activeTypes.find((tt) => tt.id === activeType);
            const ut   = meta?.underlying_type?.toUpperCase() ?? "";
            const hint = ut === "PULL"
              ? t("approval_rule.pull_orientation_hint")
              : ut === "PUSH"
              ? t("approval_rule.push_orientation_hint")
              : t("approval_rule.sister_orientation_hint");
            return (
              <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-blue-50 border border-blue-100 text-[11px] text-blue-700 leading-snug">
                <span className="shrink-0 font-bold mt-0.5">ℹ</span>
                <span>{hint}</span>
              </div>
            );
          })()}

          {currentRules.map((rule, rIdx) => (
            <div key={rule.id} className="border border-gray-200 rounded-xl p-4 bg-white space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-bold uppercase text-gray-500">Rule {rIdx + 1}</span>
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-1.5">
                      <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
                        {t("approval_rule.priority_label")}
                      </label>
                      <input
                        type="number" min={0}
                        value={rule.priority}
                        onChange={(e) => updateRule(activeType, rIdx, { priority: Number(e.target.value) })}
                        className="w-14 border border-gray-200 rounded px-1.5 py-0.5 text-xs text-center focus:border-emerald-400 focus:outline-none"
                      />
                    </div>
                    <p className="text-[10px] text-gray-400 leading-tight">{t("approval_rule.priority_hint")}</p>
                  </div>
                </div>
                <button type="button" onClick={() => removeRule(activeType, rIdx)}
                  className="w-6 h-6 flex items-center justify-center text-xs rounded border border-red-200 text-red-500 hover:bg-red-50">🗑</button>
              </div>

              {/* Level selectors */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-gray-600 mb-1">{t("approval_rule.from_level")}</label>
                  <select value={rule.source_level ?? ""} onChange={(e) => updateRule(activeType, rIdx, { source_level: e.target.value ? Number(e.target.value) : null })}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
                    {levelOptions.map((o) => <option key={String(o.value)} value={o.value ?? ""}>{o.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-600 mb-1">{t("approval_rule.to_level")}</label>
                  <select value={rule.destination_level ?? ""} onChange={(e) => updateRule(activeType, rIdx, { destination_level: e.target.value ? Number(e.target.value) : null })}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
                    {levelOptions.map((o) => <option key={String(o.value)} value={o.value ?? ""}>{o.label}</option>)}
                  </select>
                </div>
              </div>

              {/* Threshold */}
              <div>
                <p className="text-xs font-bold text-gray-600 mb-1">{t("approval_rule.threshold_type")}</p>
                <div className="flex gap-3 flex-wrap">
                  {(["QUANTITY","VALUE","EITHER","BOTH"] as const).map((tt2) => (
                    <label key={tt2} className="flex items-center gap-1 text-xs cursor-pointer">
                      <input type="radio" name={`thresh-${rule.id}`} value={tt2} checked={rule.threshold_type === tt2}
                        onChange={() => updateRule(activeType, rIdx, { threshold_type: tt2 })} className="accent-emerald-600" />
                      {t(`approval_rule.${tt2.toLowerCase()}`)}
                    </label>
                  ))}
                </div>
                {(rule.threshold_type === "QUANTITY" || rule.threshold_type === "EITHER" || rule.threshold_type === "BOTH") && (
                  <div className="flex items-center gap-2 mt-2">
                    <input type="number" min={0} value={rule.quantity_min} placeholder="min" onChange={(e) => updateRule(activeType, rIdx, { quantity_min: Number(e.target.value) })}
                      className="w-24 border border-gray-300 rounded px-2 py-1 text-xs" />
                    <span className="text-xs text-gray-400">to</span>
                    <input type="number" min={0} value={rule.quantity_max ?? ""} placeholder="unlimited" onChange={(e) => updateRule(activeType, rIdx, { quantity_max: e.target.value ? Number(e.target.value) : null })}
                      className="w-28 border border-gray-300 rounded px-2 py-1 text-xs" />
                    <span className="text-xs text-gray-400">units</span>
                  </div>
                )}
              </div>

              {/* Approval steps */}
              <div>
                <p className="text-xs font-bold text-gray-600 mb-2">Approval Steps</p>
                <div className="space-y-2">
                  {rule.steps.map((step, sIdx) => (
                    <div key={sIdx} className="flex items-center gap-2 flex-wrap bg-gray-50 rounded p-2">
                      <span className="text-xs text-gray-400 shrink-0">{step.sequence}.</span>
                      <select value={step.position_id} onChange={(e) => {
                        const pos = allPositions.find((p) => p.id === e.target.value);
                        updateStep(activeType, rIdx, sIdx, { position_id: e.target.value, position_title: pos?.title ?? "" });
                      }} className="flex-1 min-w-0 border border-gray-300 rounded px-2 py-1 text-xs bg-white">
                        <option value="">— {t("approval_rule.position")} —</option>
                        {allPositions.map((p) => <option key={p.id} value={p.id}>{p.title} ({p.role_code})</option>)}
                      </select>
                      <select value={step.location} onChange={(e) => updateStep(activeType, rIdx, sIdx, { location: e.target.value })}
                        className="border border-gray-300 rounded px-2 py-1 text-xs bg-white">
                        {LOCATION_OPTIONS.map((o) => <option key={o.v} value={o.v}>{t(o.l)}</option>)}
                      </select>
                      <select value={step.mode} onChange={(e) => updateStep(activeType, rIdx, sIdx, { mode: e.target.value })}
                        title={t("approval_rule.mode_note")}
                        className="border border-gray-300 rounded px-2 py-1 text-xs bg-white">
                        {MODE_OPTIONS.map((o) => <option key={o.v} value={o.v}>{t(o.l)}</option>)}
                      </select>
                      <input type="number" min={1} value={step.sla_hours ?? ""} placeholder={t("approval_rule.sla")} onChange={(e) => updateStep(activeType, rIdx, sIdx, { sla_hours: e.target.value ? Number(e.target.value) : null })}
                        className="w-16 border border-gray-300 rounded px-2 py-1 text-xs" />
                      <button type="button" onClick={() => removeStep(activeType, rIdx, sIdx)}
                        className="w-5 h-5 flex items-center justify-center text-xs rounded border border-red-200 text-red-400 hover:bg-red-50">×</button>
                    </div>
                  ))}
                </div>
                <button type="button" onClick={() => addStep(activeType, rIdx)}
                  className="mt-2 px-2 py-1 text-xs border border-dashed border-emerald-400 text-emerald-700 rounded hover:bg-emerald-50">
                  + {t("approval_rule.add_step")}
                </button>
              </div>
            </div>
          ))}

          <button type="button" onClick={() => addRule(activeType)}
            className="w-full py-2 border-2 border-dashed border-gray-300 text-gray-500 text-sm rounded-xl hover:border-emerald-400 hover:text-emerald-600">
            + {t("approval_rule.add_rule")}
          </button>
        </div>
      )}

          {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}
          {saveOk && <p className="text-sm text-emerald-600 font-medium">✓ Saved</p>}
          <button type="button" onClick={() => void save()} disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? t("common.saving") : t("approval_rule.save")}
          </button>
        </>)}
        </>
      )}

      {subTab === "adjustment" && <AdjustmentRulesSection tenantId={tenantId} />}
    </div>
  );
}

/* ── Tab 6: Personnel ───────────────────────────────────────────────────────── */

interface PositionAssignment { assignment_id: string; position_id: string; title: string; role_code: string; node_id: string; node_name: string; level_number: number; assignment_type: string; valid_from: string | null; valid_until: string | null }
interface UserWithPositions { id: string; email: string; name: string; primary_position: PositionAssignment | null; acting_positions: PositionAssignment[]; is_active: boolean; must_reset_password: boolean }

function PersonnelV2Tab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [uName, setUName]           = useState("");
  const [uEmail, setUEmail]         = useState("");
  const [uPass, setUPass]           = useState("");
  const [uPosId, setUPosId]         = useState("");
  const [formErr, setFormErr]       = useState<string | null>(null);
  const [saving, setSaving]         = useState(false);

  const { data: users = [], isLoading } = useQuery<UserWithPositions[]>({
    queryKey: ["personnel-v2", tenantId],
    queryFn:  () => api.get<UserWithPositions[]>(`/api/v1/tenants/${tenantId}/users`),
    staleTime: 0,
    enabled:  !!tenantId,
  });
  const { data: posGroups = [] } = useQuery<NodePositionGroup[]>({
    queryKey: ["positions", tenantId],
    queryFn:  () => api.get<NodePositionGroup[]>(`/api/v1/tenants/${tenantId}/positions`),
    staleTime: 30_000,
    enabled:  !!tenantId,
  });

  const allPositions = posGroups.flatMap((g) => g.positions);

  async function createUser() {
    if (!uName.trim() || !uEmail.trim() || !uPass.trim()) { setFormErr("Name, email and password are required."); return; }
    setSaving(true); setFormErr(null);
    try {
      await api.post(`/api/v1/tenants/${tenantId}/users`, {
        name: uName.trim(), email: uEmail.trim(), password: uPass,
        position_id: uPosId || null,
      });
      void qc.invalidateQueries({ queryKey: ["personnel-v2", tenantId] });
      setShowCreate(false); setUName(""); setUEmail(""); setUPass(""); setUPosId("");
    } catch (e) { setFormErr(e instanceof Error ? e.message : t("common.error")); }
    setSaving(false);
  }

  async function toggleActive(userId: string, currentlyActive: boolean) {
    if (!tenantId) return;
    const path = currentlyActive ? "deactivate" : "reactivate";
    try {
      await api.patch(`/api/v1/tenants/${tenantId}/users/${userId}/${path}`, {});
      void qc.invalidateQueries({ queryKey: ["personnel-v2", tenantId] });
    } catch (e) { alert(e instanceof Error ? e.message : t("common.error")); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">{t("wizard.personnel_tab")}</h3>
        {!showCreate && (
          <button type="button" onClick={() => setShowCreate(true)}
            className="px-3 py-1 bg-emerald-600 text-white text-xs font-semibold rounded hover:bg-emerald-700">
            + {t("personnel.add_user")}
          </button>
        )}
      </div>

      {showCreate && (
        <div className="border border-emerald-300 rounded-xl p-4 bg-emerald-50 space-y-3">
          <p className="text-xs font-bold uppercase text-emerald-700">{t("personnel.add_user")}</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">{t("personnel.full_name")} *</label>
              <input value={uName} onChange={(e) => setUName(e.target.value)} className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm" placeholder="Full name" />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">{t("personnel.email")} *</label>
              <input type="email" value={uEmail} onChange={(e) => setUEmail(e.target.value)} className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm" placeholder="email@company.com" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">Temporary Password *</label>
              <input type="password" value={uPass} onChange={(e) => setUPass(e.target.value)} className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">{t("personnel.primary_facility")} (optional)</label>
              <select value={uPosId} onChange={(e) => setUPosId(e.target.value)}
                className="w-full border border-gray-300 rounded px-2.5 py-1.5 text-sm bg-white">
                <option value="">— assign later —</option>
                {allPositions.map((p) => <option key={p.id} value={p.id}>{p.title} · {posGroups.find((g) => g.positions.some((pos) => pos.id === p.id))?.node_name ?? ""}</option>)}
              </select>
            </div>
          </div>
          {formErr && <p className="text-xs text-red-600">{formErr}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={() => void createUser()} disabled={saving}
              className="px-3 py-1.5 bg-emerald-600 text-white text-xs font-semibold rounded hover:bg-emerald-700 disabled:opacity-50">
              {saving ? t("common.saving") : t("personnel.create_user")}
            </button>
            <button type="button" onClick={() => { setShowCreate(false); setFormErr(null); }}
              className="px-3 py-1.5 border border-gray-300 text-gray-600 text-xs rounded hover:bg-gray-50">
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      {isLoading ? <p className="text-sm text-gray-400">{t("common.loading")}</p> : (
        <div className="space-y-2">
          {users.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">{t("personnel.no_users_found")}</p>}
          {users.map((u) => (
            <div key={u.id} className={`border rounded-xl p-3 flex items-start justify-between gap-3 ${u.is_active ? "border-gray-200 bg-white" : "border-gray-100 bg-gray-50 opacity-60"}`}>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-gray-800 m-0">{u.name} {u.must_reset_password && <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full ml-1">pwd reset</span>}</p>
                <p className="text-xs text-gray-500 m-0">{u.email}</p>
                {u.primary_position ? (
                  <p className="text-xs text-emerald-700 m-0 mt-0.5">✓ {u.primary_position.title} · {u.primary_position.node_name}</p>
                ) : (
                  <p className="text-xs text-amber-600 m-0 mt-0.5">⚠ No position assigned</p>
                )}
                {u.acting_positions.length > 0 && (
                  <p className="text-xs text-gray-400 m-0">{u.acting_positions.length} acting assignment{u.acting_positions.length > 1 ? "s" : ""}</p>
                )}
              </div>
              <button type="button" onClick={() => void toggleActive(u.id, u.is_active)}
                disabled={!tenantId || isLoading}
                className={`px-2.5 py-1 text-xs rounded border font-medium shrink-0 disabled:opacity-40 disabled:cursor-not-allowed ${u.is_active ? "border-red-200 text-red-600 hover:bg-red-50" : "border-emerald-200 text-emerald-600 hover:bg-emerald-50"}`}>
                {u.is_active ? t("personnel.deactivate") : t("personnel.reactivate")}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────────── */

type TabId = "levels" | "tree" | "positions" | "transfer-types" | "approval" | "personnel";

export default function OrgSetupPage() {
  const { org } = useParams() as { org: string };
  const [activeTab, setActiveTab] = useState<TabId>("levels");

  // All hierarchy/node endpoints require a UUID — resolve it from the slug (or UUID) in the URL
  const { data: tenantMeta, isLoading: metaLoading, isError: metaError } = useQuery<{ id: string; name: string }>({
    queryKey: ["tenant-meta", org],
    queryFn: () => api.get<{ id: string; name: string }>(`/api/v1/tenants/${org}`),
    staleTime: 300_000,
    retry: false,
  });

  const tenantId = tenantMeta?.id ?? "";

  if (metaLoading) {
    return (
      <div className="p-8 max-w-3xl">
        <p className="text-sm text-gray-400 py-8 text-center">{t("common.loading")}</p>
      </div>
    );
  }

  if (metaError || !tenantId) {
    return (
      <div className="p-8 max-w-3xl">
        <p className="text-sm text-red-500 py-8 text-center">{t("org_setup.tenant_not_found")}</p>
      </div>
    );
  }

  const tabCls = (id: TabId) =>
    `px-5 py-2.5 text-sm font-semibold rounded-t-lg border-b-2 transition-all ${
      activeTab === id
        ? "border-emerald-600 text-emerald-700 bg-white"
        : "border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50"
    }`;

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 m-0">{t("org_setup.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{t("org_setup.subtitle")}</p>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap border-b border-gray-200 mb-6 gap-0.5">
        <button type="button" className={tabCls("levels")}         onClick={() => setActiveTab("levels")}>Organisation Levels</button>
        <button type="button" className={tabCls("tree")}           onClick={() => setActiveTab("tree")}>Organisation Tree</button>
        <button type="button" className={tabCls("positions")}      onClick={() => setActiveTab("positions")}>{t("wizard.positions_tab")}</button>
        <button type="button" className={tabCls("transfer-types")} onClick={() => setActiveTab("transfer-types")}>{t("wizard.transfer_types_tab")}</button>
        <button type="button" className={tabCls("approval")}       onClick={() => setActiveTab("approval")}>{t("wizard.approval_rules_tab")}</button>
        <button type="button" className={tabCls("personnel")}      onClick={() => setActiveTab("personnel")}>{t("wizard.personnel_tab")}</button>
      </div>

      {activeTab === "levels"         && <LevelsTab          tenantId={tenantId} />}
      {activeTab === "tree"           && <TreeTab             tenantId={tenantId} />}
      {activeTab === "positions"      && <PositionsTab        tenantId={tenantId} />}
      {activeTab === "transfer-types" && <TransferTypesTab    tenantId={tenantId} />}
      {activeTab === "approval"       && <ApprovalRulesV2Tab  tenantId={tenantId} />}
      {activeTab === "personnel"      && <PersonnelV2Tab      tenantId={tenantId} />}
    </div>
  );
}
