/**
 * Playwright E2E — P3: Features tab plan comparison modal and upgrade
 * requests (CLAUDE.md §29).
 *
 * zz-e2e-ta is the permanent TA probe, STARTER tier. No live write ever
 * reaches the backend here — the renewal-requests POST and GET are
 * intercepted and fulfilled in this spec. Chromium headless only, against
 * http://localhost:3000. Run:
 *   npx playwright test tests/p3-features-upgrade.spec.ts --workers=1 --reporter=line
 */
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

// Block the service worker so every page.route() intercept below is
// guaranteed to catch the request instead of falling through to the real
// backend — critical since this spec intercepts a POST that creates data.
test.use({ serviceWorkers: "block" });

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

const RENEWAL_REQUESTS_PATH = "**/api/v1/tenants/me/renewal-requests";
const PUBLIC_CONTACT_PATH = "**/api/v1/tenants/public/contact";

// Forces PublicContactLink's "contact support" link to not render — the real
// platform_contact row's configured state is not this spec's concern, and
// relying on it being unconfigured made the "no contact support link"
// assertion below depend on live DB state (CLAUDE.md §29: no SQL writes
// here to force that state instead).
const UNCONFIGURED_CONTACT = {
  configured: false,
  support_email: null,
  phone: null,
  whatsapp: null,
  address: { en: null, am: null },
  hours: { en: null, am: null },
  note: { en: null, am: null },
  updated_at: "2026-01-01T00:00:00Z",
};

function fulfillList(route: Route, data: unknown[]) {
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

async function assertNoRawKeysOrPlaceholderLinks(page: Page) {
  await expect(page.getByText(/\b[a-z][a-z_]*\.[a-z][a-z_.]*\b/, { exact: true })).toHaveCount(0);
  await expect(page.locator('a[href="#"]')).toHaveCount(0);
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Features tab — plan comparison modal (${locale})`, () => {
    test(`View pricing / View plans / Compare plans all open the modal (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);
      await page.route(PUBLIC_CONTACT_PATH, (route) => fulfillContact(route, UNCONFIGURED_CONTACT));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=features`);
      await page.waitForLoadState("networkidle");

      // No "Contact support" link left on the Features tab.
      await expect(page.getByText(/contact support|ድጋፍን ያነጋግሩ/i)).toHaveCount(0);
      await assertNoRawKeysOrPlaceholderLinks(page);

      const viewPricingBtn = page.getByRole("button", { name: /View Pricing|ዋጋ ይመልክቱ/i });
      await viewPricingBtn.click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 10_000 });
      await expect(dialog.getByText("STARTER").or(dialog.getByText("Starter"))).toBeVisible();
      await expect(dialog.getByText(/Your plan|የእርስዎ ዕቅድ/i)).toBeVisible();

      // Three package columns.
      const columnCount = await dialog.locator(":scope > div > div.rounded-lg").count();
      expect(columnCount).toBe(3);

      // Esc closes it.
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);

      const viewPlansBtn = page.getByRole("button", { name: /View Plans|ዕቅዶችን ይመልክቱ/i });
      await viewPlansBtn.click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10_000 });
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);

      const compareLink = page.getByRole("button", { name: /Compare plans|ዕቅዶችን ያወዳድሩ/i }).first();
      await compareLink.click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10_000 });
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);

      console.log(`--- Features tab modal (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`Request upgrade dialog lists only tiers above STARTER and posts request_type UPGRADE (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      let capturedBody: Record<string, unknown> | null = null;

      await page.route(RENEWAL_REQUESTS_PATH, (route) => {
        const req = route.request();
        if (req.method() === "GET") return fulfillList(route, []);
        if (req.method() === "POST") {
          capturedBody = req.postDataJSON() as Record<string, unknown>;
          return route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              success: true,
              data: {
                id: "test-upgrade-id",
                tenant_id: "test-tenant-id",
                requested_by: "test-user-id",
                requested_by_email: E2E_TA_EMAIL,
                message: null,
                request_type: "UPGRADE",
                requested_tier: "GROWTH",
                status: "OPEN",
                handled_by: null,
                handled_note: null,
                handled_at: null,
                created_at: new Date().toISOString(),
              },
              request_id: "test-request-id",
              timestamp: new Date().toISOString(),
            }),
          });
        }
        return route.continue();
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=features`);
      await page.waitForLoadState("networkidle");

      const requestUpgradeBtn = page.getByRole("button", { name: /Request Upgrade|ማሻሻል ይጠይቁ/i });
      await expect(requestUpgradeBtn).toBeVisible({ timeout: 10_000 });
      await requestUpgradeBtn.click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 10_000 });

      const tierSelect = dialog.locator("select");
      const optionValues = await tierSelect.locator("option").allTextContents();
      expect(optionValues.join(" ")).not.toMatch(/STARTER|Starter/);
      expect(optionValues.length).toBe(2); // GROWTH, ENTERPRISE only

      const submitBtn = dialog.getByRole("button", { name: /Submit request|ጥያቄ አቅርብ/i });
      await submitBtn.click();

      await expect(dialog).toHaveCount(0, { timeout: 10_000 });
      expect(capturedBody).not.toBeNull();
      expect((capturedBody as Record<string, unknown>).request_type).toBe("UPGRADE");

      console.log(`--- Request upgrade dialog (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });

  test.describe(`Plan tab — open UPGRADE request (${locale})`, () => {
    test(`renewal form still shown and the upgrade line is shown (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(RENEWAL_REQUESTS_PATH, (route) => {
        if (route.request().method() !== "GET") return route.continue();
        return fulfillList(route, [
          {
            id: "test-upgrade-id",
            tenant_id: "test-tenant-id",
            requested_by: "test-user-id",
            requested_by_email: E2E_TA_EMAIL,
            message: null,
            request_type: "UPGRADE",
            requested_tier: "GROWTH",
            status: "OPEN",
            handled_by: null,
            handled_note: null,
            handled_at: null,
            created_at: new Date().toISOString(),
          },
        ]);
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=plan`);
      await page.waitForLoadState("networkidle");

      // The renewal form (no OPEN *renewal* request) is still shown — this
      // mocked list only contains an OPEN UPGRADE row.
      const submitBtn = page.getByRole("button", { name: /Request renewal|የማደስ ጥያቄ አቅርብ/i });
      await expect(submitBtn).toBeVisible({ timeout: 10_000 });

      await expect(page.getByText(/Upgrade to GROWTH requested on|ማሻሻል ወደ GROWTH/i)).toBeVisible({ timeout: 10_000 });

      console.log(`--- Plan tab open upgrade (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
