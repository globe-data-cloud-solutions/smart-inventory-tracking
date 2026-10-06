"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

interface TaUserOut {
  id: string;
  full_name: string;
  email: string;
}

export function AdminUserTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { data: taUser, isLoading } = useQuery<TaUserOut | null>({
    queryKey: ["sa-tenant-admin-user", tenantId],
    queryFn: async () => {
      try {
        return await api.get<TaUserOut>(`/api/v1/tenants/${tenantId}/admin-user`);
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });

  const [form, setForm] = useState({ full_name: "", email: "" });

  const saveMutation = useMutation({
    mutationFn: (body: { full_name?: string; email?: string }) =>
      api.patch(`/api/v1/tenants/${tenantId}/admin-user`, body),
    onSuccess: () => {
      setConfirm(false);
      setError(null);
      setSuccess(t("common.success"));
      void qc.invalidateQueries({ queryKey: ["sa-tenant-admin-user", tenantId] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : t("common.error")),
  });

  if (isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!taUser) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa.admin_user_heading")}</h3>
        <p className="text-sm text-gray-400 italic">{t("sa.admin_user_no_ta")}</p>
      </div>
    );
  }

  const originalName = taUser.full_name;
  const originalEmail = taUser.email;
  const effectiveName = form.full_name || originalName;
  const effectiveEmail = form.email || originalEmail;

  function changedFields(): { full_name?: string; email?: string } {
    const body: { full_name?: string; email?: string } = {};
    if (effectiveName.trim() !== originalName) body.full_name = effectiveName.trim();
    if (effectiveEmail.trim().toLowerCase() !== originalEmail.toLowerCase()) body.email = effectiveEmail.trim();
    return body;
  }

  function handleSaveClick() {
    if (Object.keys(changedFields()).length === 0) {
      setSuccess(t("sa.admin_no_changes"));
      return;
    }
    setConfirm(true);
    setSuccess(null);
    setError(null);
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa.admin_user_heading")}</h3>

      <div className="flex flex-col gap-3 mb-6 max-w-md">
        <div>
          <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("sa.admin_user_name_label")}</label>
          <input type="text" value={effectiveName}
            onChange={(e) => { setForm((p) => ({ ...p, full_name: e.target.value })); setSuccess(null); }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f] focus:ring-1 focus:ring-[#0f2d1f]"
          />
        </div>
        <div>
          <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("sa.admin_user_email_label")}</label>
          <input type="email" value={effectiveEmail}
            onChange={(e) => { setForm((p) => ({ ...p, email: e.target.value })); setSuccess(null); }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-[#0f2d1f] focus:ring-1 focus:ring-[#0f2d1f]"
          />
        </div>
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {success && <p className="text-sm text-emerald-700 mb-3">{success}</p>}

      {confirm ? (
        <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
          <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
          <button type="button" disabled={saveMutation.isPending}
            onClick={() => saveMutation.mutate(changedFields())}
            className="px-3 py-1.5 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50">
            {saveMutation.isPending ? "…" : t("sa.admin_confirm_yes")}
          </button>
          <button type="button" disabled={saveMutation.isPending} onClick={() => setConfirm(false)}
            className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
            {t("sa.admin_confirm_no")}
          </button>
        </div>
      ) : (
        <button type="button"
          disabled={effectiveName === originalName && effectiveEmail.toLowerCase() === originalEmail.toLowerCase()}
          onClick={handleSaveClick}
          className="px-4 py-2 text-sm font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-40">
          {t("sa.admin_user_save_btn")}
        </button>
      )}
    </div>
  );
}
