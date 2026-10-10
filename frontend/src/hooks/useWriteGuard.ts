"use client";

import { t } from "@/lib/i18n";
import { useContractStatus } from "./useContractStatus";
import { usePlanUsage, type PlanUsage } from "./usePlanUsage";

export type PlanResource = keyof Pick<PlanUsage, "skus" | "users" | "warehouses">;

export interface WriteGuard {
  readOnly: boolean;
  atLimit: (resource: PlanResource) => boolean;
  reason: (resource?: PlanResource) => string | null;
}

/**
 * Combines contract stage (useContractStatus) and resource usage
 * (usePlanUsage) into a single UI guard for disabling write actions and
 * showing a tooltip reason. Used by P5/P6 — nothing else wires to this yet.
 */
export function useWriteGuard(): WriteGuard {
  const { contractStatus } = useContractStatus();
  const { planUsage } = usePlanUsage();

  const readOnly = contractStatus?.stage === "READ_ONLY";

  function atLimit(resource: PlanResource): boolean {
    if (!planUsage) return false;
    const r = planUsage[resource];
    return r.limit !== null && r.used >= r.limit;
  }

  function reason(resource?: PlanResource): string | null {
    if (readOnly) return t("contract.read_only_error");
    if (resource && atLimit(resource)) return t(`plan.limit_reached.${resource}`);
    return null;
  }

  return { readOnly, atLimit, reason };
}
