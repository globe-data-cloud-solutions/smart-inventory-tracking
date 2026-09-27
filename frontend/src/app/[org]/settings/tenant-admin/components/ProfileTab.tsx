"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantAdminData } from "../types";

const LOCALES = [
  { code: "en", label: "English" },
  { code: "am", label: "አማርኛ (Amharic)" },
  { code: "or", label: "Afaan Oromoo (Oromifa)" },
];

export function ProfileTab({ tenantId, isLoading }: TabProps) {
  const qc = useQueryClient();
  const [editMode, setEditMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { data: tenant, isLoading: loadingTenant } = useQuery<TenantAdminData>({
    queryKey: ["tenant-admin-profile", tenantId],
    queryFn: () => api.get<TenantAdminData>(`/api/v1/tenants/${tenantId}`),
    staleTime: 30_000,
  });

  const [formData, setFormData] = useState({
    default_locale: tenant?.default_locale ?? "en",
  });

  const updateMutation = useMutation({
    mutationFn: (data: { default_locale: string }) =>
      api.patch(`/api/v1/tenants/${tenantId}/profile`, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-admin-profile", tenantId] });
      setSuccess(t("common.saved_successfully"));
      setEditMode(false);
      setError(null);
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : t("common.error"));
      setSuccess(null);
    },
  });

  if (loadingTenant || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!tenant) {
    return <div className="flex items-center justify-center py-12 text-red-600">{t("common.error")}</div>;
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold text-gray-800">{t("layout.profile")}</h3>
          {!editMode && (
            <button
              onClick={() => {
                setFormData({ default_locale: tenant.default_locale ?? "en" });
                setEditMode(true);
              }}
              className="text-sm font-semibold text-blue-600 hover:text-blue-700"
            >
              {t("common.edit")}
            </button>
          )}
        </div>

        {/* Display Fields (Read-only) */}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("dashboard.tenant_name")}
            </label>
            <p className="text-sm text-gray-600">{tenant.name}</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Slug
            </label>
            <p className="text-sm text-gray-600">{tenant.slug || "—"}</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("wizard.org_type")}
            </label>
            <p className="text-sm text-gray-600">{tenant.organisation_type || "—"}</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Status
            </label>
            <p className="text-sm">
              <span
                className={`inline-block px-2 py-1 rounded text-xs font-semibold ${
                  tenant.status === "SUSPENDED"
                    ? "bg-red-100 text-red-800"
                    : tenant.status === "DEACTIVATED"
                      ? "bg-gray-100 text-gray-800"
                      : "bg-green-100 text-green-800"
                }`}
              >
                {tenant.status || "ACTIVE"}
              </span>
            </p>
          </div>

          {/* Editable Locale */}
          {editMode ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t("settings.default_language")}
              </label>
              <select
                value={formData.default_locale}
                onChange={(e) => setFormData({ ...formData, default_locale: e.target.value })}
                className="w-full max-w-sm px-3 py-2 border border-gray-300 rounded-md text-sm"
              >
                {LOCALES.map((loc) => (
                  <option key={loc.code} value={loc.code}>
                    {loc.label}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t("settings.default_language")}
              </label>
              <p className="text-sm text-gray-600">
                {LOCALES.find((l) => l.code === tenant.default_locale)?.label}
              </p>
            </div>
          )}
        </div>

        {/* Action Buttons (Edit Mode) */}
        {editMode && (
          <div className="flex gap-3 mt-6 pt-6 border-t border-gray-200">
            <button
              onClick={() => {
                setFormData({ default_locale: tenant.default_locale ?? "en" });
                setEditMode(false);
                setError(null);
              }}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50"
            >
              {t("common.cancel")}
            </button>
            <button
              onClick={() => updateMutation.mutate(formData)}
              disabled={updateMutation.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {updateMutation.isPending ? t("common.saving") : t("common.save")}
            </button>
          </div>
        )}

        {/* Messages */}
        {error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            {error}
          </div>
        )}
        {success && (
          <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded text-sm text-green-700">
            {success}
          </div>
        )}
      </div>
    </div>
  );
}
