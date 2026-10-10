"use client";

import { useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";

/* ── Types ─────────────────────────────────────────────────────────────────── */

/** Mirrors personnel_v2.py's PositionAssignmentOut — a single position assignment. */
interface PositionRow {
  assignment_id: string;
  position_id: string;
  title: string;
  role_code: string;
  node_id: string;
  node_name: string;
  level_number: number;
  assignment_type: "PRIMARY" | "ACTING" | "DELEGATE";
  valid_from: string | null;
  valid_until: string | null;
}

interface UserRecord {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  primary_facility_name: string | null;
  primary_facility_id: string | null;
  primary_position: PositionRow | null;
  acting_positions: PositionRow[];
  created_at: string;
}

// GET /users/{id} returns the same UserOut shape as the list endpoint.
type UserDetail = UserRecord;

/** A position flattened from NodePositionGroupOut for dropdown use. */
interface PositionItem {
  id: string;
  title: string;
  role_code: string;
  node_id: string;
  node_name: string;
}


type AddUserTrack = "position" | "tenant_wide";

interface NewUserForm {
  name: string;
  email: string;
  position_id: string;
  system_role: "" | "AU" | "LM";
  password: string;
}

interface ActingAssignmentForm {
  position_id: string;
  valid_from: string;
  valid_until: string;
  notes: string;
}

/* ── Constants ─────────────────────────────────────────────────────────────── */

// Role catalog used for display (badges, the read-only "Role" filter dropdown,
// and role-derived-from-position previews). Role is never set directly through
// these forms — it always comes from the selected position's role_code.
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

function roleLabel(code: string | null | undefined): string {
  if (!code) return "—";
  return ROLE_OPTIONS.find((r) => r.code === code)?.label ?? code;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const EMPTY_USER: NewUserForm = {
  name: "", email: "", position_id: "", system_role: "", password: "",
};

function emptyActingForm(): ActingAssignmentForm {
  return { position_id: "", valid_from: todayISO(), valid_until: "", notes: "" };
}

interface EditUserForm {
  name: string;
  email: string;
  position_id: string;
  system_role: "" | "AU" | "LM";
  must_reset_password: boolean;
}

/** Mirrors AddUserPanel's two-track model. A user with a PRIMARY position is
 * always Track A; a user with no position whose role is AU/LM is Track B;
 * anyone else (unassigned, or TA — not editable via this redesign) defaults
 * to Track A, same as a brand-new user. */
function initialTrackFor(user: UserRecord): AddUserTrack {
  if (!user.primary_position && (user.role === "AU" || user.role === "LM")) {
    return "tenant_wide";
  }
  return "position";
}

// Color scheme matches the Positions tab (org-setup/page.tsx ROLE_BADGE_COLORS) —
// used only for the role-derived-from-position preview below, kept separate from
// the table-wide roleBadge() below to avoid an unrelated visual change elsewhere.
const POSITION_ROLE_BADGE_COLORS: Record<string, string> = {
  NM: "bg-green-800 text-white",
  RM: "bg-green-600 text-white",
  WM: "bg-green-400 text-white",
  AU: "bg-blue-500  text-white",
  LM: "bg-gray-500  text-white",
  TA: "bg-teal-600  text-white",
  SA: "bg-purple-600 text-white",
};

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${POSITION_ROLE_BADGE_COLORS[role] ?? "bg-gray-300 text-gray-700"}`}>
      {role}
    </span>
  );
}

/** Bordered "radio card" — used for the Add User track selector and the
 * tenant-wide Access Level options. Visually a radio button, but styled as
 * a clickable card so the description text has room to breathe. */
function SelectableCard({
  selected,
  onSelect,
  title,
  description,
  badge,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  description: string;
  badge?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left rounded-lg border-2 px-3 py-2.5 transition-colors ${
        selected ? "border-green-600 bg-green-50" : "border-gray-200 bg-white hover:border-gray-300"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`inline-block w-3.5 h-3.5 rounded-full border-2 shrink-0 ${
          selected ? "border-green-600 bg-green-600" : "border-gray-300 bg-white"
        }`} />
        {badge}
        <span className="text-sm font-semibold text-gray-900">{title}</span>
      </div>
      <p className="text-xs text-gray-500 mt-1 ml-[22px]">{description}</p>
    </button>
  );
}

/* ── Helpers ────────────────────────────────────────────────────────────────── */

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

/* ── Confirm Position Change Modal ────────────────────────────────────────────── */

function ConfirmPositionChangeModal({
  userName,
  currentPosition,
  newPosition,
  saving,
  onCancel,
  onConfirm,
}: {
  userName: string;
  currentPosition: PositionRow;
  newPosition: PositionItem;
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[250] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <h2 className="text-base font-bold text-gray-900">
          {t("personnel.confirm_position_change_title")}
        </h2>

        <p className="text-sm text-gray-700">
          {t("personnel.confirm_position_change_prefix")} <span className="font-semibold">{userName}</span>
          {t("personnel.confirm_position_change_suffix")}
        </p>

        <div className="bg-gray-50 rounded-lg p-3 space-y-1.5 text-sm">
          <p className="text-gray-600">
            <span className="font-semibold text-gray-500">{t("personnel.confirm_position_change_from")}:</span>{" "}
            {currentPosition.title} ({currentPosition.role_code})
          </p>
          <p className="text-gray-600">
            <span className="font-semibold text-gray-500">{t("personnel.confirm_position_change_to")}:</span>{" "}
            {newPosition.title} ({newPosition.role_code})
          </p>
        </div>

        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          {t("personnel.confirm_position_change_warning")}
        </p>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.confirm_position_change_confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Confirm Track Switch Modal ───────────────────────────────────────────────── */

function ConfirmTrackSwitchModal({
  message,
  saving,
  onCancel,
  onConfirm,
}: {
  message: string;
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[250] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <p className="text-sm text-gray-700">{message}</p>
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.continue")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Edit User Panel ────────────────────────────────────────────────────────── */

function EditUserPanel({
  tenantId,
  user: initialUser,
  positions,
  onClose,
  onUpdated,
}: {
  tenantId: string;
  user: UserRecord;
  positions: PositionItem[];
  onClose: () => void;
  onUpdated: () => void;
}) {
  const currentPrimary = initialUser.primary_position;
  const initialTrack   = initialTrackFor(initialUser);
  const session = getSession();
  const isSelf  = session?.id === initialUser.id;

  const [track, setTrack] = useState<AddUserTrack>(initialTrack);
  const [form, setForm]   = useState<EditUserForm>({
    name:                initialUser.name,
    email:               initialUser.email,
    position_id:         currentPrimary?.position_id ?? "",
    system_role:         initialTrack === "tenant_wide" ? (initialUser.role as "AU" | "LM") : "",
    must_reset_password: false,
  });
  const [saving, setSaving]                   = useState(false);
  const [error, setError]                     = useState<string | null>(null);
  const [showConfirmSwap, setShowConfirmSwap] = useState(false);
  const [pendingTrack, setPendingTrack]       = useState<AddUserTrack | null>(null);
  const writeGuard = useWriteGuard();
  const gp = guardProps(writeGuard);

  function update(patch: Partial<EditUserForm>) {
    setForm((f) => ({ ...f, ...patch }));
  }

  // The position actually selected in the dropdown right now (for the read-only
  // role preview) — falls back to the user's current position when untouched.
  const selectedPosition = form.position_id
    ? positions.find((p) => p.id === form.position_id) ?? null
    : null;
  const previewRoleCode = selectedPosition?.role_code ?? currentPrimary?.role_code ?? null;

  // A "real" change is a non-blank selection that differs from the current PRIMARY.
  const isPositionChange =
    !!form.position_id && form.position_id !== (currentPrimary?.position_id ?? "");

  function applyTrackSwitch(next: AddUserTrack) {
    setTrack(next);
    if (next === "position") update({ system_role: "" });
    else update({ position_id: "" });
  }

  function requestTrackSwitch(next: AddUserTrack) {
    if (isSelf) return; // cannot change one's own position/role — see read-only section below
    if (next === track) return;
    // Only warn when the switch would actually undo something real — moving
    // away from the user's ORIGINAL assignment, not just toggling the radio
    // back and forth before saving.
    const needsWarning =
      (next === "tenant_wide" && initialTrack === "position" && !!currentPrimary) ||
      (next === "position" && initialTrack === "tenant_wide");
    if (needsWarning) {
      setPendingTrack(next);
    } else {
      applyTrackSwitch(next);
    }
  }

  async function doSubmit() {
    setSaving(true);
    setError(null);
    try {
      const patchBody: Record<string, unknown> = {
        name:                form.name.trim(),
        email:               form.email.trim().toLowerCase(),
        must_reset_password: form.must_reset_password,
      };
      // A user can never change their own position or role — see the read-only
      // section rendered below for isSelf. Skip all role/position fields and
      // calls entirely here as a second guard (the backend rejects these too).
      if (!isSelf) {
        if (track === "tenant_wide") {
          patchBody.system_role = form.system_role;
        } else if (initialTrack === "tenant_wide") {
          // Switching away from a tenant-wide role — clear it explicitly so role
          // resolution falls through to the new position instead of the stale value.
          patchBody.clear_system_role = true;
        }
      }
      await api.patch(`/api/v1/tenants/${tenantId}/users/${initialUser.id}`, patchBody);

      if (!isSelf && track === "position" && isPositionChange) {
        await api.post(`/api/v1/tenants/${tenantId}/users/${initialUser.id}/positions`, {
          position_id:     form.position_id,
          assignment_type: "PRIMARY",
        });
      }
      if (!isSelf && track === "tenant_wide" && currentPrimary) {
        // Switching from a position-based role — deactivate the old PRIMARY.
        await api.delete(`/api/v1/tenants/${tenantId}/users/${initialUser.id}/positions/${currentPrimary.assignment_id}`);
      }

      onUpdated();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
      setShowConfirmSwap(false);
    }
  }

  function handleSaveClick() {
    if (!form.name.trim() || !form.email.trim()) {
      setError(t("personnel.fill_required_fields"));
      return;
    }
    if (!isSelf && track === "tenant_wide" && !form.system_role) {
      setError(t("personnel.fill_required_fields"));
      return;
    }
    setError(null);
    // Swapping an existing PRIMARY position is a destructive, immediately-effective
    // change (the old assignment is deactivated) — confirm before calling the API.
    if (!isSelf && track === "position" && isPositionChange && currentPrimary) {
      setShowConfirmSwap(true);
      return;
    }
    void doSubmit();
  }

  return (
    <>
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4">
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-gray-900">{t("personnel.edit_user")}</h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl border-0 bg-transparent cursor-pointer">✕</button>
          </div>

          <div className="space-y-3">
            {isSelf ? (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-gray-600">{t("personnel.role_and_position")}</p>
                <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
                  {previewRoleCode && <RoleBadge role={previewRoleCode} />}
                  <span className="text-sm text-gray-600">
                    {currentPrimary
                      ? `${currentPrimary.title} — ${currentPrimary.node_name}`
                      : roleLabel(initialUser.role)}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{t("personnel.cannot_edit_own_role_note")}</p>
              </div>
            ) : (
              <div className="space-y-2">
                <SelectableCard
                  selected={track === "position"}
                  onSelect={() => requestTrackSwitch("position")}
                  title={t("personnel.track_position_title")}
                  description={t("personnel.track_position_desc")}
                />
                <SelectableCard
                  selected={track === "tenant_wide"}
                  onSelect={() => requestTrackSwitch("tenant_wide")}
                  title={t("personnel.track_tenant_wide_title")}
                  description={t("personnel.track_tenant_wide_desc")}
                />
              </div>
            )}

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

            {!isSelf && (track === "position" ? (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.primary_position")}</label>
                <select
                  value={form.position_id}
                  onChange={(e) => update({ position_id: e.target.value })}
                  className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                >
                  <option value="">{t("personnel.keep_existing_position")}</option>
                  {positions.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title} ({p.role_code}) — {p.node_name}
                    </option>
                  ))}
                </select>
                {previewRoleCode ? (
                  <div className="mt-1 flex items-center gap-2 text-sm">
                    <RoleBadge role={previewRoleCode} />
                    <span className="text-gray-500">{roleLabel(previewRoleCode)}</span>
                  </div>
                ) : (
                  <p className="text-xs text-gray-500 mt-1">{t("personnel.no_position_no_role")}</p>
                )}
              </div>
            ) : (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.access_level")} *</label>
                <div className="space-y-2">
                  <SelectableCard
                    selected={form.system_role === "AU"}
                    onSelect={() => update({ system_role: "AU" })}
                    badge={<RoleBadge role="AU" />}
                    title={t("personnel.role_au_title")}
                    description={t("personnel.role_au_desc")}
                  />
                  <SelectableCard
                    selected={form.system_role === "LM"}
                    onSelect={() => update({ system_role: "LM" })}
                    badge={<RoleBadge role="LM" />}
                    title={t("personnel.role_lm_title")}
                    description={t("personnel.role_lm_desc")}
                  />
                </div>
              </div>
            ))}

            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.must_reset_password}
                onChange={(e) => update({ must_reset_password: e.target.checked })}
                className="w-4 h-4 accent-emerald-600"
              />
              <span className="text-xs text-gray-600">{t("personnel.force_password_reset")}</span>
            </label>
          </div>

          {gp.title && (
            <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {gp.title}
            </p>
          )}
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
              onClick={handleSaveClick}
              disabled={saving || gp.disabled}
              title={gp.title}
              className="px-4 py-1.5 text-sm font-bold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
            >
              {saving ? t("common.saving") : t("personnel.save_changes")}
            </button>
          </div>
        </div>
      </div>

      {showConfirmSwap && currentPrimary && selectedPosition && (
        <ConfirmPositionChangeModal
          userName={initialUser.name}
          currentPosition={currentPrimary}
          newPosition={selectedPosition}
          saving={saving}
          onCancel={() => setShowConfirmSwap(false)}
          onConfirm={() => void doSubmit()}
        />
      )}

      {pendingTrack && (
        <ConfirmTrackSwitchModal
          message={
            pendingTrack === "tenant_wide"
              ? t("personnel.switch_to_tenant_wide_warning").replace("{name}", initialUser.name)
              : t("personnel.switch_to_position_warning").replace("{name}", initialUser.name)
          }
          saving={false}
          onCancel={() => setPendingTrack(null)}
          onConfirm={() => {
            applyTrackSwitch(pendingTrack);
            setPendingTrack(null);
          }}
        />
      )}
    </>
  );
}

/* ── Add User Panel ─────────────────────────────────────────────────────────── */

function AddUserPanel({
  tenantId,
  positions,
  onClose,
  onCreated,
}: {
  tenantId: string;
  positions: PositionItem[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [track, setTrack] = useState<AddUserTrack>("position");
  const [form, setForm]   = useState<NewUserForm>({ ...EMPTY_USER });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);
  const writeGuard = useWriteGuard();
  const gp = guardProps(writeGuard, "users");

  const selectedPosition = form.position_id
    ? positions.find((p) => p.id === form.position_id) ?? null
    : null;

  function update(patch: Partial<NewUserForm>) {
    setForm((f) => ({ ...f, ...patch }));
  }

  function selectTrack(next: AddUserTrack) {
    setTrack(next);
    // Clear the other track's selection so a stale value can't be submitted
    // after switching — only one of position_id / system_role is ever sent.
    if (next === "position") update({ system_role: "" });
    else update({ position_id: "" });
  }

  async function submit() {
    if (!form.name.trim() || !form.email.trim()) {
      setError(t("personnel.fill_required_fields"));
      return;
    }
    if (track === "tenant_wide" && !form.system_role) {
      setError(t("personnel.fill_required_fields"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Track A: role is never sent directly — it is derived server-side from
      // position_id (personnel_v2.py create_user creates the PRIMARY assignment
      // atomically). Track B: position_id is never sent — system_role is direct.
      await api.post(`/api/v1/tenants/${tenantId}/users`, {
        name:        form.name.trim(),
        email:       form.email.trim().toLowerCase(),
        position_id: track === "position"    ? (form.position_id || null) : null,
        system_role: track === "tenant_wide" ? form.system_role           : null,
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
          <div className="space-y-2">
            <SelectableCard
              selected={track === "position"}
              onSelect={() => selectTrack("position")}
              title={t("personnel.track_position_title")}
              description={t("personnel.track_position_desc")}
            />
            <SelectableCard
              selected={track === "tenant_wide"}
              onSelect={() => selectTrack("tenant_wide")}
              title={t("personnel.track_tenant_wide_title")}
              description={t("personnel.track_tenant_wide_desc")}
            />
          </div>

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

          {track === "position" ? (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.primary_position")}</label>
              <select
                value={form.position_id}
                onChange={(e) => update({ position_id: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">{t("personnel.no_position_assigned")}</option>
                {positions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title} ({p.role_code}) — {p.node_name}
                  </option>
                ))}
              </select>
              {selectedPosition ? (
                <div className="mt-1 flex items-center gap-2 text-sm">
                  <RoleBadge role={selectedPosition.role_code} />
                  <span className="text-gray-500">
                    {selectedPosition.title} · {selectedPosition.node_name}
                  </span>
                </div>
              ) : (
                <p className="text-xs text-gray-500 mt-1">{t("personnel.no_position_no_role")}</p>
              )}
            </div>
          ) : (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.access_level")} *</label>
              <div className="space-y-2">
                <SelectableCard
                  selected={form.system_role === "AU"}
                  onSelect={() => update({ system_role: "AU" })}
                  badge={<RoleBadge role="AU" />}
                  title={t("personnel.role_au_title")}
                  description={t("personnel.role_au_desc")}
                />
                <SelectableCard
                  selected={form.system_role === "LM"}
                  onSelect={() => update({ system_role: "LM" })}
                  badge={<RoleBadge role="LM" />}
                  title={t("personnel.role_lm_title")}
                  description={t("personnel.role_lm_desc")}
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.temp_password")}</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => update({ password: e.target.value })}
              placeholder={t("personnel.password_optional_hint")}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
        </div>

        {gp.title && (
          <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {gp.title}
          </p>
        )}
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
            disabled={saving || gp.disabled}
            title={gp.title}
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
  positions,
  onClose,
  onCreated,
}: {
  tenantId: string;
  userId: string;
  positions: PositionItem[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<ActingAssignmentForm>(emptyActingForm);
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState<string | null>(null);
  const writeGuard = useWriteGuard();
  const gp = guardProps(writeGuard);

  const selectedPosition = form.position_id
    ? positions.find((p) => p.id === form.position_id) ?? null
    : null;

  function update(patch: Partial<ActingAssignmentForm>) {
    setForm((f) => ({ ...f, ...patch }));
  }

  async function submit() {
    if (!form.position_id) {
      setError(t("personnel.acting_fill_required"));
      return;
    }
    if (!form.valid_until) {
      setError(t("personnel.acting_valid_until_required"));
      return;
    }
    if (new Date(form.valid_until) <= new Date(todayISO())) {
      setError(t("personnel.acting_valid_until_future"));
      return;
    }
    if (new Date(form.valid_until) <= new Date(form.valid_from)) {
      setError(t("personnel.acting_end_after_start"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Live model: ACTING is a time-bounded position assignment, not a raw
      // facility+role_code grant — same endpoint as the PRIMARY assignment.
      await api.post(`/api/v1/tenants/${tenantId}/users/${userId}/positions`, {
        position_id:     form.position_id,
        assignment_type: "ACTING",
        valid_from:      form.valid_from,
        valid_until:     form.valid_until,
        notes:           form.notes || null,
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
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.acting_position")} *</label>
            <select
              value={form.position_id}
              onChange={(e) => update({ position_id: e.target.value })}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">{t("personnel.acting_select_position")}</option>
              {positions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} ({p.role_code}) — {p.node_name}
                </option>
              ))}
            </select>
            {selectedPosition && (
              <p className="text-xs text-gray-500 mt-1">
                {t("personnel.role")}: {roleLabel(selectedPosition.role_code)} ({selectedPosition.role_code})
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.acting_valid_from")} *</label>
              <input
                type="date"
                value={form.valid_from}
                onChange={(e) => update({ valid_from: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.acting_valid_until")} *</label>
              <input
                type="date"
                value={form.valid_until}
                onChange={(e) => update({ valid_until: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">{t("personnel.acting_notes")}</label>
            <input
              type="text"
              value={form.notes}
              onChange={(e) => update({ notes: e.target.value })}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {gp.title && (
          <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {gp.title}
          </p>
        )}
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
            disabled={saving || gp.disabled}
            title={gp.title}
            className="px-4 py-1.5 text-sm font-bold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.create_assignment")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Confirm Force-Remove (SA-only) Modal ─────────────────────────────────────── */

function ConfirmForceRemoveModal({
  saving,
  error,
  onCancel,
  onConfirm,
}: {
  saving: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[250] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <h2 className="text-base font-bold text-gray-900">{t("personnel.confirm_force_remove_title")}</h2>
        <p className="text-sm text-gray-700">{t("personnel.confirm_force_remove_body")}</p>
        {error && <p className="text-xs text-red-600 font-medium">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.confirm_force_remove_confirm")}
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
  positions,
  onClose,
  onRefresh,
}: {
  tenantId: string;
  user: UserDetail;
  positions: PositionItem[];
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [showActing, setShowActing] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [confirmForceRemoveId, setConfirmForceRemoveId] = useState<string | null>(null);
  const [forceRemoveError, setForceRemoveError] = useState<string | null>(null);
  const [forceRemoveSuccess, setForceRemoveSuccess] = useState<string | null>(null);
  const writeGuard = useWriteGuard();
  // Reactivate goes through user:manage (not in ALLOWED_WRITE_ACTIONS) — guarded.
  // Deactivate goes through user:deactivate, which IS allowed in READ_ONLY
  // (CLAUDE.md §29 P6) — left fully enabled below, no guard.
  const gp = guardProps(writeGuard);

  const session = getSession();
  const isSelf = session?.id === user.id;
  const isSA   = session?.role === "SA";

  async function toggleActive(activate: boolean) {
    setActionLoading(activate ? "reactivate" : "deactivate");
    try {
      const endpoint = activate ? "reactivate" : "deactivate";
      // Both routes are PATCH-only in personnel_v2.py — POST here would 405.
      await api.patch(`/api/v1/tenants/${tenantId}/users/${user.id}/${endpoint}`, {});
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
    setForceRemoveSuccess(null);
    try {
      // Live endpoint is position-based, not the dropped facility-assignment path.
      await api.delete(`/api/v1/tenants/${tenantId}/users/${user.id}/positions/${assignmentId}`);
      onRefresh();
    } catch (e: unknown) {
      const code = e instanceof Error ? (e as Error & { code?: string }).code : undefined;
      // Only an SA gets the force-remove escape hatch — everyone else keeps the
      // existing silent failure (surfaced via toast in production).
      if (code === "CANNOT_REMOVE_LAST_PRIMARY" && isSA) {
        setConfirmForceRemoveId(assignmentId);
      }
    } finally {
      setActionLoading(null);
    }
  }

  async function forceRemoveAssignment(assignmentId: string) {
    setActionLoading(`del:${assignmentId}`);
    setForceRemoveError(null);
    try {
      await api.delete(`/api/v1/tenants/${tenantId}/users/${user.id}/positions/${assignmentId}?force=true`);
      setConfirmForceRemoveId(null);
      setForceRemoveSuccess(t("personnel.force_remove_success"));
      onRefresh();
    } catch (e: unknown) {
      setForceRemoveError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setActionLoading(null);
    }
  }

  const primaryPosition  = user.primary_position;
  const actingPositions  = user.acting_positions ?? [];

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

          {/* Active assignments — primary + acting (already filtered by the
              backend to is_active=true and not-yet-expired) */}
          <div>
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
              {t("personnel.active_assignments")} ({(primaryPosition ? 1 : 0) + actingPositions.length})
            </p>
            {forceRemoveSuccess && (
              <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 font-medium mb-2">
                {forceRemoveSuccess}
              </p>
            )}
            {!primaryPosition && actingPositions.length === 0 ? (
              <p className="text-xs text-gray-400">{t("personnel.no_active_assignments")}</p>
            ) : (
              <div className="space-y-2">
                {primaryPosition && (
                  <div className="flex items-start justify-between bg-gray-50 rounded-lg px-3 py-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">
                          {primaryPosition.assignment_type}
                        </span>
                        {roleBadge(primaryPosition.role_code)}
                      </div>
                      <p className="text-xs text-gray-600 mt-1">
                        {primaryPosition.title} — {primaryPosition.node_name}
                      </p>
                    </div>
                    {!isSelf && (
                      <button
                        type="button"
                        onClick={() => void removeAssignment(primaryPosition.assignment_id)}
                        disabled={actionLoading === `del:${primaryPosition.assignment_id}` || gp.disabled}
                        title={gp.title}
                        className="text-xs text-red-400 hover:text-red-600 border-0 bg-transparent cursor-pointer disabled:opacity-50"
                      >
                        {t("common.remove")}
                      </button>
                    )}
                  </div>
                )}
                {actingPositions.map((a) => (
                  <div key={a.assignment_id} className="flex items-start justify-between bg-gray-50 rounded-lg px-3 py-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          a.assignment_type === "ACTING"
                            ? "bg-blue-100 text-blue-700"
                            : "bg-violet-100 text-violet-700"
                        }`}>
                          {a.assignment_type}
                        </span>
                        {roleBadge(a.role_code)}
                      </div>
                      <p className="text-xs text-gray-600 mt-1">{a.title} — {a.node_name}</p>
                      {a.valid_from && (
                        <p className="text-[10px] text-gray-400 mt-0.5">
                          {a.valid_from} → {a.valid_until ?? "∞"}
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => void removeAssignment(a.assignment_id)}
                      disabled={actionLoading === `del:${a.assignment_id}` || gp.disabled}
                      title={gp.title}
                      className="text-xs text-red-400 hover:text-red-600 border-0 bg-transparent cursor-pointer disabled:opacity-50"
                    >
                      {t("common.remove")}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer actions */}
        <div className="px-5 py-4 border-t border-gray-100 space-y-2 shrink-0">
          {gp.title && (
            <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {gp.title}
            </p>
          )}
          {user.is_active && (
            <button
              type="button"
              onClick={() => { if (!gp.disabled) setShowActing(true); }}
              disabled={gp.disabled}
              title={gp.title}
              className="w-full py-2 text-sm font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              + {t("personnel.add_acting_assignment")}
            </button>
          )}

          {!isSelf && (
            user.is_active ? (
              // user:deactivate is allowed in READ_ONLY (CLAUDE.md §29 P6) —
              // always enabled, no guard.
              <button
                type="button"
                onClick={() => void toggleActive(false)}
                disabled={actionLoading === "deactivate"}
                className="w-full py-2 text-sm font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-50"
              >
                {actionLoading === "deactivate" ? t("common.saving") : t("personnel.deactivate")}
              </button>
            ) : (
              // Reactivate goes through user:manage, not exempted — guarded.
              <button
                type="button"
                onClick={() => void toggleActive(true)}
                disabled={actionLoading === "reactivate" || gp.disabled}
                title={gp.title}
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
          positions={positions}
          onClose={() => setShowActing(false)}
          onCreated={onRefresh}
        />
      )}

      {confirmForceRemoveId && (
        <ConfirmForceRemoveModal
          saving={actionLoading === `del:${confirmForceRemoveId}`}
          error={forceRemoveError}
          onCancel={() => { setConfirmForceRemoveId(null); setForceRemoveError(null); }}
          onConfirm={() => void forceRemoveAssignment(confirmForceRemoveId)}
        />
      )}
    </>
  );
}

