/**
 * Playwright E2E — S12-2 Help & Documents page (manifest filtered by role
 * audience, markdown rendering with anchors/tables, Amharic chrome).
 *
 * Chromium headless only, against http://localhost:3000. See CLAUDE.md §29
 * "Browser verification". Screenshots go to frontend/test-results/screens/s12/
 * (gitignored).
 *
 * No demo WM account exists in frontend/src/lib/demo-data.ts (ALL_DEMO_USERS
 * is SA only), and the real seeded WM account (wm_wha1@t07.com) has a real
 * password this suite does not have, so that check is skipped rather than
 * guessed at or reset.
 *
 * Run:
 *   npx playwright test tests/s12-help.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { SA_EMAIL, saPasswordOrSkip } from "./helpers/sa-credentials";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const WM_EMAIL = "wm_wha1@t07.com";
const WM_ORG = "tenant-07";

test.setTimeout(60_000);

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => { if (msg.type() === "error" && !isDevHmrNoise(msg.text())) lines.push(msg.text()); });
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

test.describe("S12-2 Help & Documents", () => {
  test("SA sees every audience, including SA-only coming-soon", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/help`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("TA Onboarding Guide")).toBeVisible();
    await expect(page.getByText("Terms of Service")).toBeVisible();
    await expect(page.getByText("Privacy Policy")).toBeVisible();
    await expect(page.getByText("SA Operations Manual")).toBeVisible();
    await expect(page.getByText("Warehouse Manager Guide")).toBeVisible();
    await expect(page.getByText("Staff Quick Guide")).toBeVisible();
    await expect(page.getByText("Release Notes")).toBeVisible();
    await expect(page.getByText("Coming soon").first()).toBeVisible();

    // SAM-2: SA Operations Manual is now "published" (served via the
    // authenticated sa:docs_view route), so its card is clickable — unlike
    // the other SA/MANAGER/STAFF docs below it, still "coming_soon".
    // Opening it and checking the fetched content is Alex's manual SA-login check.
    const saManualCard = page.locator("a", { hasText: "SA Operations Manual" });
    await expect(saManualCard).toHaveCount(1);

    await page.screenshot({ path: "test-results/screens/s12/sa-help-list-en.png", fullPage: true });

    console.log("--- SA help list console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on SA help list").toHaveLength(0);
  });

  test("e2e TA sees TA + ALL docs, opens the guide, anchors and tables render", async ({ page }) => {
    const password = e2eTaPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, E2E_TA_EMAIL, password);
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/help`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("TA Onboarding Guide")).toBeVisible();
    await expect(page.getByText("Terms of Service")).toBeVisible();
    await expect(page.getByText("Release Notes")).toBeVisible();
    await expect(page.getByText("SA Operations Manual")).toHaveCount(0);
    await expect(page.getByText("Warehouse Manager Guide")).toHaveCount(0);
    await expect(page.getByText("Staff Quick Guide")).toHaveCount(0);

    await page.getByText("TA Onboarding Guide").click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: /SMART Inventory/i })).toBeVisible();

    // Table renders (the Audience | Sections table near the top of the guide).
    // Scoped to a table cell — the guide now repeats "Tenant Administrator" in
    // several places (checklist heading, FAQ, role-lock text), which makes the
    // old bare getByText ambiguous (strict-mode violation).
    await expect(page.getByRole("table").first()).toBeVisible();
    await expect(page.getByRole("cell", { name: /^🔒\s*Tenant Administrator \(TA\) Only$/ })).toBeVisible();

    // Internal anchor link scrolls to its heading (same algorithm as the
    // link's own target — see DocumentRenderer.slugifyHeading).
    const planTiersLink = page.locator('a[href="#plan-tiers"]').first();
    await planTiersLink.scrollIntoViewIfNeeded();
    await planTiersLink.click();
    await page.waitForTimeout(300);
    await expect(page).toHaveURL(/#plan-tiers$/);

    await page.screenshot({ path: "test-results/screens/s12/ta-help-doc-en.png", fullPage: true });

    console.log("--- TA help doc console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on TA help doc").toHaveLength(0);
  });

  for (const locale of ["en", "am"] as const) {
    test(`SAM-2: e2e TA cannot reach the SA Operations Manual (${locale})`, async ({ page }) => {
      const password = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);
      const saDocRequests: string[] = [];
      page.on("request", (req) => {
        if (req.url().includes("/api/v1/tenants/sa/docs/")) saDocRequests.push(req.url());
      });

      await login(page, E2E_TA_EMAIL, password);
      if (locale === "am") await page.evaluate(() => localStorage.setItem("locale", "am"));

      // (a) no SA Operations Manual card on the help list.
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/help`);
      await page.waitForLoadState("networkidle");
      await expect(page.getByText("SA Operations Manual")).toHaveCount(0);

      // (b) direct navigation shows help.not_found and never calls the SA route.
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/help/sa-operations-manual`);
      await page.waitForLoadState("networkidle");
      await expect(page.getByText(/not found|not available|አልተገኘም/i)).toBeVisible();

      expect(saDocRequests, "no request to the SA docs route was made").toHaveLength(0);

      await page.screenshot({
        path: `test-results/screens/s12/ta-sa-manual-blocked-${locale}.png`,
        fullPage: true,
      });

      console.log(`--- TA SA-manual-blocked (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  }

  test("WM sees MANAGER + ALL only; the TA guide is not authorised", async ({ page }) => {
    test.skip(
      true,
      "No demo WM login available (ALL_DEMO_USERS is SA-only) and the real seeded " +
        `WM account (${WM_EMAIL}) has a real password this suite does not have — ` +
        "skipped rather than guessed at or reset (CLAUDE.md §29).",
    );
    const consoleErrors = collectConsoleErrors(page);

    await login(page, WM_EMAIL, "x");
    await page.goto(`${BASE_URL}/${WM_ORG}/help`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Warehouse Manager Guide")).toBeVisible();
    await expect(page.getByText("Terms of Service")).toBeVisible();
    await expect(page.getByText("Release Notes")).toBeVisible();
    await expect(page.getByText("TA Onboarding Guide")).toHaveCount(0);
    await expect(page.getByText("SA Operations Manual")).toHaveCount(0);
    await expect(page.getByText("Staff Quick Guide")).toHaveCount(0);

    await page.goto(`${BASE_URL}/${WM_ORG}/help/ta-onboarding-guide`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/not found|not available/i)).toBeVisible();

    await page.screenshot({ path: "test-results/screens/s12/wm-help-list-en.png", fullPage: true });

    console.log("--- WM help console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on WM help views").toHaveLength(0);
  });

  test("Amharic chrome translates, english_only_notice shown, no raw keys", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, SA_EMAIL, saPw);
    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.goto(`${BASE_URL}/admin/help/ta-onboarding-guide`);
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText, "no raw i18n key leaked into rendered text").not.toMatch(/help\.[a-z_]+\.[a-z_]+/);

    await expect(page.getByText(/በእንግሊዝኛ ብቻ/)).toBeVisible();
    await expect(page.getByText("ወደ እገዛ ተመለስ")).toBeVisible();

    await page.screenshot({ path: "test-results/screens/s12/sa-help-doc-am.png", fullPage: true });

    console.log("--- Amharic help doc console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors rendering the Amharic help doc").toHaveLength(0);
  });
});
