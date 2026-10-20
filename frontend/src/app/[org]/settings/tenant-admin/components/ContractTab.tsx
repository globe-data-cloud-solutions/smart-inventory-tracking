"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantAdminData } from "../types";
import { formatDate } from "@/lib/format";

interface SubscriptionBillingPeriod {
  billing_period: string | null;
}

function BillingPeriodLine({ tenantId }: { tenantId?: string }) {
  const subPath = tenantId ? `/api/v1/tenants/${tenantId}/subscription` : `/api/v1/tenants/me/subscription`;
  const { data: subscription } = useQuery<SubscriptionBillingPeriod>({
    queryKey: ["tenant-admin-subscription", tenantId ?? "me"],
    queryFn: () => api.get<SubscriptionBillingPeriod>(subPath),
    staleTime: 30_000,
  });

  const periodLabel = subscription?.billing_period === "ANNUAL"
    ? t("tenant_admin.billing.annual")
    : subscription?.billing_period === "MONTHLY"
      ? t("tenant_admin.billing.monthly")
      : "—";

  return (
    <div>
      <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.contract.billing_period_label")}</p>
      <p className="text-lg font-semibold text-gray-800">{periodLabel}</p>
    </div>
  );
}

function ContractEditForm({ tenantId, tenant }: { tenantId: string; tenant: TenantAdminData }) {
  const qc = useQueryClient();
  const [start, setStart] = useState(tenant.contract_start ?? "");
  const [end, setEnd] = useState(tenant.contract_end ?? "");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => api.patch(`/api/v1/tenants/${tenantId}/contract`, {
      contract_start: start || null,
      contract_end: end || null,
      note,
    }),
    onSuccess: () => {
      setConfirm(false);
      setError(null);
      setSuccess(t("common.success"));
      void qc.invalidateQueries({ queryKey: ["tenant-admin-contract", tenantId] });
      void qc.invalidateQueries({ queryKey: ["sa-registry-header"] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : t("common.error")),
  });

  function handleSaveClick() {
    const trimmedNote = note.trim();
    if (!trimmedNote) {
      setError(t("sa.edit_contract_note_required"));
      return;
    }
    setConfirm(true);
    setSuccess(null);
    setError(null);
  }

  const hasChanges = start !== (tenant.contract_start ?? "") || end !== (tenant.contract_end ?? "");

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa.admin_sub_contract")}</h3>

      <div className="grid grid-cols-2 gap-3 mb-4 max-w-md">
        <div>
          <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("wizard.contract_start")}</label>
          <input type="date" value={start}
            onChange={(e) => { setStart(e.target.value); setSuccess(null); }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div>
          <label className="block text-[12px] font-semibold text-gray-600 mb-1">{t("wizard.contract_end")}</label>
          <input type="date" value={end}
            onChange={(e) => { setEnd(e.target.value); setSuccess(null); }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
      </div>

      {end && end < new Date().toISOString().slice(0, 10) && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2 mb-4 max-w-md">
          {t("sa.edit_contract_warning_past")}
        </p>
      )}

      <div className="mb-4 max-w-md">
        <label className="block text-[12px] font-semibold text-gray-600 mb-1">
          {t("sa.edit_contract_note_label")} <span className="text-red-500">*</span>
        </label>
        <textarea rows={3} value={note}
          placeholder={t("sa.edit_contract_note_placeholder")}
          onChange={(e) => { setNote(e.target.value); setSuccess(null); setError(null); }}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 resize-none"
        />
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {success && <p className="text-sm text-emerald-700 mb-3">{success}</p>}

      {confirm ? (
        <div className="flex items-center gap-3 p-3 bg-gray-50 rounded border border-gray-200">
          <span className="text-sm text-gray-700 flex-1">{t("sa.admin_confirm_prompt")}</span>
          <button type="button" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}
            className="px-3 py-1.5 text-xs font-bold text-white bg-sky-600 rounded hover:bg-sky-700 disabled:opacity-50">
            {saveMutation.isPending ? "…" : t("sa.admin_confirm_yes")}
          </button>
          <button type="button" disabled={saveMutation.isPending} onClick={() => setConfirm(false)}
            className="px-3 py-1.5 text-xs font-bold text-gray-600 rounded hover:bg-gray-200">
            {t("sa.admin_confirm_no")}
          </button>
        </div>
      ) : (
        <button type="button" disabled={!hasChanges} onClick={handleSaveClick}
          className="px-4 py-2 text-sm font-bold text-white bg-sky-600 rounded hover:bg-sky-700 disabled:opacity-50">
          {t("sa.admin_save_btn")}
        </button>
      )}
    </div>
  );
}

