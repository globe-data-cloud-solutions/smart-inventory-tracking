"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { getSession } from "@/lib/demo-auth";

/* ── Types ─────────────────────────────────────────────────────────────────── */

interface UserRecord {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  primary_facility_name: string | null;
  primary_facility_id: string | null;
  created_at: string;
}

interface Assignment {
  id: string;
  assignment_type: "PRIMARY" | "ACTING" | "DELEGATE";
  facility_id: string;
  facility_name: string | null;
  role_code: string;
  valid_from: string | null;
  valid_until: string | null;
  is_active: boolean;
}

interface UserDetail extends UserRecord {
  assignments: Assignment[];
}

interface OrgNode {
  id: string;
  name: string;
  code: string;
  hierarchy_level: number;
  children: OrgNode[];
}

interface NewUserForm {
  name: string;
  email: string;
  role: string;
  facility_id: string;
  password: string;
}

interface ActingAssignmentForm {
  facility_id: string;
  role_code: string;
  valid_from: string;
  valid_until: string;
}

/* ── Constants ─────────────────────────────────────────────────────────────── */

const ROLE_OPTIONS = [
  { code: "TA",    label: "Tenant Admin",        level: 9 },
  { code: "NM",    label: "National Manager",    level: 8 },
  { code: "RM",    label: "Regional Manager",    level: 7 },
  { code: "WM",    label: "Warehouse Manager",   level: 6 },
  { code: "LM",    label: "Logistics Manager",   level: 6 },
  { code: "SA_GT", label: "Sales Agent",         level: 4 },
  { code: "RT",    label: "Retailer",            level: 3 },
  { code: "AU",    label: "Auditor",             level: 2 },
] as const;

const ROLE_LEVEL: Record<string, number> = {
  SA: 10, TA: 9, NM: 8, RM: 7, WM: 6, LM: 6, SA_GT: 4, RT: 3, AU: 2, SYS: 1,
};

const ROLE_BADGE_CLASS: Record<string, string> = {
  TA:    "bg-violet-100 text-violet-700",
  NM:    "bg-blue-100  text-blue-700",
  RM:    "bg-teal-100  text-teal-700",
  WM:    "bg-emerald-100 text-emerald-700",
  LM:    "bg-cyan-100  text-cyan-700",
  SA_GT: "bg-orange-100 text-orange-700",
  RT:    "bg-yellow-100 text-yellow-700",
  AU:    "bg-gray-100  text-gray-600",
};

const EMPTY_USER: NewUserForm = {
  name: "", email: "", role: "WM", facility_id: "", password: "",
};

const EMPTY_ACTING: ActingAssignmentForm = {
  facility_id: "", role_code: "WM", valid_from: "", valid_until: "",
};

/* ── Helpers ────────────────────────────────────────────────────────────────── */

function flattenNodes(nodes: OrgNode[]): OrgNode[] {
  const out: OrgNode[] = [];
  function visit(list: OrgNode[]) {
    for (const n of list) { out.push(n); visit(n.children); }
  }
  visit(nodes);
  return out;
}

function roleBadge(role: string) {
  return (
    <span
      className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
        ROLE_BADGE_CLASS[role] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {role}
    </span>
  );
}

function isExpired(until: string | null): boolean {
  if (!until) return false;
  return new Date(until) < new Date();
}

/* ── Add User Panel ─────────────────────────────────────────────────────────── */

