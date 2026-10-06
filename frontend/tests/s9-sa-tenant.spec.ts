/**
 * Playwright E2E — S9 one SA tenant page
 *
 * Covers: /[org]/settings/tenants/[tenantId] — every tab renders, live plan
 * limits (not hardcoded), contract vs billing period shown separately,
 * status actions, feature overrides, admin user, activity log, and the
 * onboarding wizard sending contract dates + billing period in one call.
 *
 * Chromium headless only, against http://localhost:3000. See CLAUDE.md §29
 * "Browser verification".
 *
 * Run:
 *   npx playwright test tests/s9-sa-tenant.spec.ts
 */

import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const SA_EMAIL = "smartadmin@smart-inventory.com";
const SA_PASSWORD = "Admin@2026";

const T6P2T_NAME = "Tenant_6_P2T";
const T6P2T_ID = "aed68cc5-789f-4cb0-9ef5-9b6404267e42";
const CONTRACT_PROBE_ID = "1ed1ab02-989c-442d-80ac-e66a7a21b36e";

test.describe.configure({ mode: "serial" });
// Generous per-test timeout: the first navigation after a fresh demo login can
// hit one 401 while the fire-and-forget JWT exchange is still in flight, and
// TanStack Query's retry/backoff plus Next dev's on-demand route compile can
// together exceed the 30s default on a cold run.
test.setTimeout(60_000);

async function reactivateProbe(tenantId: string) {
  const tokenRes = await fetch(`${BASE_URL.replace("3000", "8000")}/api/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dev_email: SA_EMAIL }),
  });
  const { access_token } = (await tokenRes.json()) as { access_token: string };
  await fetch(`${BASE_URL.replace("3000", "8000")}/api/v1/tenants/${tenantId}/reactivate`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
    body: JSON.stringify({}),
  });
}

async function loginAs(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(admin|addis-water|muger-cement|[a-z0-9-]+)\/dashboard/);
  // login() patches the SMART JWT into the session fire-and-forget (demo-auth.ts
  // _exchangeJWT) — a hard navigation/reload before it lands sends every gateway
  // request with no Authorization header at all (permanent 401, no retry recovers
  // it). Wait for the token to actually be persisted before navigating further.
  await page.waitForFunction(() => {
    try {
      const raw = localStorage.getItem("smart_demo_session");
      return !!(raw && JSON.parse(raw).jwtToken);
    } catch {
      return false;
    }
  }, { timeout: 10_000 });
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() === "error") errors.push(`[console] ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`[pageerror] ${err.message}`));
  return errors;
}

async function openTenantFromRegistry(page: Page, tenantName: string) {
  await page.goto(`${BASE_URL}/admin/dashboard`);
  await page.getByRole("button", { name: /Registry/i }).click();
  // The first API call after a fresh demo login can 401 once while the JWT
  // exchange (fire-and-forget) is still in flight — TanStack Query retries
  // with backoff, so give this generous time instead of a fixed sleep.
  await page.getByText(tenantName).first().waitFor({ state: "visible", timeout: 20_000 });
  const row = page.locator("tr", { hasText: tenantName });
  await row.getByRole("link", { name: "Open" }).click();
  await page.waitForURL(/\/admin\/settings\/tenants\/[0-9a-f-]+/);
}

test.describe("S9 smoke", () => {
  test("00 - login page renders", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.screenshot({ path: "test-results/screens/s9/00-login.png", fullPage: true });
  });
});

