"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

interface RegistryStatusRow {
  id: string;
  name: string;
  status: string;
}

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: "bg-emerald-100 text-emerald-800",
  SUSPENDED: "bg-amber-100 text-amber-800",
  DEACTIVATED: "bg-red-100 text-red-700",
};

const STATUS_LABEL_KEY: Record<string, string> = {
  ACTIVE: "sa.tenant_status_active",
  SUSPENDED: "sa.tenant_status_suspended",
  DEACTIVATED: "sa.tenant_status_deactivated",
};

const CONFIRM_BODY_KEY: Record<"suspend" | "reactivate" | "deactivate", string> = {
  suspend: "sa.confirm_suspend",
  reactivate: "sa.confirm_reactivate",
  deactivate: "sa.confirm_deactivate",
};

export function StatusTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<"suspend" | "reactivate" | "deactivate" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: registry, isLoading } = useQuery<RegistryStatusRow[]>({
    queryKey: ["sa-registry-header"],
    queryFn: () => api.get<RegistryStatusRow[]>("/api/v1/tenants/sa/registry"),
    staleTime: 30_000,
  });

  const tenant = registry?.find((r) => r.id === tenantId);

  const actionMutation = useMutation({
    mutationFn: (action: "suspend" | "reactivate" | "deactivate") =>
      api.patch(`/api/v1/tenants/${tenantId}/${action}`, {}),
    onSuccess: () => {
      setConfirm(null);
      setError(null);
      void qc.invalidateQueries({ queryKey: ["sa-registry-header"] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : t("common.error")),
  });

  if (isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!tenant) {
    return <div className="flex items-center justify-center py-12 text-red-600">{t("common.error")}</div>;
  }

  const status = tenant.status || "ACTIVE";

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa.admin_status_heading")}</h3>

      <div className="mb-5">
        <span className={`text-xs font-bold px-2.5 py-0.5 rounded ${STATUS_BADGE[status] ?? "bg-gray-100 text-gray-700"}`}>
          {STATUS_LABEL_KEY[status] ? t(STATUS_LABEL_KEY[status]) : status}
        </span>
      </div>

      <div className="flex gap-3 mb-5">
        {status === "ACTIVE" && (
          <button type="button"
            onClick={() => { setConfirm("suspend"); setError(null); }}
            className="px-4 py-2 text-sm font-bold text-white bg-amber-500 rounded hover:bg-amber-600">
            {t("sa.action_suspend")}
          </button>
        )}
        {status !== "ACTIVE" && (
          <button type="button"
            onClick={() => { setConfirm("reactivate"); setError(null); }}
            className="px-4 py-2 text-sm font-bold text-white bg-emerald-600 rounded hover:bg-emerald-700">
            {t("sa.action_reactivate")}
          </button>
        )}
        {status !== "DEACTIVATED" && (
          <button type="button"
            onClick={() => { setConfirm("deactivate"); setError(null); }}
            className="px-4 py-2 text-sm font-bold text-white bg-red-600 rounded hover:bg-red-700">
            {t("sa.action_deactivate")}
          </button>
        )}
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {confirm && (
        <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
          <span className="text-sm text-gray-700 flex-1">
            {t(CONFIRM_BODY_KEY[confirm]).replace("{name}", tenant.name)}
          </span>
          <button type="button" disabled={actionMutation.isPending}
            onClick={() => actionMutation.mutate(confirm)}
            className={`px-3 py-1.5 text-xs font-bold text-white rounded disabled:opacity-50 ${
              confirm === "deactivate" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"
            }`}>
            {actionMutation.isPending ? "…" : t("sa.admin_confirm_yes")}
          </button>
          <button type="button" disabled={actionMutation.isPending} onClick={() => setConfirm(null)}
            className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
            {t("sa.admin_confirm_no")}
          </button>
        </div>
      )}
    </div>
  );
}
