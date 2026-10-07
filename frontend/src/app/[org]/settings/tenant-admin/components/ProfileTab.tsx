"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantAdminData } from "../types";

// Endonyms — each language shown in its own script, not translated (CLAUDE.md §12)
const LOCALES = [
  { code: "en", label: "English" },
  { code: "am", label: "አማርኛ" },
  { code: "or", label: "Afaan Oromoo" },
];

interface TermsAcceptanceOut {
  accepted_version: string | null;
  accepted_at: string | null;
  accepted_by_email: string | null;
  current_version: string;
}

function TermsAcceptanceLine({ tenantId }: { tenantId?: string }) {
  const path = tenantId ? `/api/v1/tenants/${tenantId}/terms-acceptance` : `/api/v1/tenants/me/terms-acceptance`;
  const { data } = useQuery<TermsAcceptanceOut>({
    queryKey: ["tenant-admin-terms-acceptance", tenantId ?? "me"],
    queryFn: () => api.get<TermsAcceptanceOut>(path),
    staleTime: 30_000,
  });

  if (!data) return null;

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {t("tenant_admin.terms.label")}
      </label>
      {data.accepted_version ? (
        <>
          <p className="text-sm text-gray-600">
            {t("tenant_admin.terms.accepted_line")
              .replace("{version}", data.accepted_version)
              .replace("{date}", data.accepted_at ? data.accepted_at.slice(0, 10) : "—")
              .replace("{email}", data.accepted_by_email ?? "—")}{" "}
            <Link href="/terms" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700 underline">
              ({t("tenant_admin.terms.view_link")})
            </Link>
          </p>
          {data.accepted_version !== data.current_version && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1 mt-1">
              {t("tenant_admin.terms.outdated_notice")}
            </p>
          )}
        </>
      ) : (
        <p className="text-sm text-gray-500">{t("tenant_admin.terms.no_record")}</p>
      )}
    </div>
  );
}

export function ProfileTab({ tenantId, isLoading }: TabProps) {
  const qc = useQueryClient();
  const [editMode, setEditMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // SA viewing another tenant: GET /{tenantId} already returns every field this
  // tab needs, so there is no separate /{tenantId}/profile read route (CLAUDE.md §15).
  const readPath = tenantId ? `/api/v1/tenants/${tenantId}` : `/api/v1/tenants/me/profile`;
  const writePath = tenantId ? `/api/v1/tenants/${tenantId}/profile` : `/api/v1/tenants/me/profile`;

  const { data: tenant, isLoading: loadingTenant } = useQuery<TenantAdminData>({
    queryKey: ["tenant-admin-profile", tenantId ?? "me"],
    queryFn: () => api.get<TenantAdminData>(readPath),
    staleTime: 30_000,
  });

  const [formData, setFormData] = useState({
    default_locale: tenant?.default_locale ?? "en",
  });

  const updateMutation = useMutation({
    mutationFn: (data: { default_locale: string }) => api.patch(writePath, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-admin-profile", tenantId ?? "me"] });
      setSuccess(t("common.success"));
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
          <h3 className="text-lg font-semibold text-gray-800">{t("sa.admin_sub_profile")}</h3>
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
              {t("tenant_admin.profile.slug")}
            </label>
            <p className="text-sm text-gray-600">{tenant.slug || "—"}</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("sa.edit_profile_field_org_type")}
            </label>
            <p className="text-sm text-gray-600">
              {tenant.organisation_type ? t(`wizard.org_types.${tenant.organisation_type}`) : "—"}
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {t("table.status")}
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
                {t(`sa.tenant_status_${(tenant.status || "ACTIVE").toLowerCase()}`)}
              </span>
            </p>
          </div>

          {/* Editable Locale */}
          {editMode ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t("sa.edit_profile_field_locale")}
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
                {t("sa.edit_profile_field_locale")}
              </label>
              <p className="text-sm text-gray-600">
                {LOCALES.find((l) => l.code === tenant.default_locale)?.label}
              </p>
            </div>
          )}

          <TermsAcceptanceLine tenantId={tenantId} />
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
