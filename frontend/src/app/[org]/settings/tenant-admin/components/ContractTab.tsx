"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantAdminData } from "../types";

export function ContractTab({ tenantId, isLoading }: TabProps) {
  const qc = useQueryClient();
  const [showRenewalModal, setShowRenewalModal] = useState(false);
  const [renewalData, setRenewalData] = useState({
    new_end_date: "",
    reason: "",
    notes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { data: tenant, isLoading: loadingTenant } = useQuery<TenantAdminData>({
    queryKey: ["tenant-admin-contract", tenantId],
    queryFn: () => api.get<TenantAdminData>(`/api/v1/tenants/${tenantId}`),
    staleTime: 30_000,
  });

  const renewalMutation = useMutation({
    mutationFn: (data: { contract_end: string; note: string }) =>
      api.patch(`/api/v1/tenants/${tenantId}/contract`, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-admin-contract", tenantId] });
      setSuccess("Contract renewed successfully!");
      setShowRenewalModal(false);
      setRenewalData({ new_end_date: "", reason: "", notes: "" });
      setError(null);
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : t("common.error"));
    },
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
          <h3 className="text-lg font-semibold text-gray-800">Contract Status</h3>
          {!isExpired && (
            <button
              onClick={() => setShowRenewalModal(true)}
              className="text-sm font-semibold text-blue-600 hover:text-blue-700"
            >
              Renew Contract
            </button>
          )}
        </div>

        {isExpired && (
          <div className="mb-4 p-3 bg-red-100 border border-red-300 rounded text-sm text-red-900">
            ⚠️ Your contract has expired. Please renew immediately to restore full access.
          </div>
        )}

        {expiringsSoon && (
          <div className="mb-4 p-3 bg-amber-100 border border-amber-300 rounded text-sm text-amber-900">
            ⏰ Your contract is expiring in {daysLeft} days. Renew now to avoid service interruption.
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <p className="text-sm text-gray-600 mb-1">Start Date</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractStart ? contractStart.toLocaleDateString() : "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">End Date</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractEnd ? contractEnd.toLocaleDateString() : "—"}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">Days Remaining</p>
            <p className={`text-lg font-semibold ${isExpired ? "text-red-700" : expiringsSoon ? "text-amber-700" : "text-green-700"}`}>
              {daysLeft === null ? "—" : isExpired ? `Expired ${Math.abs(daysLeft)} days ago` : `${daysLeft} days`}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">Duration</p>
            <p className="text-lg font-semibold text-gray-800">
              {contractStart && contractEnd
                ? `${Math.round((contractEnd.getTime() - contractStart.getTime()) / (1000 * 60 * 60 * 24 * 365))} years`
                : "—"}
            </p>
          </div>
        </div>
      </div>

      {/* Renewal Modal */}
      {showRenewalModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">Renew Contract</h3>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  New End Date <span className="text-red-600">*</span>
                </label>
                <input
                  type="date"
                  value={renewalData.new_end_date}
                  onChange={(e) => setRenewalData({ ...renewalData, new_end_date: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  min={new Date().toISOString().split("T")[0]}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Reason <span className="text-red-600">*</span>
                </label>
                <select
                  value={renewalData.reason}
                  onChange={(e) => setRenewalData({ ...renewalData, reason: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                >
                  <option value="">Select a reason</option>
                  <option value="annual_renewal">Annual Renewal</option>
                  <option value="multi_year_extension">Multi-year Extension</option>
                  <option value="contract_expansion">Contract Expansion</option>
                  <option value="other">Other</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Additional Notes
                </label>
                <textarea
                  value={renewalData.notes}
                  onChange={(e) => setRenewalData({ ...renewalData, notes: e.target.value })}
                  placeholder="Any special terms or details..."
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                />
              </div>

              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                  {error}
                </div>
              )}

              <div className="flex gap-3 pt-4 border-t border-gray-200">
                <button
                  onClick={() => {
                    setShowRenewalModal(false);
                    setRenewalData({ new_end_date: "", reason: "", notes: "" });
                    setError(null);
                  }}
                  className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (!renewalData.new_end_date || !renewalData.reason) {
                      setError("Please fill in all required fields");
                      return;
                    }
                    renewalMutation.mutate({
                      contract_end: renewalData.new_end_date,
                      note: `Reason: ${renewalData.reason}. Notes: ${renewalData.notes}`,
                    });
                  }}
                  disabled={renewalMutation.isPending}
                  className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {renewalMutation.isPending ? "Renewing..." : "Renew"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {success && (
        <div className="p-4 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
          ✅ {success}
        </div>
      )}

      {/* Info Box */}
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-sm text-blue-900">
          <strong>Note:</strong> Contract renewal requires approval from your system administrator. Your renewal request will be processed within 1-2 business days.
        </p>
      </div>
    </div>
  );
}
