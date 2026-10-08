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
