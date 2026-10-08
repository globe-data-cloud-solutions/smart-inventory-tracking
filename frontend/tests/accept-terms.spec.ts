/**
 * Playwright E2E — account-owner terms re-acceptance gate (feature (b))
 *
 * Covers: owner login with a stale terms_acceptance_required=true lands on
 * /accept-terms, accepting routes to the tenant dashboard, and a second
 * login (flag now false) goes straight to the dashboard.
 *
 * Run against both en and am locales. Chromium headless only, against
 * http://localhost:3000 — see CLAUDE.md §29 "Frontend verification".
 *
 * Requires TENANT_B_OWNER_EMAIL / TENANT_B_OWNER_PASSWORD env vars (set by
 * the session running the probe, after signing up zz-terms-b-<epoch> and
 * restarting auth/tenant with a bumped TERMS_VERSION) — skipped otherwise.
 *
 * Run:
 *   npx playwright test tests/accept-terms.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const OWNER_EMAIL    = process.env.TENANT_B_OWNER_EMAIL;
const OWNER_PASSWORD = process.env.TENANT_B_OWNER_PASSWORD;

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    lines.push(msg.text());
  });
  page.on("pageerror", (err) => lines.push(`[pageerror] ${err.message}`));
  return lines;
}

async function setLocaleBeforeLoad(page: Page, locale: "en" | "am") {
  await page.addInitScript((loc) => {
    window.localStorage.setItem("locale", loc);
  }, locale);
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Terms re-acceptance gate (${locale})`, () => {
    test(`owner is gated to /accept-terms, accepts, then logs in straight through (${locale})`, async ({ page }) => {
      test.skip(!OWNER_EMAIL || !OWNER_PASSWORD, "TENANT_B_OWNER_EMAIL/PASSWORD not set — skipping live probe");
      const consoleErrors = collectConsoleErrors(page);

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/login`);
      await page.fill('input[type="email"]', OWNER_EMAIL!);
      await page.fill('input[type="password"]', OWNER_PASSWORD!);
      await page.click('button[type="submit"]');

      await page.waitForURL(/\/accept-terms/);
      await page.screenshot({ path: "test-results/accept-terms-gate.png" });

      await page.click('button:has-text("Accept"), button:has-text("ተቀብለው")');
      await page.waitForURL(/\/[a-z0-9-]+\/dashboard/);

      // Logout and log back in — flag should now be false, straight to dashboard.
      await page.click('button:has-text("Sign"), button:has-text("ውጣ")');
      await page.waitForURL(/\/login/);

      await page.fill('input[type="email"]', OWNER_EMAIL!);
      await page.fill('input[type="password"]', OWNER_PASSWORD!);
      await page.click('button[type="submit"]');
      await page.waitForURL(/\/[a-z0-9-]+\/dashboard/);
      await expect(page).not.toHaveURL(/\/accept-terms/);

      console.log(`[${locale}] console errors:`, consoleErrors);
      expect(consoleErrors).toEqual([]);
    });
  });
}
