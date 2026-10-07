/**
 * Playwright E2E — S10 add-ons, post-login JWT race fix, e2e TA account.
 *
 * Chromium headless only, against http://localhost:3000. See CLAUDE.md §29
 * "Browser verification". Screenshots go to
 * frontend/test-results/screens/s10/ (gitignored).
 *
 * Run:
 *   npx playwright test tests/s10-addons.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const SA_EMAIL = "smartadmin@smart-inventory.com";
const SA_PASSWORD = "Admin@2026";

test.setTimeout(60_000);

function collectConsole(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => lines.push(`[${msg.type()}] ${msg.text()}`));
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

test.describe("S10-1 post-login JWT race fix", () => {
  for (let i = 1; i <= 5; i++) {
    test(`fresh SA login #${i} -> dashboard, zero 401s`, async ({ page }) => {
      const consoleLines = collectConsole(page);
      const apiErrors: string[] = [];
      page.on("response", (res) => {
        if (res.status() === 401) apiErrors.push(`401: ${res.url()}`);
      });

      await login(page, SA_EMAIL, SA_PASSWORD);
      // Give any in-flight dashboard queries a moment to settle.
      await page.waitForLoadState("networkidle");

      console.log(`--- run #${i} console messages ---`);
      for (const line of consoleLines) console.log(line);
      console.log(`--- run #${i} 401 responses: ${apiErrors.length} ---`);
      for (const e of apiErrors) console.log(e);

      expect(apiErrors, `run #${i} should have zero 401s`).toHaveLength(0);
    });
  }
});

test.describe("S10-1 permanent e2e TA account", () => {
  test("TA login with zz-e2e-ta -> dashboard", async ({ page }) => {
    const password = e2eTaPasswordOrSkip(test);
    const consoleLines = collectConsole(page);

    await login(page, E2E_TA_EMAIL, password);
    await page.waitForLoadState("networkidle");

    console.log("--- TA login console messages ---");
    for (const line of consoleLines) console.log(line);

    await page.screenshot({ path: "test-results/screens/s10/ta-dashboard-en.png", fullPage: true });

    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "test-results/screens/s10/ta-dashboard-am.png", fullPage: true });
  });
});
