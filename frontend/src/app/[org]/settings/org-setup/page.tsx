"use client";

import { useState, useCallback, Fragment } from "react";
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

function mkTier(role = ""): ApprovalTier {
  return {
    id: `${Date.now()}_${Math.random()}`,
    max_quantity: null,
    approver_role: role,
    auto_approve: false,
    notify_above: false,
    notify_all: false,
  };
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
  for (let i = 0; i < tiers.length - 1; i++) {
    const cur = tiers[i];
    const nxt = tiers[i + 1];
    if (!cur || !nxt) continue;
    if (cur.max_quantity === null) {
      return `Tier ${i + 1}: enter an upper bound — only the last tier can be unlimited.`;
    }
    if (!cur.approver_role) return `Tier ${i + 1}: approver required.`;
    if (nxt.max_quantity !== null && cur.max_quantity >= nxt.max_quantity) {
      return `Upper bounds must be ascending: tier ${i + 1} (${cur.max_quantity.toLocaleString()} units) must be less than tier ${i + 2} (${nxt.max_quantity.toLocaleString()} units).`;
    }
  }
  if (!last.approver_role) return "Last tier: approver required.";
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

  return (
    <div className="space-y-3">
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
            {tiers.map((tier, i) => (
              <Fragment key={tier.id}>
                <tr className="hover:bg-gray-50">
                  <td className="px-3 py-2.5 text-gray-400 font-mono text-xs">{i + 1}</td>
                  <td className="px-3 py-2.5">
                    {i === tiers.length - 1 ? (
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
                  <td className="px-3 py-2.5">
                    {tiers.length > 1 && (
                      <button
                        type="button"
                        onClick={() => deleteTier(i)}
                        className="text-red-400 hover:text-red-600 text-base leading-none"
                        aria-label="Remove tier"
                      >
                        🗑
                      </button>
                    )}
                  </td>
                </tr>
                {tier.auto_approve && (
                  <tr key={`${tier.id}-notify`}>
                    <td></td>
                    <td colSpan={3} className="px-3 py-2 bg-blue-50">
                      <div className="flex items-center gap-4 text-xs text-gray-600 pl-2 border-l-2 border-blue-300">
                        <span className="font-medium">Notify:</span>
                        <label className="flex items-center gap-1 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={tier.notify_above}
                            onChange={(e) => updateTier(i, { notify_above: e.target.checked })}
                            className="rounded"
                          />
                          {t("approval.notify_above")}
                        </label>
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
            ))}
          </tbody>
        </table>
      </div>
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
  const [gapError, setGapError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const { data: levels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["hierarchy-config", tenantId],
    queryFn: () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    staleTime: 30_000,
  });

  const { data: savedRules = [], isLoading: rulesLoading } = useQuery<SavedApprovalRule[]>({
    queryKey: ["approval-rules", tenantId],
    queryFn: () => api.get<SavedApprovalRule[]>(`/api/v1/tenants/${tenantId}/approval-rules`),
    staleTime: 30_000,
  });

  if (!initialized && !rulesLoading) {
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
    }
    setInitialized(true);
  }

  function buildRules(): SavedApprovalRule[] {
    if (simpleMode) {
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

  function handleSave() {
    const tierSets = simpleMode
      ? [simpleTiers]
      : Object.values(customTiers);
    for (const ts of tierSets) {
      const err = validateTiers(ts);
      if (err) { setGapError(err); return; }
    }
    setGapError(null);
    saveMutation.mutate(buildRules());
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
    mutationFn: (rules: SavedApprovalRule[]) =>
      api.put(`/api/v1/tenants/${tenantId}/approval-rules`, { rules }),
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
          Define who approves each type of transaction based on quantity
        </p>
      </div>

      {/* Mode selector */}
      <div className="flex gap-6">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="approval-mode"
            checked={simpleMode}
            onChange={() => setSimpleMode(true)}
            className="accent-emerald-600"
          />
          <span className="text-sm text-gray-700">{t("approval.simple_mode")}</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="approval-mode"
            checked={!simpleMode}
            onChange={() => setSimpleMode(false)}
            className="accent-emerald-600"
          />
          <span className="text-sm text-gray-700">{t("approval.custom_mode")}</span>
        </label>
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
              SISTER transfers share these tiers with PULL
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
      {saveOk  && <p className="text-sm text-emerald-600 font-medium">{t("approval_rules.saved")}</p>}

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

/* ── Main page ─────────────────────────────────────────────────────────────── */

type TabId = "levels" | "tree" | "approval";

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
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 m-0">{t("org_setup.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{t("org_setup.subtitle")}</p>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 mb-6">
        <button type="button" className={tabCls("levels")} onClick={() => setActiveTab("levels")}>
          Organisation Levels
        </button>
        <button type="button" className={tabCls("tree")} onClick={() => setActiveTab("tree")}>
          Organisation Tree
        </button>
        <button type="button" className={tabCls("approval")} onClick={() => setActiveTab("approval")}>
          Approval Rules
        </button>
      </div>

      {activeTab === "levels"   && <LevelsTab        tenantId={tenantId} />}
      {activeTab === "tree"     && <TreeTab           tenantId={tenantId} />}
      {activeTab === "approval" && <ApprovalRulesTab  tenantId={tenantId} />}
    </div>
  );
}