function AddUserPanel({
  tenantId,
  callerRole,
  nodes,
  onClose,
  onCreated,
}: {
  tenantId: string;
  callerRole: string;
  nodes: OrgNode[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<NewUserForm>({ ...EMPTY_USER });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const callerLevel = ROLE_LEVEL[callerRole] ?? 0;
  const allowedRoles = ROLE_OPTIONS.filter((r) => r.level < callerLevel);
  const flat = flattenNodes(nodes);

  function update(patch: Partial<NewUserForm>) {
    setForm((f) => ({ ...f, ...patch }));
  }

  async function submit() {
    if (!form.name.trim() || !form.email.trim() || !form.facility_id) {
      setError(t("personnel.fill_required_fields"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post(`/api/v1/tenants/${tenantId}/users`, {
        name:        form.name.trim(),
        email:       form.email.trim().toLowerCase(),
        role:        form.role,
        facility_id: form.facility_id,
        password:    form.password || undefined,
      });
      onCreated();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-gray-900">{t("personnel.add_user")}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl border-0 bg-transparent cursor-pointer">✕</button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.full_name")} *</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update({ name: e.target.value })}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.email")} *</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => update({ email: e.target.value })}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.role")} *</label>
              <select
                value={form.role}
                onChange={(e) => update({ role: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                {allowedRoles.map((r) => (
                  <option key={r.code} value={r.code}>{r.code} — {r.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.primary_facility")} *</label>
              <select
                value={form.facility_id}
                onChange={(e) => update({ facility_id: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">{t("personnel.select_facility")}</option>
                {flat.map((n) => (
                  <option key={n.id} value={n.id}>L{n.hierarchy_level} — {n.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.temp_password")}</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => update({ password: e.target.value })}
              placeholder={t("personnel.temp_password_hint")}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
        </div>

        {error && <p className="text-xs text-red-600 font-medium">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.create_user")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Acting Assignment Panel ────────────────────────────────────────────────── */

function ActingAssignmentPanel({
  tenantId,
  userId,
  callerRole,
  nodes,
  onClose,
  onCreated,
}: {
  tenantId: string;
  userId: string;
  callerRole: string;
  nodes: OrgNode[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<ActingAssignmentForm>({ ...EMPTY_ACTING });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  const callerLevel = ROLE_LEVEL[callerRole] ?? 0;
  const allowedRoles = ROLE_OPTIONS.filter((r) => r.level < callerLevel);
  const flat = flattenNodes(nodes);

  function update(patch: Partial<ActingAssignmentForm>) {
    setForm((f) => ({ ...f, ...patch }));
  }

  async function submit() {
    if (!form.facility_id || !form.valid_from || !form.valid_until) {
      setError(t("personnel.acting_fill_required"));
      return;
    }
    if (new Date(form.valid_until) <= new Date(form.valid_from)) {
      setError(t("personnel.acting_end_after_start"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.post(`/api/v1/tenants/${tenantId}/users/${userId}/assignments`, {
        assignment_type: "ACTING",
        facility_id:     form.facility_id,
        role_code:       form.role_code,
        valid_from:      form.valid_from,
        valid_until:     form.valid_until,
      });
      onCreated();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-gray-900">{t("personnel.add_acting_assignment")}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl border-0 bg-transparent cursor-pointer">✕</button>
        </div>

        <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
          <p className="text-xs text-blue-700">{t("personnel.acting_assignment_note")}</p>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.acting_facility")} *</label>
              <select
                value={form.facility_id}
                onChange={(e) => update({ facility_id: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">{t("personnel.select_facility")}</option>
                {flat.map((n) => (
                  <option key={n.id} value={n.id}>L{n.hierarchy_level} — {n.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.acting_role")} *</label>
              <select
                value={form.role_code}
                onChange={(e) => update({ role_code: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {allowedRoles.map((r) => (
                  <option key={r.code} value={r.code}>{r.code} — {r.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.valid_from")} *</label>
              <input
                type="date"
                value={form.valid_from}
                onChange={(e) => update({ valid_from: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.valid_until")} *</label>
              <input
                type="date"
                value={form.valid_until}
                onChange={(e) => update({ valid_until: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        {error && <p className="text-xs text-red-600 font-medium">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.create_assignment")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── User detail panel ──────────────────────────────────────────────────────── */

function UserDetailPanel({
  tenantId,
  user,
  callerRole,
  nodes,
  onClose,
  onRefresh,
}: {
  tenantId: string;
  user: UserDetail;
  callerRole: string;
  nodes: OrgNode[];
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [showActing, setShowActing] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const session = getSession();
  const isSelf = session?.id === user.id;

  async function toggleActive(activate: boolean) {
    setActionLoading(activate ? "reactivate" : "deactivate");
    try {
      const endpoint = activate ? "reactivate" : "deactivate";
      await api.post(`/api/v1/tenants/${tenantId}/users/${user.id}/${endpoint}`, {});
      onRefresh();
      onClose();
    } catch {
      /* surface via toast in production */
    } finally {
      setActionLoading(null);
    }
  }

  async function removeAssignment(assignmentId: string) {
    setActionLoading(`del:${assignmentId}`);
    try {
      await api.delete(`/api/v1/tenants/${tenantId}/users/${user.id}/assignments/${assignmentId}`);
      onRefresh();
    } catch {
      /* surface via toast */
    } finally {
      setActionLoading(null);
    }
  }

  const activeAssignments = user.assignments.filter(
    (a) => a.is_active && !isExpired(a.valid_until)
  );
  const expiredAssignments = user.assignments.filter(
    (a) => !a.is_active || isExpired(a.valid_until)
  );

  return (
    <>
      <div className="fixed inset-y-0 right-0 z-[150] w-[420px] bg-white shadow-2xl border-l border-gray-200 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center text-lg font-bold text-emerald-700">
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">{user.name}</p>
              <p className="text-xs text-gray-400">{user.email}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl border-0 bg-transparent cursor-pointer">✕</button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Identity row */}
          <div className="flex items-center gap-3">
            {roleBadge(user.role)}
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
              user.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"
            }`}>
              {user.is_active ? t("personnel.active") : t("personnel.inactive")}
            </span>
            {user.primary_facility_name && (
              <span className="text-xs text-gray-500">🏭 {user.primary_facility_name}</span>
            )}
          </div>

          {/* Active assignments */}
          <div>
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
              {t("personnel.active_assignments")} ({activeAssignments.length})
            </p>
            {activeAssignments.length === 0 ? (
              <p className="text-xs text-gray-400">{t("personnel.no_active_assignments")}</p>
            ) : (
              <div className="space-y-2">
                {activeAssignments.map((a) => (
                  <div key={a.id} className="flex items-start justify-between bg-gray-50 rounded-lg px-3 py-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          a.assignment_type === "PRIMARY"
                            ? "bg-emerald-100 text-emerald-700"
                            : a.assignment_type === "ACTING"
                            ? "bg-blue-100 text-blue-700"
                            : "bg-violet-100 text-violet-700"
                        }`}>
                          {a.assignment_type}
                        </span>
                        {roleBadge(a.role_code)}
                      </div>
                      <p className="text-xs text-gray-600 mt-1">{a.facility_name ?? a.facility_id}</p>
                      {a.valid_from && (
                        <p className="text-[10px] text-gray-400 mt-0.5">
                          {a.valid_from} → {a.valid_until ?? "∞"}
                        </p>
                      )}
                    </div>
                    {a.assignment_type !== "PRIMARY" && (
                      <button
                        type="button"
                        onClick={() => void removeAssignment(a.id)}
                        disabled={actionLoading === `del:${a.id}`}
                        className="text-xs text-red-400 hover:text-red-600 border-0 bg-transparent cursor-pointer disabled:opacity-50"
                      >
                        {t("common.remove")}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Expired/inactive assignments */}
          {expiredAssignments.length > 0 && (
            <div>
              <p className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">
                {t("personnel.expired_assignments")}
              </p>
              <div className="space-y-1 opacity-50">
                {expiredAssignments.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 bg-gray-50 rounded px-3 py-1.5">
                    <span className="text-[10px] font-bold text-gray-400 border border-gray-300 rounded px-1">
                      {a.assignment_type}
                    </span>
                    <span className="text-xs text-gray-500">{a.facility_name ?? a.facility_id}</span>
                    {a.valid_until && (
                      <span className="text-[10px] text-red-400">expired {a.valid_until}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="px-5 py-4 border-t border-gray-100 space-y-2 shrink-0">
          {user.is_active && (
            <button
              type="button"
              onClick={() => setShowActing(true)}
              className="w-full py-2 text-sm font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100"
            >
              + {t("personnel.add_acting_assignment")}
            </button>
          )}

          {!isSelf && (
            user.is_active ? (
              <button
                type="button"
                onClick={() => void toggleActive(false)}
                disabled={actionLoading === "deactivate"}
                className="w-full py-2 text-sm font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-50"
              >
                {actionLoading === "deactivate" ? t("common.saving") : t("personnel.deactivate")}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void toggleActive(true)}
                disabled={actionLoading === "reactivate"}
                className="w-full py-2 text-sm font-semibold text-green-700 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100 disabled:opacity-50"
              >
                {actionLoading === "reactivate" ? t("common.saving") : t("personnel.reactivate")}
              </button>
            )
          )}
        </div>
      </div>

      {showActing && (
        <ActingAssignmentPanel
          tenantId={tenantId}
          userId={user.id}
          callerRole={callerRole}
          nodes={nodes}
          onClose={() => setShowActing(false)}
          onCreated={onRefresh}
        />
      )}
    </>
  );
}

/* ── Main personnel page ────────────────────────────────────────────────────── */

export default function PersonnelPage() {
  const { org } = useParams() as { org: string };
  const session  = getSession();
  const tenantId = session?.tenantId ?? "";
  const callerRole = session?.role ?? "WM";
  const qc = useQueryClient();

  const [search, setSearch]         = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("active");
  const [showAddUser, setShowAddUser] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserDetail | null>(null);

  const { data: users = [], refetch: refetchUsers } = useQuery<UserRecord[]>({
    queryKey: ["personnel-users", tenantId],
    queryFn:  () => api.get<UserRecord[]>(`/api/v1/tenants/${tenantId}/users`),
    enabled:  !!tenantId,
  });

  const { data: nodes = [] } = useQuery<OrgNode[]>({
    queryKey: ["org-nodes", tenantId],
    queryFn:  () => api.get<OrgNode[]>(`/api/v1/tenants/${tenantId}/nodes`),
    enabled:  !!tenantId,
  });

  async function openDetail(user: UserRecord) {
    try {
      const detail = await api.get<UserDetail>(
        `/api/v1/tenants/${tenantId}/users/${user.id}`
      );
      setSelectedUser(detail);
    } catch {
      // Fallback: show limited info
      setSelectedUser({ ...user, assignments: [] });
    }
  }

  const filtered = users.filter((u) => {
    if (statusFilter === "active"   && !u.is_active) return false;
    if (statusFilter === "inactive" && u.is_active)  return false;
    if (roleFilter && u.role !== roleFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        u.name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.primary_facility_name ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const stats = {
    total:    users.length,
    active:   users.filter((u) => u.is_active).length,
    inactive: users.filter((u) => !u.is_active).length,
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t("personnel.page_title")}</h1>
          <p className="text-sm text-gray-500 mt-0.5">{t("personnel.page_subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={() => setShowAddUser(true)}
          className="px-4 py-2 text-sm font-bold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700"
        >
          + {t("personnel.add_user")}
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: t("personnel.total_users"),    value: stats.total,    cls: "text-gray-900" },
          { label: t("personnel.active_users"),   value: stats.active,   cls: "text-green-600" },
          { label: t("personnel.inactive_users"), value: stats.inactive, cls: "text-red-500"  },
        ].map(({ label, value, cls }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs font-medium text-gray-500">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${cls}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("personnel.search_placeholder")}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500 w-64"
        />

        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
        >
          <option value="">{t("personnel.all_roles")}</option>
          {ROLE_OPTIONS.map((r) => (
            <option key={r.code} value={r.code}>{r.code} — {r.label}</option>
          ))}
        </select>

        <div className="flex rounded-lg border border-gray-300 overflow-hidden">
          {(["all", "active", "inactive"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 text-xs font-medium border-0 cursor-pointer transition-all ${
                statusFilter === s
                  ? "bg-emerald-600 text-white"
                  : "bg-white text-gray-500 hover:bg-gray-50"
              }`}
            >
              {t(`personnel.status_${s}`)}
            </button>
          ))}
        </div>
      </div>

      {/* User table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {filtered.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-gray-400 text-sm">{t("personnel.no_users_found")}</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left text-xs font-semibold text-gray-500 px-4 py-3">{t("personnel.name")}</th>
                <th className="text-left text-xs font-semibold text-gray-500 px-4 py-3">{t("personnel.role")}</th>
                <th className="text-left text-xs font-semibold text-gray-500 px-4 py-3">{t("personnel.facility")}</th>
                <th className="text-left text-xs font-semibold text-gray-500 px-4 py-3">{t("personnel.status")}</th>
                <th className="text-left text-xs font-semibold text-gray-500 px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => void openDetail(u)}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                        u.is_active ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"
                      }`}>
                        {u.name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <p className="font-medium text-gray-900 m-0">{u.name}</p>
                        <p className="text-xs text-gray-400 m-0">{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">{roleBadge(u.role)}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-600">
                      {u.primary_facility_name ?? <span className="text-gray-300">{t("personnel.no_facility")}</span>}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      u.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"
                    }`}>
                      {u.is_active ? t("personnel.active") : t("personnel.inactive")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-xs text-emerald-600 font-semibold">{t("common.view")} →</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modals */}
      {showAddUser && (
        <AddUserPanel
          tenantId={tenantId}
          callerRole={callerRole}
          nodes={nodes}
          onClose={() => setShowAddUser(false)}
          onCreated={() => void refetchUsers()}
        />
      )}

      {selectedUser && (
        <UserDetailPanel
          tenantId={tenantId}
          user={selectedUser}
          callerRole={callerRole}
          nodes={nodes}
          onClose={() => setSelectedUser(null)}
          onRefresh={() => void refetchUsers()}
        />
      )}
    </div>
  );
}