/* ── Confirm Deactivate User Modal ────────────────────────────────────────────── */

function ConfirmDeactivateUserModal({
  userName,
  saving,
  onCancel,
  onConfirm,
}: {
  userName: string;
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[250] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <h2 className="text-base font-bold text-gray-900">{t("personnel.deactivate_user")}</h2>
        <p className="text-sm text-gray-700">
          {t("personnel.confirm_deactivate_user").replace("{name}", userName)}
        </p>
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.deactivate_user")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Reset Password Modal ─────────────────────────────────────────────────────── */

function ResetPasswordModal({
  tenantId,
  user,
  onClose,
  onSuccess,
}: {
  tenantId: string;
  user: UserRecord;
  onClose: () => void;
  onSuccess: (message: string) => void;
}) {
  const [password, setPassword] = useState("");
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState<string | null>(null);

  async function submit() {
    if (password.length < 8) {
      setError(t("personnel.password_min_length"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/api/v1/tenants/${tenantId}/users/${user.id}`, { password });
      onSuccess(t("personnel.reset_password_success").replace("{name}", user.name));
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[250] flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <h2 className="text-base font-bold text-gray-900">{t("personnel.reset_password_title")}</h2>
        <p className="text-sm text-gray-700">
          {t("personnel.reset_password_body").replace("{name}", user.name)}
        </p>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {t("personnel.new_temporary_password")} *
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>

        {error && <p className="text-xs text-red-600 font-medium">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving}
            className="px-4 py-1.5 text-sm font-bold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? t("common.saving") : t("personnel.reset_password")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Main personnel page ────────────────────────────────────────────────────── */

export default function PersonnelPage() {
  const { org } = useParams() as { org: string };
  const session    = getSession();
  const callerRole = session?.role ?? "WM";
  const qc = useQueryClient();

  // BUG 4 fix: SA JWT has tenant_id=null. When SA visits another tenant's page,
  // resolve the correct tenant UUID from the org slug via the API.
  const isSAViewing = callerRole === "SA" && org !== SA_ORG_SLUG;
  const { data: tenantMeta } = useQuery<{ id: string; name: string }>({
    queryKey: ["tenant-meta", org],
    queryFn:  () => api.get<{ id: string; name: string }>(`/api/v1/tenants/${org}`),
    enabled:  isSAViewing,
    staleTime: 60_000,
    retry: false,
  });
  const tenantId = isSAViewing
    ? (tenantMeta?.id ?? "")
    : (session?.tenantId ?? "");

  const [search, setSearch]         = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("active");
  const [showAddUser, setShowAddUser] = useState(false);
  const [editUser, setEditUser]       = useState<UserRecord | null>(null);
  const [selectedUser, setSelectedUser] = useState<UserDetail | null>(null);
  const [confirmDeactivateUser, setConfirmDeactivateUser] = useState<UserRecord | null>(null);
  const [resetPasswordUser, setResetPasswordUser]         = useState<UserRecord | null>(null);
  const [actionLoadingId, setActionLoadingId]             = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const writeGuard = useWriteGuard();
  // Add User creates a new user — counts against the "users" plan cap.
  const addUserGp = guardProps(writeGuard, "users");
  // Edit/Reactivate — read-only guard only. Reset password and Deactivate
  // are NOT guarded here — both stay allowed in READ_ONLY (CLAUDE.md §29 P6).
  const rowGp = guardProps(writeGuard);

  function showToast(message: string, tone: "success" | "error" = "success") {
    setToast({ message, tone });
    setTimeout(() => setToast(null), 4000);
  }

  const { data: users = [], refetch: refetchUsers } = useQuery<UserRecord[]>({
    queryKey: ["personnel-users", tenantId],
    queryFn:  () => api.get<UserRecord[]>(`/api/v1/tenants/${tenantId}/users`),
    enabled:  !!tenantId,
  });

  // Positions flattened from node groups — used in Add/Edit user dropdowns.
  // Fetches from GET /tenants/{uuid}/positions which returns NodePositionGroupOut[].
  const { data: positions = [] } = useQuery<PositionItem[]>({
    queryKey: ["positions-flat", tenantId],
    queryFn: async () => {
      const groups = await api.get<Array<{
        node_id:     string;
        node_name:   string;
        level_number: number;
        positions: Array<{ id: string; title: string; role_code: string; is_active: boolean }>;
      }>>(`/api/v1/tenants/${tenantId}/positions`);
      return groups.flatMap((g) =>
        g.positions
          .filter((p) => p.is_active)
          .map((p) => ({ id: p.id, title: p.title, role_code: p.role_code, node_id: g.node_id, node_name: g.node_name }))
      );
    },
    enabled:   !!tenantId,
    staleTime: 60_000,
  });

  async function openDetail(user: UserRecord) {
    try {
      const detail = await api.get<UserDetail>(
        `/api/v1/tenants/${tenantId}/users/${user.id}`
      );
      setSelectedUser(detail);
    } catch {
      // Fallback: show limited info without crashing
      setSelectedUser(user);
    }
  }

  function deactivateErrorMessage(e: unknown): string {
    const code = e instanceof Error ? (e as Error & { code?: string }).code : undefined;
    if (code === "CANNOT_DEACTIVATE_SELF")    return t("personnel.cannot_deactivate_self");
    if (code === "CANNOT_DEACTIVATE_LAST_TA") return t("personnel.cannot_deactivate_last_ta");
    return e instanceof Error ? e.message : t("common.error");
  }

  async function handleDeactivateConfirmed() {
    const user = confirmDeactivateUser;
    if (!user) return;
    setActionLoadingId(`deactivate:${user.id}`);
    try {
      await api.patch(`/api/v1/tenants/${tenantId}/users/${user.id}/deactivate`, {});
      showToast(t("personnel.user_deactivated"));
      await refetchUsers();
    } catch (e) {
      showToast(deactivateErrorMessage(e), "error");
    } finally {
      setActionLoadingId(null);
      setConfirmDeactivateUser(null);
    }
  }

  async function handleReactivate(user: UserRecord) {
    setActionLoadingId(`reactivate:${user.id}`);
    try {
      await api.patch(`/api/v1/tenants/${tenantId}/users/${user.id}/reactivate`, {});
      showToast(t("personnel.user_reactivated"));
      await refetchUsers();
    } catch (e) {
      showToast(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setActionLoadingId(null);
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
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-[300] px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium ${
          toast.tone === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"
        }`}>
          {toast.message}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t("personnel.page_title")}</h1>
          <p className="text-sm text-gray-500 mt-0.5">{t("personnel.page_subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={() => { if (!addUserGp.disabled) setShowAddUser(true); }}
          {...addUserGp}
          className="px-4 py-2 text-sm font-bold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
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
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); if (!rowGp.disabled) setEditUser(u); }}
                        disabled={rowGp.disabled}
                        title={rowGp.title ?? t("personnel.edit_user")}
                        className="text-xs text-blue-600 font-semibold hover:text-blue-800 border-0 bg-transparent cursor-pointer px-2 py-1 rounded hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        ✏ {t("common.edit")}
                      </button>
                      {/* user:reset_password is allowed in READ_ONLY (CLAUDE.md §29 P6) — never guarded. */}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setResetPasswordUser(u); }}
                        className="text-xs text-gray-600 font-semibold hover:text-gray-800 border-0 bg-transparent cursor-pointer px-2 py-1 rounded hover:bg-gray-100"
                        title={t("personnel.reset_password")}
                      >
                        {t("personnel.reset_password")}
                      </button>
                      {u.is_active ? (
                        // A user can never deactivate their own account — hide the
                        // button entirely rather than show it and let the backend 422.
                        // user:deactivate is allowed in READ_ONLY — never guarded.
                        session?.id !== u.id && (
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); setConfirmDeactivateUser(u); }}
                            disabled={actionLoadingId === `deactivate:${u.id}`}
                            className="text-xs text-red-600 font-semibold border border-red-200 rounded px-2 py-1 hover:bg-red-50 disabled:opacity-50"
                          >
                            {t("personnel.deactivate_user")}
                          </button>
                        )
                      ) : (
                        // Reactivate goes through user:manage, not exempted — guarded.
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); if (!rowGp.disabled) void handleReactivate(u); }}
                          disabled={actionLoadingId === `reactivate:${u.id}` || rowGp.disabled}
                          title={rowGp.title}
                          className="text-xs text-green-700 font-semibold border border-green-200 rounded px-2 py-1 hover:bg-green-50 disabled:opacity-50"
                        >
                          {actionLoadingId === `reactivate:${u.id}` ? t("common.saving") : t("personnel.reactivate_user")}
                        </button>
                      )}
                      <span className="text-xs text-emerald-600 font-semibold">{t("common.view")} →</span>
                    </div>
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
          positions={positions}
          onClose={() => setShowAddUser(false)}
          onCreated={() => void refetchUsers()}
        />
      )}

      {editUser && (
        <EditUserPanel
          tenantId={tenantId}
          user={editUser}
          positions={positions}
          onClose={() => setEditUser(null)}
          onUpdated={() => { void refetchUsers(); qc.invalidateQueries({ queryKey: ["personnel-users", tenantId] }); }}
        />
      )}

      {selectedUser && (
        <UserDetailPanel
          tenantId={tenantId}
          user={selectedUser}
          positions={positions}
          onClose={() => setSelectedUser(null)}
          onRefresh={() => void refetchUsers()}
        />
      )}

      {confirmDeactivateUser && (
        <ConfirmDeactivateUserModal
          userName={confirmDeactivateUser.name}
          saving={actionLoadingId === `deactivate:${confirmDeactivateUser.id}`}
          onCancel={() => setConfirmDeactivateUser(null)}
          onConfirm={() => void handleDeactivateConfirmed()}
        />
      )}

      {resetPasswordUser && (
        <ResetPasswordModal
          tenantId={tenantId}
          user={resetPasswordUser}
          onClose={() => setResetPasswordUser(null)}
          onSuccess={(message) => showToast(message)}
        />
      )}
    </div>
  );
}
