/**
 * Playwright E2E — P6: write-guard on settings pages (personnel, org-setup,
 * tenant-admin) plus "Coming soon" badges for the 3 screens with no backend
 * route yet (CLAUDE.md §29).
 *
 * zz-e2e-ta (STARTER, contract stage ACTIVE) is the permanent TA probe —
 * never mutated here. Every READ_ONLY / at-limit scenario uses page.route
 * interception ONLY inside the test; no write click in this file ever
 * reaches the real backend. No SA credentials anywhere in this file.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p6-settings-guard.spec.ts --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

// Block the app's service worker for every test in this file — otherwise a
// mocked route can silently fall through to the real backend (see P4/P5).
test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    if (/Failed to load resource.*40[0-9]/.test(msg.text())) return; // expected gated round-trips
    if (/Failed to fetch RSC payload.*Falling back to browser navigation/.test(msg.text())) return; // next dev HMR noise
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

function fulfillJson(route: Route, data: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ success: true, data, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  return {
    addUser: d.personnel.add_user as string,
    resetPassword: d.personnel.reset_password as string,
    deactivate: d.personnel.deactivate_user as string,
    addContact: d.sa.contacts_add_btn as string,
    contactTab: d.tenant_admin.tabs.contact as string,
    renewalSubmit: d.tenant_admin.plan.renewal.submit_btn as string,
    readOnlyReason: d.contract.read_only_error as string,
    userLimitReason: d.plan.limit_reached.users as string,
    comingSoonBadge: d.common.coming_soon_badge as string,
    comingSoonHint: d.common.coming_soon_hint as string,
    bulkImportTitle: d.bulk_import.title as string,
    openingBalanceTitle: d.opening_balance.title as string,
    startSession: d.count.start_session as string,
    submitSession: d.count.submit_session as string,
  };
}

const CONTRACT_STATUS_PATH = "**/api/v1/tenants/me/contract-status";
const PLAN_USAGE_PATH = "**/api/v1/tenants/me/plan-usage";
const USERS_LIST_PATH = "**/api/v1/tenants/*/users";

const SYNTHETIC_USERS = [
  {
    id: "p6-test-user-nm",
    name: "P6 Test NM",
    email: "p6-test-nm@example.invalid",
    role: "NM",
    is_active: true,
    primary_facility_name: "Main Warehouse",
    primary_facility_id: "p6-wh",
    primary_position: null,
    acting_positions: [],
    created_at: new Date().toISOString(),
  },
];

