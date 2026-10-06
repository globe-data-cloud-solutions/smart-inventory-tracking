"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantAdminData } from "../types";

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
      {/* Status Card */}
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
              {contractStart ? contractStart.toLocaleDateString() : "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">{t("tenant_admin.contract.end_date")}</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractEnd ? contractEnd.toLocaleDateString() : "—"}
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
        </div>
      </div>

      {/* Info Note — contract dates are platform-managed; TA has no write path here.
          SA edits contract dates from the SA dashboard's Admin tab (PATCH /{tenant_id}/contract) —
          link there rather than duplicating that edit form (CLAUDE.md §15). */}
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-sm text-blue-900">
          {tenantId ? t("sa_tenant.contract.edit_elsewhere") : t("tenant_admin.contract.managed_by_platform")}
        </p>
        {tenantId && (
          <Link href="/admin/dashboard" className="text-sm font-semibold text-blue-700 hover:underline mt-1 inline-block">
            {t("sa_tenant.open_dashboard_admin_link")}
          </Link>
        )}
      </div>
    </div>
  );
}
