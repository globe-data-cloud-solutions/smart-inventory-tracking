// Shared renderer for the FEATURE_NOT_IN_PLAN 402 (plan_middleware.py's
// ACTION_FLAG_MAP) — used by any screen where a save can be rejected because
// the tenant's plan doesn't include the feature. Never show the raw error or
// [object Object]; always route through planFeatureErrorMessage().
import { t } from "@/lib/i18n";

const TIER_KEYS: Record<string, string> = {
  STARTER: "tenant_admin.plan.tier.STARTER",
  GROWTH: "tenant_admin.plan.tier.GROWTH",
  ENTERPRISE: "tenant_admin.plan.tier.ENTERPRISE",
};

export function tierLabel(tier: string): string {
  const key = TIER_KEYS[tier];
  return key ? t(key) : tier;
}

export interface PlanFeatureErrorInfo {
  code?: string;
  feature?: string;
  upgradeTo?: string | null;
}

export function isPlanFeatureError(e: unknown): e is PlanFeatureErrorInfo {
  return !!e && typeof e === "object" && (e as PlanFeatureErrorInfo).code === "FEATURE_NOT_IN_PLAN";
}

// Mirrors backend/shared/permissions/plan_middleware.py's _UPGRADE_TO — used
// to show the right upgrade target when the frontend already has plan_tier
// but no 402 body (e.g. gating a form before any save is attempted).
export const PLAN_UPGRADE_TO: Record<string, string | null> = {
  STARTER: "GROWTH",
  GROWTH: "ENTERPRISE",
  ENTERPRISE: null,
};

export function planFeatureErrorMessage(info: PlanFeatureErrorInfo): string {
  let msg = t("plan.feature_not_in_plan");
  if (info.upgradeTo) {
    msg += " " + t("plan.upgrade_to").replace("{tier}", tierLabel(info.upgradeTo));
  }
  return msg;
}

// PLAN_LIMIT_REACHED (402, plan_middleware.py / product-service create_product) —
// resource is "skus" | "users" | "warehouses". api.ts already sets err.message
// to the friendly translated text; these helpers just let a caller branch on
// the error shape without string-matching err.message.
export interface PlanLimitErrorInfo {
  code?: string;
  resource?: string;
  limit?: number | null;
}

export function isPlanLimitError(e: unknown): e is PlanLimitErrorInfo {
  return !!e && typeof e === "object" && (e as PlanLimitErrorInfo).code === "PLAN_LIMIT_REACHED";
}

// CONTRACT_EXPIRED_READ_ONLY (402, shared/permissions/middleware.py) — raised
// on a write action once the tenant's contract has been in READ_ONLY stage.
export interface ContractReadOnlyErrorInfo {
  code?: string;
  contractEnd?: string | null;
  readOnlySince?: string | null;
}

export function isContractReadOnlyError(e: unknown): e is ContractReadOnlyErrorInfo {
  return !!e && typeof e === "object" && (e as ContractReadOnlyErrorInfo).code === "CONTRACT_EXPIRED_READ_ONLY";
}
