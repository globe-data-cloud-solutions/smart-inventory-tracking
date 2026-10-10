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

export interface GuardProps {
  disabled: boolean;
  title?: string;
  "aria-disabled"?: true;
}

/**
 * Spreadable props for a single write control: `<button {...guardProps(guard)}>`.
 * disabled mirrors the existing disabled styling already on these controls —
 * this never introduces new CSS, only decides when disabled applies. A
 * disabled control must never open its panel/modal; a panel already open
 * must show guard.reason() at the top and disable its own submit the same way.
 */
export function guardProps(guard: WriteGuard, resource?: PlanResource): GuardProps {
  const reason = guard.reason(resource);
  if (!reason) return { disabled: false };
  return { disabled: true, title: reason, "aria-disabled": true };
}
