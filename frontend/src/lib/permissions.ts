// WARNING: controls UI visibility only. Backend enforces all permissions independently.
// Never rely on this for security decisions.

const ROLE_HIERARCHY: Record<string, number> = {
  SA:    10,
  TA:    9,
  NM:    8,
  RM:    7,
  WM:    6,
  LM:    6,
  SA_GT: 4,
  RT:    3,
  AU:    2,
  SYS:   1,
};

const ROLE_PERMISSIONS: Record<string, string[]> = {
  SA:  ["*"], // all actions
  TA:  ["tenant:*", "user:*", "product:*", "inventory:*", "order:*", "report:*", "audit:*"],
  NM:  ["product:*", "inventory:*", "order:*", "report:*", "dispatch:configure"],
  RM:  ["inventory:*", "transfer:*", "adjustment:approve", "order:*", "report:*"],
  WM:  ["inventory:receive", "inventory:adjust", "inventory:transfer", "inventory:cycle_count",
        "transfer:create", "transfer:submit", "count:*", "scan:*", "report:low_stock"],
  LM:  ["logistics:*", "order:ship", "transfer:dispatch"],
  SA_GT:["scan:*", "inventory:receive", "inventory:issue"],
  RT:  ["inventory:view_balance", "report:low_stock", "scan:barcode_lookup"],
  AU:  ["audit:view_logs", "report:*", "inventory:view_ledger"],
  SYS: ["ai:model_run", "system:*"],
};

export function usePermission(actionId: string, role: string): boolean {
  const perms = ROLE_PERMISSIONS[role] ?? [];
  if (perms.includes("*")) return true;

  const [domain, action] = actionId.split(":");
  return (
    perms.includes(actionId) ||
    perms.includes(`${domain}:*`)
  );
}

export function getRoleLevel(role: string): number {
  return ROLE_HIERARCHY[role] ?? 0;
}

export function canAssignRole(actorRole: string, targetRole: string): boolean {
  return getRoleLevel(actorRole) > getRoleLevel(targetRole);
}