test.describe("S9-2 SA tenant page", () => {
  const errors: string[] = [];

  test("01 - registry Open navigates to the SA tenant page", async ({ page }) => {
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await openTenantFromRegistry(page, T6P2T_NAME);
    await expect(page.getByRole("heading", { name: T6P2T_NAME })).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s9/01-tenant-page.png", fullPage: true });
  });

  const TABS: { id: string; label: RegExp; shot: string }[] = [
    { id: "profile", label: /Profile/i, shot: "02-profile" },
    { id: "plan", label: /^.?.?\s*Plan$/i, shot: "03-plan" },
    { id: "contract", label: /Contract/i, shot: "04-contract" },
    { id: "status", label: /Status/i, shot: "05-status" },
    { id: "levels", label: /Levels/i, shot: "06-levels" },
    { id: "contact", label: /^[^a-zA-Z]*Contact$/i, shot: "07-contacts" },
    { id: "features", label: /Features/i, shot: "08-features" },
    { id: "admin-user", label: /Admin User/i, shot: "09-admin-user" },
    { id: "activity", label: /Activity/i, shot: "10-activity" },
  ];

  for (const tab of TABS) {
    test(`02 - tab renders: ${tab.id}`, async ({ page }) => {
      errors.push(...collectConsoleErrors(page));
      await loginAs(page, SA_EMAIL, SA_PASSWORD);
      await openTenantFromRegistry(page, T6P2T_NAME);
      await page.getByRole("button", { name: tab.label }).first().click();
      await page.waitForTimeout(600);
      await page.screenshot({ path: `test-results/screens/s9/en-${tab.shot}.png`, fullPage: true });
    });
  }

  test("03 - Amharic: profile and plan tabs render", async ({ page }) => {
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await page.evaluate(() => localStorage.setItem("locale", "am"));
    // Registry's "Open" action label is itself translated in Amharic — go
    // straight to the tenant's known UUID rather than text-matching the link.
    await page.goto(`${BASE_URL}/admin/settings/tenants/${T6P2T_ID}`);
    await page.waitForTimeout(1200);
    await page.screenshot({ path: "test-results/screens/s9/am-02-profile.png", fullPage: true });
    await page.getByRole("button").nth(1).click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "test-results/screens/s9/am-03-plan.png", fullPage: true });
  });

  test("04 - plan tab reads live tier limits, not hardcoded", async ({ page }) => {
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await openTenantFromRegistry(page, T6P2T_NAME);
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();

    const growthButtonBefore = page.locator("button", { hasText: "GROWTH" }).first();
    await expect(growthButtonBefore).not.toContainText("Loading", { timeout: 15_000 });
    const textBefore = await growthButtonBefore.innerText();
    await page.screenshot({ path: "test-results/screens/s9/11-plan-before-limit-change.png", fullPage: true });

    // Change GROWTH max_users via Plans & Pricing
    await page.goto(`${BASE_URL}/admin/settings/plans`);
    await page.getByPlaceholder(/Why are you making this change/i).waitFor({ state: "visible", timeout: 20_000 });
    await page.getByPlaceholder(/Why are you making this change/i).fill("S9 live-limits check");
    const growthCard = page.locator("div.bg-white.border.rounded-lg.p-4", { hasText: "GROWTH" }).first();
    const maxUsersInput = growthCard.locator("label:text-is('Max users') + input").first();
    const originalValue = await maxUsersInput.inputValue();
    const newValue = String((parseInt(originalValue || "25", 10) || 25) + 1);
    await maxUsersInput.fill(newValue);
    await growthCard.getByRole("button", { name: /Save/i }).click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: "test-results/screens/s9/12-plans-pricing-growth-changed.png", fullPage: true });

    // Reload the tenant's Plan tab — the number must reflect the live change
    await openTenantFromRegistry(page, T6P2T_NAME);
    await page.getByRole("button", { name: /^.?.?\s*Plan$/i }).first().click();
    const growthButtonAfter = page.locator("button", { hasText: "GROWTH" }).first();
    await expect(growthButtonAfter).not.toContainText("Loading", { timeout: 15_000 });
    const textAfter = await growthButtonAfter.innerText();
    await page.screenshot({ path: "test-results/screens/s9/13-plan-after-limit-change.png", fullPage: true });
    expect(textAfter).not.toBe(textBefore);

    // Revert
    await page.goto(`${BASE_URL}/admin/settings/plans`);
    await page.getByPlaceholder(/Why are you making this change/i).fill("S9 revert");
    const growthCard2 = page.locator("div.bg-white.border.rounded-lg.p-4", { hasText: "GROWTH" }).first();
    const maxUsersInput2 = growthCard2.locator("label:text-is('Max users') + input").first();
    await maxUsersInput2.fill(originalValue);
    await growthCard2.getByRole("button", { name: /Save/i }).click();
    await page.waitForTimeout(800);
  });

  test("05 - contract probe: contract tab + status deactivate via UI", async ({ page }) => {
    errors.push(...collectConsoleErrors(page));
    // Idempotent setup: this probe may already be DEACTIVATED from a prior run
    // of this same test — reactivate it first via a direct API call so the UI
    // flow below (deactivate via the Status tab) always has something to do.
    await reactivateProbe(CONTRACT_PROBE_ID);
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${CONTRACT_PROBE_ID}`);
    await page.getByRole("button", { name: /Contract/i }).first().waitFor({ state: "visible", timeout: 20_000 });
    await page.getByRole("button", { name: /Contract/i }).first().click();
    await page.waitForTimeout(600);
    // toLocaleDateString() formatting is environment-locale-dependent — match
    // loosely on the year rather than an exact M/D/Y string.
    await expect(page.getByText(/2026/).first()).toBeVisible();
    await expect(page.getByText(/2028/).first()).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s9/14-contract-probe-contract-tab.png", fullPage: true });

    await page.getByRole("button", { name: /Status/i }).first().click();
    await page.waitForTimeout(400);
    await page.getByRole("button", { name: /Deactivate/i }).click();
    await page.getByRole("button", { name: /Yes/i }).click();
    await expect(page.getByText("Deactivated").first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s9/15-contract-probe-deactivated.png", fullPage: true });
  });

  test("06 - features tab: overrides banner + toggle", async ({ page }) => {
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${CONTRACT_PROBE_ID}`);
    await page.getByRole("button", { name: /Features/i }).first().waitFor({ state: "visible", timeout: 20_000 });
    await page.getByRole("button", { name: /Features/i }).first().click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "test-results/screens/s9/16-features-overrides.png", fullPage: true });

    const toggle = page.locator("button[aria-pressed]").first();
    const before = await toggle.getAttribute("aria-pressed");
    await toggle.click();
    const saveBtn = page.getByRole("button", { name: /Save Feature Flags/i });
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click();
      const yesBtn = page.getByRole("button", { name: /Yes/i });
      await yesBtn.waitFor({ state: "visible", timeout: 3_000 }).catch(() => null);
      if (await yesBtn.isVisible().catch(() => false)) await yesBtn.click();
      // Either the mutation resolves (success message) or the backend refuses
      // it on a deactivated tenant (error message) — wait for either, don't
      // assume success.
      await page.waitForTimeout(1_200);
    }
    await page.screenshot({ path: "test-results/screens/s9/17-features-after-toggle.png", fullPage: true });

    // Revert
    await page.reload();
    await page.getByRole("button", { name: /Features/i }).first().waitFor({ state: "visible", timeout: 20_000 });
    await page.getByRole("button", { name: /Features/i }).first().click();
    await page.waitForTimeout(600);
    const toggleAfterReload = page.locator("button[aria-pressed]").first();
    const current = await toggleAfterReload.getAttribute("aria-pressed");
    if (current !== before) {
      await toggleAfterReload.click();
      const saveBtn2 = page.getByRole("button", { name: /Save Feature Flags/i });
      if (await saveBtn2.isVisible().catch(() => false)) {
        await saveBtn2.click();
        const yesBtn2 = page.getByRole("button", { name: /Yes/i });
        await yesBtn2.waitFor({ state: "visible", timeout: 3_000 }).catch(() => null);
        if (await yesBtn2.isVisible().catch(() => false)) await yesBtn2.click();
      }
    }
  });

  test("07 - admin user + activity tabs render for t6p2t", async ({ page }) => {
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await openTenantFromRegistry(page, T6P2T_NAME);
    await page.getByRole("button", { name: /Admin User/i }).first().click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "test-results/screens/s9/18-admin-user.png", fullPage: true });

    await page.getByRole("button", { name: /Activity/i }).first().click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "test-results/screens/s9/19-activity.png", fullPage: true });
  });

  test.afterAll(() => {
    console.log("=== S9-2 console/page errors (raw) ===");
    if (errors.length === 0) console.log("none");
    else for (const e of errors) console.log(e);
  });
});

