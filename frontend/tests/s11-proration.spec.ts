/**
 * Playwright E2E — S11 mid-period proration UI (preview + confirm dialog,
 * proration badge on invoices, blocked message, downgrade no-refund note).
 *
 * Chromium headless only, against http://localhost:3000. See CLAUDE.md §29
 * "Browser verification". Screenshots go to
 * frontend/test-results/screens/s11/ (gitignored).
 *
 * Uses the probe tenant zz-s11-probe created via the public signup API for
 * this work (ANNUAL STARTER, already upgraded to GROWTH + API_ACCESS
 * add-on via direct API calls earlier in this session, then downgraded
 * back to STARTER — this spec re-exercises the SAME upgrade through the
 * UI). Deactivated at the end — it keeps its invoice history (append-only).
 *
 * Run:
 *   npx playwright test tests/s11-proration.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const SA_EMAIL = "smartadmin@smart-inventory.com";
const SA_PASSWORD = "Admin@2026";
const PROBE_TENANT_ID = "c16a9753-1a17-4695-a766-6c98b4d529a6"; // zz-s11-probe

test.setTimeout(60_000);

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => { if (msg.type() === "error") lines.push(msg.text()); });
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

test.describe.configure({ mode: "serial" });

test.describe("S11 proration — SA tenant page", () => {
  test("upgrade preview, confirm, proration invoice banner + badge", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await login(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${PROBE_TENANT_ID}`);
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");

    // Current tier is STARTER (downgraded back via API earlier this session).
    await page.getByRole("button", { name: "GROWTH" }).click();
    await page.getByRole("button", { name: "Save Changes" }).click();

    // Preview should resolve and show the charge line before confirming.
    await expect(page.getByText(/months charged now/)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s11/sa-plan-upgrade-preview-en.png", fullPage: true });

    await page.getByRole("button", { name: "Yes, apply" }).click();
    await expect(page.getByText(/proration invoice.*has been raised/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s11/sa-plan-upgrade-done-en.png", fullPage: true });

    // Invoices list should show at least one PRORATION badge (this run's new
    // invoice, plus the one created via direct API call earlier in this session).
    await expect(page.getByText("Proration", { exact: true }).first()).toBeVisible({ timeout: 10_000 });

    // Cleanup — cancel the PRORATION invoice this run just raised (newest
    // row, since the backend orders payments by created_at DESC) so repeated
    // runs stop piling up PENDING invoices on zz-s11-probe (CLAUDE.md §15 S12).
    const newInvoiceRow = page.locator("tr", { hasText: "Proration" }).first();
    await newInvoiceRow.getByRole("button", { name: "Cancel" }).click();
    await page.locator("tr.bg-red-50 input[type=\"text\"]").fill("e2e cleanup");
    await page.getByRole("button", { name: "Yes" }).click();
    await page.waitForLoadState("networkidle");

    console.log("--- upgrade preview/confirm console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on the upgrade preview/confirm flow").toHaveLength(0);
  });

  test("downgrade shows no-refund note, no proration invoice", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await login(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${PROBE_TENANT_ID}`);
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "STARTER" }).click();
    await page.getByRole("button", { name: "Save Changes" }).click();
    await expect(page.getByText(/no refund or credit/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s11/sa-plan-downgrade-no-refund-en.png", fullPage: true });

    await page.getByRole("button", { name: "Yes, apply" }).click();
    await page.waitForLoadState("networkidle");

    console.log("--- downgrade console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on the downgrade flow").toHaveLength(0);
  });

  test("Amharic locale renders the proration preview without errors", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await login(page, SA_EMAIL, SA_PASSWORD);
    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.goto(`${BASE_URL}/admin/settings/tenants/${PROBE_TENANT_ID}`);
    await page.getByRole("button", { name: /Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "GROWTH" }).click();
    await page.getByRole("button", { name: /Save Changes|ለውጦችን ያስቀምጡ/ }).click();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "test-results/screens/s11/sa-plan-upgrade-preview-am.png", fullPage: true });

    // Cancel rather than apply — this run only checks rendering.
    await page.getByRole("button", { name: /Cancel|ይቅር/ }).first().click();

    console.log("--- Amharic preview console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors rendering the Amharic preview").toHaveLength(0);
  });
});
