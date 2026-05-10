"use client";

import { getSession } from "@/lib/demo-auth";
import { usePermission as checkPermission } from "@/lib/permissions";

// WARNING: controls UI visibility only. Backend enforces all permissions independently.
export function usePermission(actionId: string): boolean {
  const session = getSession();
  if (!session) return false;
  return checkPermission(actionId, session.role);
}