export function ContractTab({ tenantId, isLoading }: TabProps) {
  const readPath = tenantId ? `/api/v1/tenants/${tenantId}` : `/api/v1/tenants/me/profile`;

  const { data: tenant, isLoading: loadingTenant } = useQuery<TenantAdminData>({
    queryKey: ["tenant-admin-contract", tenantId ?? "me"],
    queryFn: () => api.get<TenantAdminData>(readPath),
    staleTime: 30_000,
  });

  if (loadingTenant || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  if (!tenant) {
    return <div className="flex items-center justify-center py-12 text-red-600">{t("common.error")}</div>;
  }

  const contractStart = tenant.contract_start ? new Date(tenant.contract_start) : null;
  const contractEnd = tenant.contract_end ? new Date(tenant.contract_end) : null;
  const today = new Date();
  const daysLeft = contractEnd ? Math.ceil((contractEnd.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)) : null;
  const isExpired = daysLeft !== null && daysLeft < 0;
  const expiringsSoon = daysLeft !== null && daysLeft >= 0 && daysLeft <= 30;

  return (
    <div className="space-y-6">
      {/* Status Card — contract dates (the commercial agreement) and billing period
          (the subscription's billing cycle) are shown separately: they are
          independent of each other (CLAUDE.md §15 decision B). */}
      <div className={`rounded-lg border p-6 ${isExpired ? "bg-red-50 border-red-200" : expiringsSoon ? "bg-amber-50 border-amber-200" : "bg-white border-gray-200"}`}>
        <div className="flex items-start justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">{t("tenant_admin.contract.status_title")}</h3>
        </div>

        {isExpired && (
          <div className="mb-4 p-3 bg-red-100 border border-red-300 rounded text-sm text-red-900">
            {t("tenant_admin.contract.expired_warning")}
          </div>
        )}

        {expiringsSoon && (
          <div className="mb-4 p-3 bg-amber-100 border border-amber-300 rounded text-sm text-amber-900">
            {t("tenant_admin.contract.expiring_soon_warning").replace("{n}", String(daysLeft))}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.contract.start_date")}</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractStart ? formatDate(contractStart) : "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.contract.end_date")}</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractEnd ? formatDate(contractEnd) : "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.contract.days_remaining")}</p>
            <p className={`text-lg font-semibold ${isExpired ? "text-red-700" : expiringsSoon ? "text-amber-700" : "text-green-700"}`}>
              {daysLeft === null
                ? "—"
                : isExpired
                  ? t("tenant_admin.contract.expired_days_ago").replace("{n}", String(Math.abs(daysLeft)))
                  : t("tenant_admin.contract.days_suffix").replace("{n}", String(daysLeft))}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.contract.duration")}</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractStart && contractEnd
                ? t("tenant_admin.contract.years_suffix").replace(
                    "{n}",
                    String(Math.round((contractEnd.getTime() - contractStart.getTime()) / (1000 * 60 * 60 * 24 * 365)))
                  )
                : "—"}
            </p>
          </div>
          <BillingPeriodLine tenantId={tenantId} />
        </div>
      </div>

      {tenantId ? (
        <ContractEditForm tenantId={tenantId} tenant={tenant} />
      ) : (
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-900">{t("tenant_admin.contract.managed_by_platform")}</p>
        </div>
      )}
    </div>
  );
}
