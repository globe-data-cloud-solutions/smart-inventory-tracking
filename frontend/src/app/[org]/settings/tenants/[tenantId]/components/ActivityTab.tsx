"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/format";

interface TenantActivityRow {
  id: string;
  action: string;
  old_value: string | null;
  new_value: string | null;
  note: string | null;
  actor_email: string | null;
  actor_id: string;
  created_at: string;
}

export function ActivityTab({ tenantId }: { tenantId: string }) {
  const { data: activityLog, isLoading } = useQuery<TenantActivityRow[]>({
    queryKey: ["sa-tenant-activity", tenantId],
    queryFn: () => api.get<TenantActivityRow[]>(`/api/v1/tenants/sa/${tenantId}/activity`),
    staleTime: 15_000,
  });

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">{t("sa.activity_heading")}</h3>

      {isLoading && <p className="text-gray-400 text-sm">{t("common.loading")}</p>}
      {!isLoading && (!activityLog || activityLog.length === 0) && (
        <p className="text-gray-400 text-sm">{t("sa.activity_empty")}</p>
      )}
      {!isLoading && activityLog && activityLog.map((entry, idx) => (
        <div key={entry.id}>
          <div className="py-3">
            <p className="m-0 font-semibold text-gray-800 text-sm">
              {(() => {
                const actionKey = `sa.activity_action_${entry.action}`;
                const translated = t(actionKey);
                return translated !== actionKey ? translated : entry.action;
              })()}
            </p>
            {entry.old_value && entry.new_value && (
              <p className="m-0 text-xs text-gray-500 mt-0.5">
                {entry.old_value} → {entry.new_value}
              </p>
            )}
            <p className="m-0 text-xs text-gray-400 mt-0.5">
              {t("sa.activity_by")} {entry.actor_email ?? entry.actor_id}
            </p>
            <p className="m-0 text-xs text-gray-400">
              {formatDateTime(entry.created_at)}
            </p>
            {entry.note && (
              <p className="m-0 text-xs text-gray-500 italic mt-1">{entry.note}</p>
            )}
          </div>
          {activityLog && idx < activityLog.length - 1 && (
            <hr className="border-gray-100 m-0" />
          )}
        </div>
      ))}
    </div>
  );
}
