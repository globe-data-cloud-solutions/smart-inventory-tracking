import { t, hasKey } from "@/lib/i18n";

/**
 * Translated message for an API error whose code has an errors.<CODE> entry,
 * else null. Screens call this before falling back to the generic "An
 * unexpected error occurred", so a permission denial (RBAC_DENIED,
 * ABAC_DENIED, TENANT_ACCESS_DENIED, NOT_YOUR_NODE…) shows its own message.
 *
 * api.ts has already built err.message from the same key with the detail
 * fields filled in, so that message is preferred; t() is the fallback.
 */
export function knownErrorMessage(err: unknown): string | null {
  const raw = (err as { code?: string } | null | undefined)?.code ?? "";
  const code = raw.split(":")[0]?.trim() ?? "";
  if (!code || !hasKey(`errors.${code}`)) return null;
  const message = err instanceof Error ? err.message : "";
  return message || t(`errors.${code}`);
}
