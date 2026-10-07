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
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
// The gateway is a separate port from the Next.js dev server — never derived
// from BASE_URL by string substitution (that breaks the moment BASE_URL
// isn't literally "...3000"). GATEWAY_URL overrides for non-default setups.
const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://localhost:8000";
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

// ── S10-4 frontend: add-on catalog, tenant add-ons, feature sources ──────────

async function getSaToken(): Promise<string> {
  const tokenRes = await fetch(`${GATEWAY_URL}/api/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dev_email: SA_EMAIL }),
  });
  const { access_token } = (await tokenRes.json()) as { access_token: string };
  return access_token;
}

// Resolved once per run by slug via the SA registry, rather than a hardcoded
// UUID that silently goes stale if the probe tenant is ever recreated.
let cachedE2ETaTenantId: string | null = null;
async function resolveE2ETaTenantId(): Promise<string> {
  if (cachedE2ETaTenantId) return cachedE2ETaTenantId;
  const token = await getSaToken();
  const registryRes = await fetch(`${GATEWAY_URL}/api/v1/tenants/sa/registry`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const { data } = (await registryRes.json()) as { data: { id: string; slug: string | null }[] };
  const row = data.find((t) => t.slug === E2E_TA_SLUG);
  if (!row) throw new Error(`Tenant with slug "${E2E_TA_SLUG}" not found in SA registry`);
  cachedE2ETaTenantId = row.id;
  return row.id;
}

async function reactivateE2ETa() {
  const token = await getSaToken();
  const tenantId = await resolveE2ETaTenantId();
  // zz-e2e-ta stays ACTIVE always (CLAUDE.md §29) — this is a no-op guard, not a real reactivate need.
  await fetch(`${GATEWAY_URL}/api/v1/tenants/${tenantId}/reactivate`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({}),
  }).catch(() => {});
}

test.describe.configure({ mode: "serial" });

test.describe("S10-4 SA Plans & Pricing — Add-ons tab", () => {
  test("set and see a scheduled price", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await login(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/plans`);
    await page.getByRole("button", { name: "Add-ons" }).click();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: "test-results/screens/s10/sa-plans-addons-en.png", fullPage: true });

    const setPriceCard = page.locator("h3", { hasText: "Set new price" }).locator("..");
    await setPriceCard.locator("select").nth(0).selectOption({ label: "Audit Log Export" });
    await setPriceCard.locator("select").nth(1).selectOption("ANNUAL");
    await setPriceCard.locator('input[type="number"]').fill("500");
    await setPriceCard.locator('input[type="date"]').fill("2027-06-01");
    await setPriceCard.locator('input[type="text"]').fill("S10 Playwright scheduled price test");
    await setPriceCard.getByRole("button", { name: "Post price" }).click();
    await expect(setPriceCard.getByText("Existing purchased add-ons pay the new price")).toBeVisible({ timeout: 10_000 });

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

    console.log("--- SA Plans Add-ons console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero new console errors on SA Plans Add-ons tab").toHaveLength(0);
  });
});

test.describe("S10-4 SA tenant page — Features Add-ons + plan-change persistence", () => {
  test("grant free override, survives plan change, then cancel", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await reactivateE2ETa();
    await login(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${await resolveE2ETaTenantId()}`);
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
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await login(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${await resolveE2ETaTenantId()}`);
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

    // Cleanup — cancel the invoice, then the add-on grant, leaving zz-e2e-ta
    // on STARTER with no add-ons (CLAUDE.md §29 e2e TA account rule).
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
    const password = e2eTaPasswordOrSkip(test);
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await login(page, E2E_TA_EMAIL, password);
    await page.waitForLoadState("networkidle");

    await page.goto(`${BASE_URL}/zz-e2e-ta/settings/tenant-admin`);
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
    await page.goto(`${BASE_URL}/admin/settings/tenants/${await resolveE2ETaTenantId()}`);
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveURL(/\/zz-e2e-ta\/dashboard/, { timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s10/ta-settings-restricted-en.png", fullPage: true });

    console.log("--- TA views console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero new console errors on TA views").toHaveLength(0);
  });
});
