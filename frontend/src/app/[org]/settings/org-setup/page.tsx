"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { getSession } from "@/lib/demo-auth";

/* ── Types ─────────────────────────────────────────────────────────────────── */

interface HierarchyLevel {
  level_number: number;
  label: string;
  code: string;
  is_mandatory: boolean;
  default_role_code: string | null;
}

interface OrgNode {
  id: string;
  name: string;
  code: string;
  hierarchy_level: number;
  parent_node_id: string | null;
  is_stock_holding: boolean;
  is_active: boolean;
  children: OrgNode[];
}

interface SupplyRoute {
  source_node_id: string;
  is_preferred: boolean;
}

/* ── Wizard step definitions ───────────────────────────────────────────────── */

const STEPS = [
  { id: 1, label: "Structure" },
  { id: 2, label: "Level Config" },
  { id: 3, label: "Build Tree" },
  { id: 4, label: "Supply Routes" },
  { id: 5, label: "Review & Confirm" },
] as const;

type StepId = (typeof STEPS)[number]["id"];

const ROLE_OPTIONS = [
  { code: "NM", label: "National Manager" },
  { code: "RM", label: "Regional Manager" },
  { code: "LM", label: "Logistics Manager" },
  { code: "WM", label: "Warehouse Manager" },
  { code: "TA", label: "Tenant Admin" },
];

/* ── Step 1: Structure ────────────────────────────────────────────────────── */

interface Step1State {
  levelCount: number;
}

