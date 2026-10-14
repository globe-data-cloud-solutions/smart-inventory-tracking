import type { Page } from "@playwright/test";

/**
 * Patch the ROLE (and optionally the warehouse) in the browser's client session
 * (localStorage "smart_demo_session"), after the real TA probe login. Client-side
 * only: no new login, no credentials, no backend write — the same approach the
 * lot-receive / transfer-lots specs use for warehouseId. All API traffic in the
 * specs that use this is answered by page.route() stubs, so the server never
 * sees the patched role.
 *
 * Call it after login() and before navigating to the page under test.
 */
export async function asRole(page: Page, role: string, warehouseId?: string): Promise<void> {
  await page.evaluate(
    ([r, wh]) => {
      const raw = window.localStorage.getItem("smart_demo_session");
      if (!raw) return;
      const session = JSON.parse(raw) as Record<string, unknown>;
      session.role = r;
      if (wh) session.warehouseId = wh;
      window.localStorage.setItem("smart_demo_session", JSON.stringify(session));
    },
    [role, warehouseId ?? ""] as const,
  );
}
