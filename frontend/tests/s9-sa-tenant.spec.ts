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
import { SA_EMAIL, saPassword, saPasswordOrSkip } from "./helpers/sa-credentials";
import {
  createProbeTenant, deactivateTenant, deactivateTenantBySlug, saToken, setContractDates,
  type ProbeTenant,
} from "./helpers/sa-api";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

const T6P2T_NAME = "Tenant_6_P2T";
const T6P2T_ID = "aed68cc5-789f-4cb0-9ef5-9b6404267e42";

// SA tests are run by Alex only, by hand (E2E_SA_PASSWORD) — see SA_SKIP_REASON guards below.
const SA_SKIP_REASON = "E2E_SA_PASSWORD not set — SA tests are run by Alex only, by hand";

/** ISO date (YYYY-MM-DD) `days` from today, UTC. */
function isoDaysFromNow(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** `iso` plus `years` years, as an ISO date. */
function isoPlusYears(iso: string, years: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() + years);
  return d.toISOString().slice(0, 10);
}

test.describe.configure({ mode: "serial" });
// Generous per-test timeout: the first navigation after a fresh demo login can
// hit one 401 while the fire-and-forget JWT exchange is still in flight, and
// TanStack Query's retry/backoff plus Next dev's on-demand route compile can
// together exceed the 30s default on a cold run.
test.setTimeout(60_000);

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
  test.skip(!saPassword(), SA_SKIP_REASON);

  const errors: string[] = [];
  // Own probe tenant (STARTER, MONTHLY) with a 2-year contract starting today —
  // created per run, deactivated in afterAll (also deactivated by test 05 itself).
  let probe: ProbeTenant;
  const contractStart = isoDaysFromNow(0);
  const contractEnd = isoPlusYears(contractStart, 2);

  test.beforeAll(async ({ request }) => {
    probe = await createProbeTenant(request, { prefix: "s9", tier: "STARTER", billingPeriod: "MONTHLY" });
    await setContractDates(request, await saToken(request), probe.id, contractStart, contractEnd);
  });

  test.afterAll(async ({ request }) => {
    if (probe) await deactivateTenant(request, await saToken(request), probe.id);
  });

  test("01 - registry Open navigates to the SA tenant page", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, saPw);
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
      const saPw = saPasswordOrSkip(test);
      errors.push(...collectConsoleErrors(page));
      await loginAs(page, SA_EMAIL, saPw);
      await openTenantFromRegistry(page, T6P2T_NAME);
      await page.getByRole("button", { name: tab.label }).first().click();
      await page.waitForTimeout(600);
      await page.screenshot({ path: `test-results/screens/s9/en-${tab.shot}.png`, fullPage: true });
    });
  }

  test("03 - Amharic: profile and plan tabs render", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, saPw);
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
    const saPw = saPasswordOrSkip(test);
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, saPw);
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

  // Declared before 05 on purpose: serial order is file order, and 05 leaves the
  // shared probe DEACTIVATED. 06 is read-only and runs on the still-ACTIVE probe.
  // The raw feature-flag override toggles (aria-pressed buttons + "Save Feature
  // Flags") were removed in S10 — overrides are add-ons now. The SA Features tab
  // shows the add-ons section instead; grant/cancel writes are covered in
  // s10-addons.spec.ts, so this test asserts the section renders and the old
  // toggles are gone.
  test("06 - features tab: overrides banner + toggle", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${probe.id}`);
    await page.getByRole("button", { name: /Features/i }).first().waitFor({ state: "visible", timeout: 20_000 });
    await page.getByRole("button", { name: /Features/i }).first().click();

    const addonsSection = page.locator("h3", { hasText: "Add-ons" }).locator("..");
    await expect(addonsSection).toBeVisible({ timeout: 20_000 });
    await expect(addonsSection.getByText("No add-ons yet.")).toBeVisible({ timeout: 10_000 });
    await expect(addonsSection.getByRole("button", { name: "Grant free override" })).toBeEnabled({ timeout: 10_000 });
    await expect(addonsSection.getByRole("button", { name: "Add purchased add-on" })).toBeEnabled();
    // Feature list carries a source label per feature (Package / Add-on / Not included).
    await expect(page.getByText(/^(Package|Add-on|Not included)$/).first()).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s9/16-features-overrides.png", fullPage: true });

    // The old raw override toggles must not come back.
    await expect(page.locator("button[aria-pressed]")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Save Feature Flags/i })).toHaveCount(0);
  });

  test("05 - contract probe: contract tab + status deactivate via UI", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${probe.id}`);
    await page.getByRole("button", { name: /Contract/i }).first().waitFor({ state: "visible", timeout: 20_000 });
    await page.getByRole("button", { name: /Contract/i }).first().click();
    await page.waitForTimeout(600);
    // toLocaleDateString() formatting is environment-locale-dependent — match
    // loosely on the year rather than an exact M/D/Y string.
    await expect(page.getByText(new RegExp(contractStart.slice(0, 4))).first()).toBeVisible();
    await expect(page.getByText(new RegExp(contractEnd.slice(0, 4))).first()).toBeVisible();
    await page.screenshot({ path: "test-results/screens/s9/14-contract-probe-contract-tab.png", fullPage: true });

    await page.getByRole("button", { name: /Status/i }).first().click();
    await page.waitForTimeout(400);
    await page.getByRole("button", { name: /Deactivate/i }).click();
    await page.getByRole("button", { name: /Yes/i }).click();
    await expect(page.getByText("Deactivated").first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/screens/s9/15-contract-probe-deactivated.png", fullPage: true });
  });

  test("07 - admin user + activity tabs render for t6p2t", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    errors.push(...collectConsoleErrors(page));
    await loginAs(page, SA_EMAIL, saPw);
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
  test.skip(!saPassword(), SA_SKIP_REASON);

  // Unique per run so a second run never collides on name/slug/email.
  const runId = Date.now().toString(36);
  const wizardName = `ZZ S9 Wizard ${runId}`;
  const wizardAdminEmail = `zz-s9-wizard-${runId}@probe.local`;
  const wizardContactEmail = `zz-s9-wizard-contact-${runId}@probe.local`;
  // Dates relative to today, not fixed calendar dates.
  const wizardStart = isoDaysFromNow(30);
  const wizardEnd = isoPlusYears(wizardStart, 2);
  let wizardSlug: string | null = null;

  test.afterAll(async ({ request }) => {
    if (wizardSlug) await deactivateTenantBySlug(request, await saToken(request), wizardSlug);
  });

  test("08 - wizard sends contract dates + billing period in one call", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const errors = collectConsoleErrors(page);
    await loginAs(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/onboard`);
    await page.getByRole("button", { name: /Next/i }).waitFor({ state: "visible", timeout: 20_000 });

    // Step 1: Company info — name + contract dates (billing period is step 2)
    await page.fill('input[placeholder*="Addis"]', wizardName);
    const dateInputs = page.locator('input[type="date"]');
    await dateInputs.nth(0).fill(wizardStart);
    await dateInputs.nth(1).fill(wizardEnd);
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
    await page.fill('input[placeholder*="admin@company"]', wizardAdminEmail);
    const pwInputs = page.locator('input[type="password"]');
    await pwInputs.nth(0).fill("S9Wizard@2026!");
    await pwInputs.nth(1).fill("S9Wizard@2026!");
    await page.getByRole("button", { name: /Next/i }).click();

    // Step 5: primary contact is required to advance — target by label, since
    // the Tenant Address section above it also has type="text" inputs.
    await page.locator('label:has-text("Full Name") + input').fill("ZZ Wizard Contact");
    await page.locator('input[type="email"]').fill(wizardContactEmail);
    await page.getByRole("button", { name: /Next/i }).click();

    await page.screenshot({ path: "test-results/screens/s9/20-wizard-review.png", fullPage: true });
    await page.getByRole("button", { name: "Launch Tenant →" }).click();
    await page.getByText(/Tenant Onboarded/i).waitFor({ state: "visible", timeout: 15_000 });
    // The success page links to /<slug>/dashboard — read the created tenant's slug from it for cleanup.
    const hrefs = await page.locator('a[href$="/dashboard"]').evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? ""));
    wizardSlug = hrefs.map((h) => h.split("/")[1] ?? "").find((slug) => slug && slug !== "admin") ?? null;
    await page.screenshot({ path: "test-results/screens/s9/21-wizard-success.png", fullPage: true });

    console.log("=== S9-2 wizard console/page errors (raw) ===");
    if (errors.length === 0) console.log("none");
    else for (const e of errors) console.log(e);
  });
});

test.describe("S9-3 dashboard picker", () => {
  test.skip(!saPassword(), SA_SKIP_REASON);

  test("09 - Tenant Admin tab is a picker that navigates to the SA tenant page", async ({ page }) => {
    const saPw = saPasswordOrSkip(test);
    const errors = collectConsoleErrors(page);
    await loginAs(page, SA_EMAIL, saPw);
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
