"use client";

import { useAuth } from "@/hooks/useAuth";
import { usePermission as checkPermission } from "@/lib/permissions";

// WARNING: controls UI visibility only. Backend enforces all permissions independently.
export function usePermission(actionId: string): boolean {
  const { user } = useAuth();
  if (!user) return false;
  return checkPermission(actionId, user.role);
}