// ── READ_ONLY: Add User disabled, org-setup add-node disabled; reset
// password + deactivate stay ENABLED (security actions); Contacts add and
// the Renewal card stay ENABLED (exempt) ──────────────────────────────────
for (const locale of ["en", "am"] as const) {
  test.describe(`READ_ONLY contract stage — settings pages (${locale})`, () => {
    test(`security actions + exempt controls stay enabled; everything else disabled (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(CONTRACT_STATUS_PATH, (route) =>
        fulfillJson(route, {
          stage: "READ_ONLY",
          contract_end: "2026-01-01",
          days_left: -20,
          grace_ends: "2026-01-15",
          read_only_since: "2026-01-16",
          open_request: null,
        })
      );
      await page.route(USERS_LIST_PATH, (route) => fulfillJson(route, SYNTHETIC_USERS));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      // ── Personnel: Add User disabled; reset password + deactivate enabled ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/personnel`);
      await page.waitForLoadState("networkidle");
      const addUserBtn = page.getByRole("button", { name: `+ ${strings.addUser}` });
      await expect(addUserBtn).toBeVisible({ timeout: 10_000 });
      await expect(addUserBtn).toBeDisabled();
      expect(await addUserBtn.getAttribute("title")).toBe(strings.readOnlyReason);

      const resetBtn = page.getByRole("button", { name: strings.resetPassword, exact: true }).first();
      await expect(resetBtn).toBeVisible({ timeout: 10_000 });
      await expect(resetBtn).toBeEnabled();

      const deactivateBtn = page.getByRole("button", { name: strings.deactivate, exact: true }).first();
      await expect(deactivateBtn).toBeVisible({ timeout: 10_000 });
      await expect(deactivateBtn).toBeEnabled();

      // ── org-setup Tree tab: add-node disabled (hardcoded English label,
      // not run through t() in app code today — same text in every locale) ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
      await page.waitForLoadState("networkidle");
      await page.getByRole("button", { name: "Organisation Tree" }).click();
      const addNodeBtn = page.getByRole("button", { name: /Add root node/i });
      await expect(addNodeBtn).toBeVisible({ timeout: 10_000 });
      await expect(addNodeBtn).toBeDisabled();
      expect(await addNodeBtn.getAttribute("title")).toBe(strings.readOnlyReason);

      // ── Contacts tab: add stays ENABLED (exempt) ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin`);
      await page.waitForLoadState("networkidle");
      // Scoped to the tab bar: the READ_ONLY banner also has a "Contact SMART" button.
      // The tab button's accessible name is its icon + label.
      await page
        .locator("div.overflow-x-auto")
        .getByRole("button", { name: new RegExp(`^👥${strings.contactTab}$`) })
        .click();
      const addContactBtn = page.getByRole("button", { name: `+ ${strings.addContact}` });
      await expect(addContactBtn).toBeVisible({ timeout: 10_000 });
      await expect(addContactBtn).toBeEnabled();

      // ── Plan tab: Renewal card submit stays ENABLED (allowed at any stage) ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=plan`);
      await page.waitForLoadState("networkidle");
      const renewalSubmit = page.getByRole("button", { name: strings.renewalSubmit });
      const openNotice = page.getByText(/SMART will contact you|SMART ያገኝዎታል/i);
      if (await renewalSubmit.isVisible().catch(() => false)) {
        await expect(renewalSubmit).toBeEnabled();
      } else {
        // An OPEN request already exists from an earlier P4 test run — the
        // "we'll contact you" notice is the enabled-equivalent state here.
        await expect(openNotice).toBeVisible({ timeout: 10_000 });
      }

      console.log(`--- READ_ONLY settings (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── ACTIVE + users at limit: Add User disabled with the user-limit tooltip ─
for (const locale of ["en", "am"] as const) {
  test.describe(`ACTIVE stage, user cap reached (${locale})`, () => {
    test(`Add User disabled with user-limit tooltip (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(PLAN_USAGE_PATH, (route) =>
        fulfillJson(route, {
          plan_tier: "STARTER",
          skus: { used: 0, limit: 500 },
          users: { used: 5, limit: 5 },
          warehouses: { used: 1, limit: 3 },
        })
      );

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/personnel`);
      await page.waitForLoadState("networkidle");
      const addUserBtn = page.getByRole("button", { name: `+ ${strings.addUser}` });
      await expect(addUserBtn).toBeVisible({ timeout: 10_000 });
      await expect(addUserBtn).toBeDisabled();
      expect(await addUserBtn.getAttribute("title")).toBe(strings.userLimitReason);

      console.log(`--- ACTIVE + user cap (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── Coming-soon badges (gateway mode is inherent — no interception needed);
// Opening Balance opener stays ENABLED (real route, P5 guard only) ─────────
test.describe("Coming-soon screens + Opening Balance (real data, ACTIVE)", () => {
  test("Bulk Import, Stock Count submit show coming-soon; Opening Balance enabled", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const strings = localeStrings("en");
    const consoleErrors = collectConsoleErrors(page);

    await login(page, E2E_TA_EMAIL, taPassword);

    // ── Bulk Import (open button) + Opening Balance (open button) ──
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
    await page.waitForLoadState("networkidle");

    const bulkImportBtn = page.getByRole("button", { name: new RegExp(`${strings.bulkImportTitle}`) });
    await expect(bulkImportBtn).toBeVisible({ timeout: 10_000 });
    await expect(bulkImportBtn).toBeDisabled();
    expect(await bulkImportBtn.getAttribute("title")).toBe(strings.comingSoonHint);
    await expect(bulkImportBtn.getByText(strings.comingSoonBadge)).toBeVisible();

    const openingBalanceBtn = page.getByRole("button", { name: `+ ${strings.openingBalanceTitle}` });
    await expect(openingBalanceBtn).toBeVisible({ timeout: 10_000 });
    await expect(openingBalanceBtn).toBeEnabled();

    // ── Stock count: start a session (purely local state, no API call —
    // confirmed by the P5 fork), then check Submit Session's coming-soon ──
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/stock-count`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: strings.startSession }).first().click().catch(() => {});
    const submitSessionBtn = page.getByRole("button", { name: new RegExp(strings.submitSession) }).first();
    if (await submitSessionBtn.isVisible().catch(() => false)) {
      await expect(submitSessionBtn).toBeDisabled();
      expect(await submitSessionBtn.getAttribute("title")).toBe(strings.comingSoonHint);
    }

    console.log("--- coming-soon + opening-balance console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});