function StructureStep({
  state,
  onChange,
}: {
  state: Step1State;
  onChange: (s: Step1State) => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {t("org_setup.structure_title")}
        </h3>
        <p className="text-sm text-gray-500">
          {t("org_setup.structure_desc")}
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t("org_setup.level_count")}
        </label>
        <div className="flex gap-3">
          {[2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => onChange({ levelCount: n })}
              className={`w-14 h-14 rounded-lg border-2 text-lg font-bold transition-all ${
                state.levelCount === n
                  ? "border-emerald-600 bg-emerald-50 text-emerald-700"
                  : "border-gray-200 bg-white text-gray-600 hover:border-gray-400"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          {t("org_setup.level_count_hint")}
        </p>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
        <p className="text-xs font-semibold text-amber-800 mb-1">
          {t("org_setup.structure_note_title")}
        </p>
        <p className="text-xs text-amber-700">
          {t("org_setup.structure_note_body")}
        </p>
      </div>
    </div>
  );
}

/* ── Step 2: Level Config ─────────────────────────────────────────────────── */

function LevelConfigStep({
  levels,
  onChange,
}: {
  levels: HierarchyLevel[];
  onChange: (levels: HierarchyLevel[]) => void;
}) {
  function update(idx: number, patch: Partial<HierarchyLevel>) {
    const next = levels.map((l, i) => (i === idx ? { ...l, ...patch } : l));
    onChange(next);
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {t("org_setup.level_config_title")}
        </h3>
        <p className="text-sm text-gray-500">
          {t("org_setup.level_config_desc")}
        </p>
      </div>

      <div className="space-y-3">
        {levels.map((lv, idx) => (
          <div
            key={lv.level_number}
            className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3"
          >
            <div className="flex items-center gap-2">
              <span className="w-7 h-7 rounded-full bg-emerald-600 text-white text-xs font-bold flex items-center justify-center shrink-0">
                {lv.level_number}
              </span>
              <span className="text-sm font-semibold text-gray-700">
                {t("org_setup.level")} {lv.level_number}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  {t("org_setup.level_label")} *
                </label>
                <input
                  type="text"
                  value={lv.label}
                  onChange={(e) => update(idx, { label: e.target.value })}
                  placeholder={`e.g. ${["Main Factory", "Region", "Warehouse", "Sub-Warehouse", "Counter"][idx] ?? "Level " + lv.level_number}`}
                  className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  {t("org_setup.level_code")} *
                </label>
                <input
                  type="text"
                  value={lv.code}
                  onChange={(e) => update(idx, { code: e.target.value.toUpperCase() })}
                  placeholder={["MAIN", "REG", "WH", "SUB", "CTR"][idx] ?? ""}
                  maxLength={20}
                  className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500 uppercase"
                />
              </div>
            </div>

            <div className="flex items-center gap-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={lv.is_mandatory}
                  onChange={(e) => update(idx, { is_mandatory: e.target.checked })}
                  className="w-4 h-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                />
                <span className="text-xs text-gray-600">{t("org_setup.mandatory")}</span>
              </label>

              <div className="flex items-center gap-2">
                <label className="text-xs font-medium text-gray-600">
                  {t("org_setup.default_role")}
                </label>
                <select
                  value={lv.default_role_code ?? ""}
                  onChange={(e) =>
                    update(idx, { default_role_code: e.target.value || null })
                  }
                  className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                >
                  <option value="">{t("org_setup.no_default_role")}</option>
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.code} — {r.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Step 3: Build Tree ───────────────────────────────────────────────────── */

interface NewNodeForm {
  name: string;
  code: string;
  hierarchy_level: number;
  parent_node_id: string;
  is_stock_holding: boolean;
}

const EMPTY_NODE: NewNodeForm = {
  name: "",
  code: "",
  hierarchy_level: 1,
  parent_node_id: "",
  is_stock_holding: true,
};

function flattenNodes(nodes: OrgNode[]): OrgNode[] {
  const out: OrgNode[] = [];
  function visit(list: OrgNode[]) {
    for (const n of list) {
      out.push(n);
      visit(n.children);
    }
  }
  visit(nodes);
  return out;
}

function BuildTreeStep({
  tenantId,
  levels,
  nodes,
  onNodesChange,
}: {
  tenantId: string;
  levels: HierarchyLevel[];
  nodes: OrgNode[];
  onNodesChange: (nodes: OrgNode[]) => void;
}) {
  const [form, setForm] = useState<NewNodeForm>({ ...EMPTY_NODE, hierarchy_level: levels[0]?.level_number ?? 1 });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const flat = flattenNodes(nodes);

  async function addNode() {
    if (!form.name.trim() || !form.code.trim()) {
      setError(t("org_setup.node_name_code_required"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await api.post<OrgNode>(`/api/v1/tenants/${tenantId}/nodes`, {
        name: form.name.trim(),
        level_number: form.hierarchy_level,
        parent_node_id: form.parent_node_id || null,
        is_stock_holding: form.is_stock_holding,
      });
      // Refresh nodes from created — fetch full tree
      const tree = await api.get<OrgNode[]>(`/api/v1/tenants/${tenantId}/nodes`);
      onNodesChange(tree);
      setForm({ ...EMPTY_NODE, hierarchy_level: form.hierarchy_level });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  function renderTree(list: OrgNode[], depth = 0): React.ReactNode {
    return list.map((node) => (
      <div key={node.id}>
        <div
          className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${
            node.is_stock_holding ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-gray-50"
          }`}
          style={{ marginLeft: `${depth * 20}px` }}
        >
          <span className="text-sm">{node.is_stock_holding ? "🏭" : "📋"}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 m-0 truncate">{node.name}</p>
            <p className="text-xs text-gray-400 m-0">
              {node.code} · L{node.hierarchy_level}
              {!node.is_stock_holding && (
                <span className="ml-1 text-amber-600 font-medium">no stock</span>
              )}
            </p>
          </div>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
            node.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"
          }`}>
            {node.is_active ? "ACTIVE" : "INACTIVE"}
          </span>
        </div>
        {node.children.length > 0 && (
          <div className="mt-1">{renderTree(node.children, depth + 1)}</div>
        )}
      </div>
    ));
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {t("org_setup.build_tree_title")}
        </h3>
        <p className="text-sm text-gray-500">{t("org_setup.build_tree_desc")}</p>
      </div>

      {/* Add node form */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
        <p className="text-sm font-semibold text-blue-800">{t("org_setup.add_node")}</p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {t("org_setup.node_name")} *
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder={t("org_setup.node_name_placeholder")}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {t("org_setup.node_code")} *
            </label>
            <input
              type="text"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value.toUpperCase() }))}
              placeholder="WH-ADDIS"
              maxLength={50}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 uppercase"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {t("org_setup.hierarchy_level")}
            </label>
            <select
              value={form.hierarchy_level}
              onChange={(e) => setForm((f) => ({ ...f, hierarchy_level: Number(e.target.value) }))}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {levels.map((lv) => (
                <option key={lv.level_number} value={lv.level_number}>
                  L{lv.level_number} — {lv.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {t("org_setup.parent_node")}
            </label>
            <select
              value={form.parent_node_id}
              onChange={(e) => setForm((f) => ({ ...f, parent_node_id: e.target.value }))}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">{t("org_setup.no_parent")}</option>
              {flat.map((n) => (
                <option key={n.id} value={n.id}>
                  L{n.hierarchy_level} — {n.name} ({n.code})
                </option>
              ))}
            </select>
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_stock_holding}
            onChange={(e) => setForm((f) => ({ ...f, is_stock_holding: e.target.checked }))}
            className="w-4 h-4 rounded border-gray-300 text-blue-600"
          />
          <span className="text-xs text-gray-700">{t("org_setup.is_stock_holding")}</span>
          <span className="text-xs text-gray-400">({t("org_setup.stock_holding_hint")})</span>
        </label>

        {error && <p className="text-xs text-red-600 font-medium">{error}</p>}

        <button
          type="button"
          onClick={() => void addNode()}
          disabled={saving}
          className="px-4 py-1.5 bg-blue-600 text-white text-sm font-semibold rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? t("common.saving") : `+ ${t("org_setup.add_node")}`}
        </button>
      </div>

      {/* Tree view */}
      {nodes.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-6">
          {t("org_setup.no_nodes_yet")}
        </p>
      ) : (
        <div className="space-y-1.5">{renderTree(nodes)}</div>
      )}
    </div>
  );
}

/* ── Step 4: Supply Routes ────────────────────────────────────────────────── */

function SupplyRoutesStep({
  tenantId,
  nodes,
}: {
  tenantId: string;
  nodes: OrgNode[];
}) {
  const flat = flattenNodes(nodes);
  const [selectedNode, setSelectedNode] = useState<string>("");
  const [routes, setRoutes]             = useState<SupplyRoute[]>([{ source_node_id: "", is_preferred: true }]);
  const [saving, setSaving]             = useState(false);
  const [saved, setSaved]               = useState<string[]>([]);
  const [error, setError]               = useState<string | null>(null);

  function addRoute() {
    setRoutes((r) => [...r, { source_node_id: "", is_preferred: false }]);
  }

  function removeRoute(idx: number) {
    setRoutes((r) => r.filter((_, i) => i !== idx));
  }

  function updateRoute(idx: number, patch: Partial<SupplyRoute>) {
    setRoutes((r) => r.map((rt, i) => (i === idx ? { ...rt, ...patch } : rt)));
  }

  async function saveRoutes() {
    if (!selectedNode) { setError(t("org_setup.select_dest_node")); return; }
    const valid = routes.filter((r) => r.source_node_id);
    if (valid.length === 0) { setError(t("org_setup.at_least_one_source")); return; }

    setSaving(true);
    setError(null);
    try {
      await api.post(`/api/v1/tenants/${tenantId}/nodes/${selectedNode}/supply-routes`, {
        routes: valid,
      });
      setSaved((s) => [...s, selectedNode]);
      setSelectedNode("");
      setRoutes([{ source_node_id: "", is_preferred: true }]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {t("org_setup.supply_routes_title")}
        </h3>
        <p className="text-sm text-gray-500">{t("org_setup.supply_routes_desc")}</p>
      </div>

      {saved.length > 0 && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-3 py-2">
          <p className="text-xs font-semibold text-green-700">
            {t("org_setup.routes_saved_for")}: {saved.map((id) => flat.find((n) => n.id === id)?.name ?? id).join(", ")}
          </p>
        </div>
      )}

      <div className="space-y-4 bg-gray-50 border border-gray-200 rounded-lg p-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {t("org_setup.destination_node")} *
          </label>
          <select
            value={selectedNode}
            onChange={(e) => setSelectedNode(e.target.value)}
            className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          >
            <option value="">{t("org_setup.select_destination")}</option>
            {flat.filter((n) => n.is_stock_holding).map((n) => (
              <option key={n.id} value={n.id}>
                L{n.hierarchy_level} — {n.name} ({n.code})
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium text-gray-600">{t("org_setup.supply_sources")}</p>
          {routes.map((rt, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <select
                value={rt.source_node_id}
                onChange={(e) => updateRoute(idx, { source_node_id: e.target.value })}
                className="flex-1 text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">{t("org_setup.select_source")}</option>
                {flat
                  .filter((n) => n.id !== selectedNode && n.is_stock_holding)
                  .map((n) => (
                    <option key={n.id} value={n.id}>
                      L{n.hierarchy_level} — {n.name}
                    </option>
                  ))}
              </select>
              <label className="flex items-center gap-1 text-xs text-gray-600 whitespace-nowrap cursor-pointer">
                <input
                  type="checkbox"
                  checked={rt.is_preferred}
                  onChange={(e) => updateRoute(idx, { is_preferred: e.target.checked })}
                  className="w-3.5 h-3.5"
                />
                {t("org_setup.preferred")}
              </label>
              {routes.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeRoute(idx)}
                  className="text-red-400 hover:text-red-600 text-sm border-0 bg-transparent cursor-pointer"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={addRoute}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium border-0 bg-transparent cursor-pointer"
          >
            + {t("org_setup.add_source")}
          </button>
        </div>

        {error && <p className="text-xs text-red-600 font-medium">{error}</p>}

        <button
          type="button"
          onClick={() => void saveRoutes()}
          disabled={saving}
          className="px-4 py-1.5 bg-emerald-600 text-white text-sm font-semibold rounded-md hover:bg-emerald-700 disabled:opacity-50"
        >
          {saving ? t("common.saving") : t("org_setup.save_routes")}
        </button>
      </div>

      <p className="text-xs text-gray-400">{t("org_setup.supply_routes_skip_hint")}</p>
    </div>
  );
}

/* ── Step 5: Review & Confirm ─────────────────────────────────────────────── */

function ReviewStep({
  levels,
  nodes,
  onConfirm,
  saving,
}: {
  levels: HierarchyLevel[];
  nodes: OrgNode[];
  onConfirm: () => void;
  saving: boolean;
}) {
  const flat = flattenNodes(nodes);

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {t("org_setup.review_title")}
        </h3>
        <p className="text-sm text-gray-500">{t("org_setup.review_desc")}</p>
      </div>

      <div className="bg-gray-50 border border-gray-200 rounded-lg divide-y divide-gray-200">
        <div className="px-4 py-3">
          <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
            {t("org_setup.hierarchy_config")} ({levels.length} {t("org_setup.levels")})
          </p>
          <div className="space-y-1">
            {levels.map((lv) => (
              <div key={lv.level_number} className="flex items-center gap-3 text-sm">
                <span className="w-6 h-6 rounded-full bg-emerald-600 text-white text-xs font-bold flex items-center justify-center">
                  {lv.level_number}
                </span>
                <span className="font-medium text-gray-800">{lv.label}</span>
                <span className="text-gray-400 text-xs">({lv.code})</span>
                {lv.is_mandatory && (
                  <span className="text-[10px] font-bold bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                    mandatory
                  </span>
                )}
                {lv.default_role_code && (
                  <span className="text-[10px] font-bold bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                    default: {lv.default_role_code}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="px-4 py-3">
          <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
            {t("org_setup.org_nodes")} ({flat.length})
          </p>
          {flat.length === 0 ? (
            <p className="text-xs text-gray-400">{t("org_setup.no_nodes_yet")}</p>
          ) : (
            <div className="space-y-1">
              {flat.map((n) => (
                <div key={n.id} className="flex items-center gap-2 text-sm">
                  <span className="text-xs text-gray-400">L{n.hierarchy_level}</span>
                  <span className="font-medium text-gray-800">{n.name}</span>
                  <span className="text-xs text-gray-400">({n.code})</span>
                  {!n.is_stock_holding && (
                    <span className="text-[10px] font-bold bg-gray-100 text-gray-500 px-1 py-0.5 rounded">
                      no stock
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={onConfirm}
        disabled={saving || levels.some((l) => !l.label || !l.code)}
        className="w-full py-2.5 bg-emerald-600 text-white text-sm font-bold rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {saving ? t("common.saving") : t("org_setup.confirm_and_save")}
      </button>

      {levels.some((l) => !l.label || !l.code) && (
        <p className="text-xs text-red-500 text-center">
          {t("org_setup.complete_level_config_first")}
        </p>
      )}
    </div>
  );
}

/* ── Wizard progress bar ──────────────────────────────────────────────────── */

function WizardProgress({ current }: { current: StepId }) {
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((step, idx) => (
        <div key={step.id} className="flex items-center flex-1">
          <div className="flex flex-col items-center shrink-0">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all ${
                step.id < current
                  ? "bg-emerald-600 border-emerald-600 text-white"
                  : step.id === current
                  ? "bg-white border-emerald-600 text-emerald-700"
                  : "bg-white border-gray-300 text-gray-400"
              }`}
            >
              {step.id < current ? "✓" : step.id}
            </div>
            <span
              className={`text-[10px] font-medium mt-1 whitespace-nowrap ${
                step.id === current ? "text-emerald-700" : "text-gray-400"
              }`}
            >
              {step.label}
            </span>
          </div>
          {idx < STEPS.length - 1 && (
            <div
              className={`flex-1 h-0.5 mt-[-14px] mx-1 ${
                step.id < current ? "bg-emerald-600" : "bg-gray-200"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Main wizard page ─────────────────────────────────────────────────────── */

function buildDefaultLevels(count: number): HierarchyLevel[] {
  const defaults = [
    { label: "Main Factory",   code: "MAIN" },
    { label: "Region",         code: "REG"  },
    { label: "Warehouse",      code: "WH"   },
    { label: "Sub-Warehouse",  code: "SUB"  },
    { label: "Counter",        code: "CTR"  },
  ];
  return Array.from({ length: count }, (_, i) => ({
    level_number:      i + 1,
    label:             defaults[i]?.label ?? `Level ${i + 1}`,
    code:              defaults[i]?.code  ?? `L${i + 1}`,
    is_mandatory:      i === 0,
    default_role_code: null,
  }));
}

export default function OrgSetupWizardPage() {
  const { org } = useParams() as { org: string };
  const router  = useRouter();
  const session = getSession();
  const tenantId = session?.tenantId ?? "";

  const [step, setStep]       = useState<StepId>(1);
  const [step1, setStep1]     = useState<Step1State>({ levelCount: 3 });
  const [levels, setLevels]   = useState<HierarchyLevel[]>(() => buildDefaultLevels(3));
  const [nodes, setNodes]     = useState<OrgNode[]>([]);
  const [saving, setSaving]   = useState(false);
  const [done, setDone]       = useState(false);
  const [error, setError]     = useState<string | null>(null);

  // Sync levels when level count changes
  function handleStep1Change(s: Step1State) {
    setStep1(s);
    setLevels((prev) => {
      if (s.levelCount === prev.length) return prev;
      if (s.levelCount > prev.length) {
        const extra = buildDefaultLevels(s.levelCount).slice(prev.length);
        return [...prev, ...extra];
      }
      return prev.slice(0, s.levelCount);
    });
  }

  async function saveHierarchyConfig() {
    setSaving(true);
    setError(null);
    try {
      await api.put(`/api/v1/tenants/${tenantId}/hierarchy/config`, levels.map((l) => ({
        level_number: l.level_number,
        level_name: l.label,
        default_role_code: l.default_role_code,
        role_display_label: null,
        is_stock_holding: true,
      })));
      setDone(true);
      setTimeout(() => router.push(`/${org}/settings/personnel`), 1500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  function canAdvance(): boolean {
    if (step === 1) return true;
    if (step === 2) return levels.every((l) => l.label.trim() && l.code.trim());
    return true;
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center space-y-3">
          <div className="text-5xl">✅</div>
          <h2 className="text-xl font-bold text-gray-900">{t("org_setup.saved_success")}</h2>
          <p className="text-sm text-gray-500">{t("org_setup.redirecting")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{t("org_setup.page_title")}</h1>
          <p className="text-sm text-gray-500 mt-1">{t("org_setup.page_subtitle")}</p>
        </div>

        <WizardProgress current={step} />

        {/* Card */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          {step === 1 && (
            <StructureStep state={step1} onChange={handleStep1Change} />
          )}
          {step === 2 && (
            <LevelConfigStep levels={levels} onChange={setLevels} />
          )}
          {step === 3 && (
            <BuildTreeStep
              tenantId={tenantId}
              levels={levels}
              nodes={nodes}
              onNodesChange={setNodes}
            />
          )}
          {step === 4 && (
            <SupplyRoutesStep tenantId={tenantId} nodes={nodes} />
          )}
          {step === 5 && (
            <ReviewStep
              levels={levels}
              nodes={nodes}
              onConfirm={() => void saveHierarchyConfig()}
              saving={saving}
            />
          )}

          {error && (
            <div className="mt-4 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <p className="text-xs text-red-700 font-medium">{error}</p>
            </div>
          )}

          {/* Navigation buttons */}
          {step !== 5 && (
            <div className="flex justify-between mt-6 pt-4 border-t border-gray-100">
              <button
                type="button"
                onClick={() => setStep((s) => Math.max(1, s - 1) as StepId)}
                disabled={step === 1}
                className="px-4 py-2 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-30"
              >
                ← {t("common.back")}
              </button>
              <button
                type="button"
                onClick={() => setStep((s) => Math.min(5, s + 1) as StepId)}
                disabled={!canAdvance()}
                className="px-4 py-2 text-sm font-bold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
              >
                {t("common.next")} →
              </button>
            </div>
          )}
        </div>

        {/* Skip link */}
        <p className="text-center mt-4">
          <button
            type="button"
            onClick={() => router.push(`/${org}/settings/personnel`)}
            className="text-xs text-gray-400 hover:text-gray-600 border-0 bg-transparent cursor-pointer"
          >
            {t("org_setup.skip_to_personnel")}
          </button>
        </p>
      </div>
    </div>
  );
}
