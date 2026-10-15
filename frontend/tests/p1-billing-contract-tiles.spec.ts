/**
 * Playwright E2E — P1: Plan tab shows separate "Billing period" and
 * "Contract" tiles (CLAUDE.md session/2026-10-11).
 *
 * Read-only against the real backend with zz-e2e-ta — no writes, no route
 * interception. Chromium headless only, against http://localhost:3000.
 * Run: npx playwright test tests/p1-billing-contract-tiles.spec.ts --workers=1
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    lines.push(msg.text());
  });
  page.on("pageerror", (err) => lines.push(`[pageerror] ${err.message}`));
  return lines;
}

async function login(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(admin|[a-z0-9-]+)\/dashboard/);
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Plan tab — Billing period + Contract tiles (${locale})`, () => {
    test(`renders with no raw i18n keys and no console errors (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.waitForLoadState("networkidle");

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=plan`);
      await page.waitForLoadState("networkidle");

      const billingTile = page.getByText(/^(Billing period|የክፍያ ጊዜ)$/);
      const contractTile = page.getByText(/^(Contract|ውል)$/);
      await expect(billingTile.first()).toBeVisible({ timeout: 10_000 });
      await expect(contractTile.first()).toBeVisible({ timeout: 10_000 });

      // Never a raw i18n key or raw dates placeholder as visible text.
      await expect(page.getByText(/tenant_admin\.billing\./)).toHaveCount(0);

      await page.screenshot({ path: `test-results/p1/plan-tab-billing-contract-${locale}.png`, fullPage: true });

      console.log(`--- Plan tab billing/contract tiles (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
