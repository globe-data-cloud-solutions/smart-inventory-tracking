/**
 * Playwright E2E — P5: public /contact page, its placements across the app,
 * and the SA settings/contact editor's access guard (CLAUDE.md §29).
 *
 * The real backend's platform_contact row is unconfigured in this dev
 * environment, so the "configured" placements (landing nav/footer, login
 * footer, dashboard "Need help?" card, Help page card, Features tab link)
 * are exercised via page.route interception of GET /public/contact — nothing
 * is faked in app code, and no write ever reaches the real backend here.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p5-contact.spec.ts --workers=1
 */
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const PUBLIC_CONTACT_PATH = "**/api/v1/tenants/public/contact";

test.setTimeout(60_000);

// Every spec in this file intercepts requests — block the service worker so
// page.route() always wins instead of silently falling through to it.
test.use({ serviceWorkers: "block" });

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

function fulfillContact(route: Route, data: Record<string, unknown>) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      data,
      request_id: "test-request-id",
      timestamp: new Date().toISOString(),
    }),
  });
}

const CONFIGURED_FIXTURE = {
  configured: true,
  support_email: "support@smart-inventory.example",
  phone: "+251911000000",
  whatsapp: "+251911000000",
  address: { en: "123 Bole Road, Addis Ababa", am: "123 ቦሌ መንገድ, አዲስ አበባ" },
  hours: { en: "Mon-Fri 9am-5pm", am: "ሰኞ-አርብ 9ሰ-5ሰ" },
  note: { en: "Response within 1 business day.", am: "በ1 የስራ ቀን ውስጥ ምላሽ።" },
  updated_at: "2026-10-01T00:00:00Z",
};

async function assertNoRawKeysOrHrefHash(page: Page) {
  await expect(page.locator('a[href="#"]')).toHaveCount(0);
  await expect(page.getByText(/\bcontact\.[a-z_]+\b/)).toHaveCount(0);
  await expect(page.getByText(/\bplatform_contact\.[a-z_]+\b/)).toHaveCount(0);
}

// ── 1) Unconfigured backend — coming-soon text; no landing link ────────────
for (const locale of ["en", "am"] as const) {
  test.describe(`Unconfigured contact (${locale})`, () => {
    test(`/contact shows coming-soon; landing has no Contact link (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await page.goto(`${BASE_URL}/contact`);
      await page.waitForLoadState("networkidle");

      const comingSoon = locale === "am"
        ? /እውቂያ ዝርዝሮች በቅርቡ ይመጣሉ|Contact details are coming soon/
        : /Contact details are coming soon/;
      await expect(page.getByText(comingSoon)).toBeVisible();
      await expect(page.getByRole("link", { name: /^(Getting started|መጀመር)$/ })).toBeVisible();
      await expect(page.getByRole("link", { name: /^(Sign up|ይመስገቡ)$/ })).toBeVisible();

      await assertNoRawKeysOrHrefHash(page);

      await page.goto(`${BASE_URL}/`);
      await page.waitForLoadState("networkidle");
      await expect(page.locator('a[href="/contact"]')).toHaveCount(0);

      await page.screenshot({ path: `test-results/p5/contact-coming-soon-${locale}.png`, fullPage: true });

      console.log(`--- unconfigured /contact (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── 2) Configured (intercepted) — /contact details, landing + login links ──
for (const locale of ["en", "am"] as const) {
  test.describe(`Configured contact, intercepted (${locale})`, () => {
    test(`/contact shows details; landing nav/footer + login footer link present (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await page.route(PUBLIC_CONTACT_PATH, (route) => fulfillContact(route, CONFIGURED_FIXTURE));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await page.goto(`${BASE_URL}/contact`);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("support@smart-inventory.example")).toBeVisible();
      await expect(page.getByText("+251911000000").first()).toBeVisible();
      const expectedHours = locale === "am" ? "ሰኞ-አርብ 9ሰ-5ሰ" : "Mon-Fri 9am-5pm";
      await expect(page.getByText(expectedHours)).toBeVisible();

      await assertNoRawKeysOrHrefHash(page);
      await page.screenshot({ path: `test-results/p5/contact-configured-${locale}.png`, fullPage: true });

      // Landing nav + footer link
      await page.goto(`${BASE_URL}/`);
      await page.waitForLoadState("networkidle");
      await expect(page.locator('a[href="/contact"]').first()).toBeVisible();

      // Login footer link
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState("networkidle");
      await expect(page.locator('a[href="/contact"]').first()).toBeVisible();

      console.log(`--- configured /contact (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── 3) TA placements: dashboard card, Help card, Features tab link ─────────
test.describe("TA placements (intercepted, configured)", () => {
  test("dashboard Need-help card, Help page card, Features tab contact link all visible", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);
    await page.route(PUBLIC_CONTACT_PATH, (route) => fulfillContact(route, CONFIGURED_FIXTURE));

    await login(page, E2E_TA_EMAIL, taPassword);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Need help?")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: "All contact details" })).toBeVisible();
    await page.screenshot({ path: "test-results/p5/dashboard-need-help.png", fullPage: true });

    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/help`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Contact SMART").first()).toBeVisible();
    await page.screenshot({ path: "test-results/p5/help-contact-card.png", fullPage: true });

    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=features`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("link", { name: "contact support" })).toBeVisible({ timeout: 10_000 });

    await assertNoRawKeysOrHrefHash(page);
    await page.screenshot({ path: "test-results/p5/features-contact-link.png", fullPage: true });

    console.log("--- TA placements console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});

// ── 4) SA editor guard — TA cannot access /settings/contact ─────────────────
test.describe("SA-only guard on /settings/contact", () => {
  test("TA sees the restricted view, not the editor form", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, E2E_TA_EMAIL, taPassword);
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/contact`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Access restricted to System Admin.")).toBeVisible();
    await expect(page.getByText("Reason for change")).toHaveCount(0);

    await page.screenshot({ path: "test-results/p5/settings-contact-restricted.png", fullPage: true });

    console.log("--- SA guard console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});
