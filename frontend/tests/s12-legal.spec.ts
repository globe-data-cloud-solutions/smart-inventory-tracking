/**
 * Playwright E2E — S12-3 public /terms and /privacy pages (draft outline,
 * DRAFT banner, no session required) and the terms-acceptance line shown
 * on the TA/SA Profile tab.
 *
 * Chromium headless only, against http://localhost:3000. See CLAUDE.md §29
 * "Browser verification". Screenshots go to frontend/test-results/screens/s12/
 * (gitignored).
 *
 * Run:
 *   npx playwright test tests/s12-legal.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { SA_EMAIL, saPasswordOrSkip } from "./helpers/sa-credentials";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const TENANT_6P2T_ID = "aed68cc5-789f-4cb0-9ef5-9b6404267e42"; // tenant-6-p2t, SA-created, no acceptance row

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

test.describe("S12-3 public legal pages + acceptance line", () => {
  test("/terms loads with no session, real draft text, English", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await page.goto(`${BASE_URL}/terms`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(/Draft — not yet in effect/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Terms of Service", exact: true }).first()).toBeVisible();
    await expect(page.getByText(/GDC\/LEGAL REVIEW PENDING/)).toBeVisible();
    await expect(page.getByRole("heading", { name: /Governing law and dispute resolution/ })).toBeVisible();
    // Word-mirror artefacts (backslash-escaped brackets, raw HTML) must not leak through.
    await expect(page.getByText(/\\\[/)).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("<table>");

    await page.screenshot({ path: "test-results/screens/s12/terms-en.png", fullPage: true });

    console.log("--- /terms console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on /terms").toHaveLength(0);
  });

  test("/privacy loads with no session, real draft text, Amharic", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await page.goto(`${BASE_URL}/privacy`);
    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.reload();
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(/ረቂቅ/)).toBeVisible();
    // Page shell title is translated (am.json legal.privacy_title); the markdown body stays English.
    await expect(page.getByRole("heading", { name: "የግላዊነት ፖሊሲ", exact: true }).first()).toBeVisible();
    await expect(page.getByText(/GDC\/LEGAL REVIEW PENDING/)).toBeVisible();
    await expect(page.getByRole("heading", { name: /Your rights/ })).toBeVisible();
    await expect(page.getByText(/\\\[/)).toHaveCount(0);

    await page.screenshot({ path: "test-results/screens/s12/privacy-am.png", fullPage: true });

    console.log("--- /privacy (am) console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on /privacy (am)").toHaveLength(0);
  });

  test("signup page links to /terms and /privacy", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    await page.goto(`${BASE_URL}/signup`);
    await page.waitForLoadState("networkidle");

    await expect(page.locator('a[href="/terms"]').first()).toBeVisible();
    await expect(page.locator('a[href="/privacy"]').first()).toBeVisible();

    console.log("--- /signup link check console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on /signup").toHaveLength(0);
  });

  test("e2e TA Profile tab shows its real terms acceptance", async ({ page }) => {
    const password = e2eTaPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, E2E_TA_EMAIL, password);
    await page.goto(`${BASE_URL}/zz-e2e-ta/settings/tenant-admin`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^.?.?\s*Profile$/i }).first().click();
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(/Terms of Service version 2026-10 accepted on/)).toBeVisible();

    await page.screenshot({ path: "test-results/screens/s12/ta-profile-terms-en.png", fullPage: true });

    console.log("--- TA profile terms acceptance console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on TA profile terms line").toHaveLength(0);
  });

  test("SA opens tenant-6-p2t (SA-created) and sees no acceptance on record", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${TENANT_6P2T_ID}`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^.?.?\s*Profile$/i }).first().click();
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("No Terms of Service acceptance on record.")).toBeVisible();

    await page.screenshot({ path: "test-results/screens/s12/sa-tenant-no-terms-en.png", fullPage: true });

    console.log("--- SA tenant no-terms console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors on SA tenant profile (no terms row)").toHaveLength(0);
  });
});