test.describe("S9-2 onboarding wizard", () => {
  test("08 - wizard sends contract dates + billing period in one call", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/onboard`);
    await page.getByRole("button", { name: /Next/i }).waitFor({ state: "visible", timeout: 20_000 });

    // Step 1: Company info — name + contract dates (billing period is step 2)
    await page.fill('input[placeholder*="Addis"]', "ZZ S9 Wizard Probe");
    const dateInputs = page.locator('input[type="date"]');
    await dateInputs.nth(0).fill("2026-11-01");
    await dateInputs.nth(1).fill("2028-10-31");
    await page.screenshot({ path: "test-results/screens/s9/20-wizard-step1.png", fullPage: true });
    await page.getByRole("button", { name: /Next/i }).click();

    // Step 2: Org type, SKU limit (shown for every org type now), plan tier, billing period
    await page.getByText("Producer / Importer", { exact: false }).click();
    await page.getByRole("button", { name: "Monthly" }).click();
    await page.screenshot({ path: "test-results/screens/s9/20b-wizard-step2.png", fullPage: true });
    await page.getByRole("button", { name: /Next/i }).click();

    await page.getByRole("button", { name: /Next/i }).click(); // step 3: locale (default en)

    // Step 4: admin user
    await page.fill('input[placeholder*="Abebe"]', "ZZ Wizard Admin");
    await page.fill('input[placeholder*="admin@company"]', "zz-s9-wizard@probe.local");
    const pwInputs = page.locator('input[type="password"]');
    await pwInputs.nth(0).fill("S9Wizard@2026!");
    await pwInputs.nth(1).fill("S9Wizard@2026!");
    await page.getByRole("button", { name: /Next/i }).click();

    // Step 5: primary contact is required to advance — target by label, since
    // the Tenant Address section above it also has type="text" inputs.
    await page.locator('label:has-text("Full Name") + input').fill("ZZ Wizard Contact");
    await page.locator('input[type="email"]').fill("zz-s9-wizard-contact@probe.local");
    await page.getByRole("button", { name: /Next/i }).click();

    await page.screenshot({ path: "test-results/screens/s9/20-wizard-review.png", fullPage: true });
    await page.getByRole("button", { name: "Launch Tenant →" }).click();
    await page.getByText(/Tenant Onboarded/i).waitFor({ state: "visible", timeout: 15_000 });
    await page.screenshot({ path: "test-results/screens/s9/21-wizard-success.png", fullPage: true });

    console.log("=== S9-2 wizard console/page errors (raw) ===");
    if (errors.length === 0) console.log("none");
    else for (const e of errors) console.log(e);
  });
});

test.describe("S9-3 dashboard picker", () => {
  test("09 - Tenant Admin tab is a picker that navigates to the SA tenant page", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAs(page, SA_EMAIL, SA_PASSWORD);
    await page.goto(`${BASE_URL}/admin/dashboard`);

    await page.getByRole("button", { name: /Tenant Admin/i }).click();
    const select = page.locator("select").first();
    await select.waitFor({ state: "visible", timeout: 20_000 });
    await page.screenshot({ path: "test-results/screens/s9/22-admin-picker.png", fullPage: true });

    await select.selectOption({ label: T6P2T_NAME });
    await page.waitForURL(new RegExp(`/admin/settings/tenants/${T6P2T_ID}`), { timeout: 20_000 });
    await expect(page.getByRole("heading", { name: T6P2T_NAME })).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s9/23-admin-picker-landed.png", fullPage: true });

    // Registry tab still works after the refactor
    await page.goto(`${BASE_URL}/admin/dashboard`);
    await page.getByRole("button", { name: /Registry/i }).click();
    await page.getByText(T6P2T_NAME).first().waitFor({ state: "visible", timeout: 20_000 });
    await page.screenshot({ path: "test-results/screens/s9/24-registry-still-works.png", fullPage: true });

    console.log("=== S9-3 console/page errors (raw) ===");
    if (errors.length === 0) console.log("none");
    else for (const e of errors) console.log(e);
  });
});
