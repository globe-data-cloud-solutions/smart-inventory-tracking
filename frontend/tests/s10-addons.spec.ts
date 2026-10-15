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
import { SA_EMAIL, saPassword, saPasswordOrSkip } from "./helpers/sa-credentials";
import { createProbeTenant, deactivateTenant, saToken, type ProbeTenant } from "./helpers/sa-api";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

// SA tests are run by Alex only, by hand (E2E_SA_PASSWORD).
const SA_SKIP_REASON = "E2E_SA_PASSWORD not set — SA tests are run by Alex only, by hand";

test.setTimeout(60_000);
// public/sw.js answers /api/v1/ mutations itself (respondWith(fetch(...))), and
// page.route() never sees requests that go through a service worker — so the
// price-post stub below only intercepts when the worker is blocked.
test.use({ serviceWorkers: "block" });

/** ISO date (YYYY-MM-DD) `days` from today, UTC. */
function isoDaysFromNow(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

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
  test.skip(!saPassword(), SA_SKIP_REASON);

  for (let i = 1; i <= 5; i++) {
    test(`fresh SA login #${i} -> dashboard, zero 401s`, async ({ page }) => {
      const saPw = saPasswordOrSkip(test);
      const consoleLines = collectConsole(page);
      const apiErrors: string[] = [];
      page.on("response", (res) => {
        if (res.status() === 401) apiErrors.push(`401: ${res.url()}`);
      });

      await login(page, SA_EMAIL, saPw);
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

test.describe.configure({ mode: "serial" });

const ADDON_PRICES_PATH = /^\/api\/v1\/tenants\/platform\/addons\/([^/]+)\/prices$/;
const ADDON_CATALOG_PATH = "/api/v1/tenants/platform/addons";

interface StubbedAddonCatalogRow {
  code: string;
  prices: Array<{ billing_period: string; current: { currency: string } | null; scheduled: unknown[] }>;
}

test.describe("S10-4 SA Plans & Pricing — Add-ons tab", () => {
  test.skip(!saPassword(), SA_SKIP_REASON);

  test("set and see a scheduled price (POST stubbed — no real price written)", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    const effectiveFrom = isoDaysFromNow(120);
    const note = "S10 Playwright scheduled price test";

    // Add-on prices are append-only, so the price POST is answered here and
    // never reaches the backend. After it, the catalog GET is the real
    // response with one scheduled ANNUAL price added to AUDIT_EXPORT, so the
    // "Scheduled" label is still checked. Any other write to the add-on
    // routes is aborted and fails the test.
    let postedPath: string | null = null;
    let postedBody: unknown = null;
    const blockedWrites: string[] = [];
    await page.route((url) => url.pathname.startsWith(ADDON_CATALOG_PATH), async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname.replace(/\/$/, "");
      const cors = {
        "access-control-allow-origin": req.headers()["origin"] ?? "*",
        "access-control-allow-credentials": "true",
        "access-control-allow-headers": "authorization,content-type",
        "access-control-allow-methods": "GET,POST,OPTIONS",
      };
      if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
      if (req.method() === "POST" && ADDON_PRICES_PATH.test(path)) {
        postedPath = path;
        postedBody = req.postDataJSON();
        return route.fulfill({
          status: 201, contentType: "application/json", headers: cors,
          body: JSON.stringify({ success: true, data: { id: "00000000-0000-4000-8000-000000000000", message: "stubbed" } }),
        });
      }
      if (req.method() === "GET" && path === ADDON_CATALOG_PATH) {
        const real = await route.fetch();
        if (postedPath === null) return route.fulfill({ response: real });
        const json = (await real.json()) as { data: StubbedAddonCatalogRow[] };
        const annual = json.data.find((r) => r.code === "AUDIT_EXPORT")?.prices.find((p) => p.billing_period === "ANNUAL");
        if (annual) {
          annual.scheduled = [{
            id: "stub-scheduled-price", amount: "500", currency: annual.current?.currency ?? "ETB",
            effective_from: `${effectiveFrom}T00:00:00+00:00`, reason: note,
            created_by: null, created_by_email: null, created_at: new Date().toISOString(),
          }];
        }
        return route.fulfill({ response: real, json });
      }
      if (req.method() !== "GET") {
        blockedWrites.push(`${req.method()} ${path}`);
        return route.abort();
      }
      return route.continue();
    });

    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/plans`);
    await page.getByRole("button", { name: "Add-ons" }).click();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "test-results/screens/s10/sa-plans-addons-en.png", fullPage: true });

    const setPriceCard = page.locator("h3", { hasText: "Set new price" }).locator("..");
    await setPriceCard.locator("select").nth(0).selectOption({ label: "Audit Log Export" });
    await setPriceCard.locator("select").nth(1).selectOption("ANNUAL");
    await setPriceCard.locator('input[type="number"]').fill("500");
    await setPriceCard.locator('input[type="date"]').fill(effectiveFrom);
    await setPriceCard.locator('input[type="text"]').fill(note);
    await setPriceCard.getByRole("button", { name: "Post price" }).click();
    await expect(setPriceCard.getByText("Existing purchased add-ons pay the new price")).toBeVisible({ timeout: 10_000 });

    // What the page sent: add-on (path), billing period, amount, effective date, note (reason).
    expect(postedPath).toBe("/api/v1/tenants/platform/addons/AUDIT_EXPORT/prices");
    expect(postedBody).toEqual({
      billing_period: "ANNUAL", amount: "500", effective_from: effectiveFrom, reason: note,
    });

    const auditCard = page.locator("span", { hasText: "AUDIT_EXPORT" }).locator("..");
    await expect(auditCard.getByText(/Scheduled/)).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s10/sa-plans-addons-scheduled-en.png", fullPage: true });

    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^(Add-ons|ተጨማሪዎች)$/ }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("LOGISTICS", { exact: true })).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/sa-plans-addons-am.png", fullPage: true });

    expect(blockedWrites, "no other write may reach the add-on routes").toEqual([]);
    console.log("--- SA Plans Add-ons console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero new console errors on SA Plans Add-ons tab").toHaveLength(0);
  });
});

// Grant / invoice / TA-view tests run against their own probe tenant (STARTER,
// MONTHLY), created per run and deactivated in afterAll — never zz-e2e-ta.
test.describe("S10-4 probe tenant add-ons", () => {
  test.skip(!saPassword(), SA_SKIP_REASON);

  let probe: ProbeTenant;

  test.beforeAll(async ({ request }) => {
    probe = await createProbeTenant(request, { prefix: "s10", tier: "STARTER", billingPeriod: "MONTHLY" });
  });

  test.afterAll(async ({ request }) => {
    if (probe) await deactivateTenant(request, await saToken(request), probe.id);
  });

test.describe("S10-4 SA tenant page — Features Add-ons + plan-change persistence", () => {
  test("grant free override, survives plan change, then cancel", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${probe.id}`);
    await page.getByRole("button", { name: /^.?.?\s*Features$/i }).first().click();
    await page.waitForLoadState("networkidle");

    const addonsSection = page.locator("h3", { hasText: "Add-ons" }).locator("..");
    await addonsSection.getByRole("button", { name: "Grant free override" }).click();
    await addonsSection.locator("select").selectOption({ label: "Logistics & Fleet Management" });
    await addonsSection.locator('input[type="text"]').fill("S10 Playwright pilot grant");
    await addonsSection.getByRole("button", { name: "Yes" }).click();
    await expect(addonsSection.getByText("Free override")).toBeVisible({ timeout: 10_000 });

    const logisticsRow = page.locator("h4", { hasText: "Logistics & Fleet Management" }).locator("..");
    await expect(logisticsRow.getByText("Add-on", { exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s10/sa-tenant-features-addon-en.png", fullPage: true });

    // Plan change STARTER -> GROWTH -> STARTER; LOGISTICS must stay "Add-on".
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "GROWTH" }).click();
    await page.getByRole("button", { name: "Save" }).click();
    await page.getByRole("button", { name: "Yes" }).click();
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /^.?.?\s*Features$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(logisticsRow.getByText("Add-on", { exact: true })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "STARTER" }).click();
    await page.getByRole("button", { name: "Save" }).click();
    await page.getByRole("button", { name: "Yes" }).click();
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /^.?.?\s*Features$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(logisticsRow.getByText("Add-on", { exact: true })).toBeVisible({ timeout: 10_000 });

    // Cancel the override.
    await addonsSection.getByRole("button", { name: "Cancel" }).click();
    await addonsSection.locator('input[type="text"]').fill("S10 Playwright cleanup");
    await addonsSection.getByRole("button", { name: "Yes" }).click();
    await expect(addonsSection.getByText("No add-ons yet.")).toBeVisible({ timeout: 10_000 });

    console.log("--- SA tenant Features add-on console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero new console errors on SA tenant Features/Plan tabs").toHaveLength(0);
  });

  test("purchased add-on on an invoice, screenshot line items, then cancel", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${probe.id}`);
    await page.getByRole("button", { name: /^.?.?\s*Features$/i }).first().click();
    await page.waitForLoadState("networkidle");

    const addonsSection = page.locator("h3", { hasText: "Add-ons" }).locator("..");
    await addonsSection.getByRole("button", { name: "Add purchased add-on" }).click();
    await addonsSection.locator("select").selectOption({ label: "Logistics & Fleet Management" });
    await addonsSection.getByRole("button", { name: "Yes" }).click();
    await expect(addonsSection.getByText("Purchased")).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Raise Invoice" }).click();
    await page.getByRole("button", { name: "Yes" }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/Add-on: Logistics/).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/sa-tenant-invoice-lines-en.png", fullPage: true });

    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^.?.?\s*(Plan|ዕቅድ)$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "test-results/screens/s10/sa-tenant-invoice-lines-am.png", fullPage: true });

    // Cleanup — cancel the invoice, then the add-on grant, leaving the probe
    // on STARTER with no add-ons.
    await page.evaluate(() => localStorage.setItem("locale", "en"));
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Cancel" }).click();
    await page.locator("tr.bg-red-50 input[type=\"text\"]").fill("S10 Playwright cleanup");
    await page.getByRole("button", { name: "Yes" }).click();
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /^.?.?\s*Features$/i }).first().click();
    await page.waitForLoadState("networkidle");
    const cleanupAddonsSection = page.locator("h3", { hasText: "Add-ons" }).locator("..");
    await cleanupAddonsSection.getByRole("button", { name: "Cancel" }).click();
    await cleanupAddonsSection.locator('input[type="text"]').fill("S10 Playwright cleanup");
    await cleanupAddonsSection.getByRole("button", { name: "Yes" }).click();
    await expect(cleanupAddonsSection.getByText("No add-ons yet.")).toBeVisible({ timeout: 10_000 });

    console.log("--- SA tenant invoice line items console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero new console errors on SA tenant invoice flow").toHaveLength(0);
  });
});

test.describe("S10-4 TA views (real login)", () => {
  test("Plan tab add-ons + invoice lines; Features source labels; settings restricted", async ({ page }) => {
    saPasswordOrSkip(test); // the probe tenant (beforeAll) is created and cleaned up by SA
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await login(page, probe.adminEmail, probe.adminPassword);
    await page.waitForLoadState("networkidle");

    await page.goto(`${BASE_URL}/${probe.slug}/settings/tenant-admin`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: "Add-ons" })).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/ta-plan-addons-en.png", fullPage: true });

    await page.getByRole("button", { name: /^.?.?\s*Features$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Package", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/ta-features-sources-en.png", fullPage: true });

    await page.evaluate(() => localStorage.setItem("locale", "am"));
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: /^.?.?\s*(Features|ባህሪያት)$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("ጥቅል", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/ta-features-sources-am.png", fullPage: true });
    await page.evaluate(() => localStorage.setItem("locale", "en"));

    // TA must never reach the SA-only tenant settings page — the org-slug
    // mismatch in [org]/layout.tsx redirects it straight back to its own
    // dashboard before the page's own role check ever runs.
    await page.goto(`${BASE_URL}/admin/settings/tenants/${probe.id}`);
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(new RegExp(`/${probe.slug}/dashboard`), { timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/ta-settings-restricted-en.png", fullPage: true });

    console.log("--- TA views console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero new console errors on TA views").toHaveLength(0);
  });
});
});
