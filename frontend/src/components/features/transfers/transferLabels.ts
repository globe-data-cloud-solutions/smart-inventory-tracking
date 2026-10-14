/**
 * Shared transfer labels — status text, type text and {placeholder} interpolation —
 * used by the Transfers list page and the transfer detail page.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { codeLabel } from "@/components/features/transfers/TransferLotDetails";
import { transferTypesKey } from "@/components/features/transfers/transferQueryKeys";

export type UnderlyingTransferType = "PULL" | "PUSH" | "SISTER";

/** One row of GET /api/v1/tenants/{tenantId}/transfer-types. */
export interface TenantTransferType {
  id: string;
  underlying_type: UnderlyingTransferType;
  display_name: string;
  is_active: boolean;
}

/** t(key) with {name}-style placeholders replaced. */
export function tf(key: string, params: Record<string, string | number>): string {
  let out = t(key);
  for (const [name, value] of Object.entries(params)) out = out.split(`{${name}}`).join(String(value));
  return out;
}

/** Translated status label (never the raw PENDING_REVIEW-style code). */
export function transferStatusLabel(status: string): string {
  return codeLabel("transfers.view.status", status);
}

/** Generic (non-tenant) type label, e.g. "Pull request". */
export function genericTransferTypeLabel(type: string): string {
  return codeLabel("transfers.view.type", type);
}

/**
 * The tenant's own name for a type (active config only), else the translated generic label.
 * `types` is empty in demo mode (no API call), which gives the generic label.
 */
export function transferTypeLabel(type: string, types: TenantTransferType[] | undefined): string {
  const name = types?.find((tt) => tt.underlying_type === type && tt.is_active)?.display_name;
  return name || genericTransferTypeLabel(type);
}

/**
 * Tenant transfer-type configs. One query key (transferTypesKey) is shared by the list and
 * detail pages. Gateway mode only — demo mode makes no call.
 */
export function useTransferTypes(tenantId: string): TenantTransferType[] {
  const isGateway = !!process.env.NEXT_PUBLIC_API_URL;
  const { data = [] } = useQuery<TenantTransferType[]>({
    queryKey: transferTypesKey(tenantId),
    queryFn:  () => api.get<TenantTransferType[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    enabled:  isGateway && !!tenantId,
    staleTime: 60_000,
  });
  return data;
}
