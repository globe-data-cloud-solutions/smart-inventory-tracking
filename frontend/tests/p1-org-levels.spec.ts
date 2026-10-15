/**
 * Playwright E2E — P1: Org Levels tab add/remove-bottom-level flow
 * (session/2026-10-12). Covers:
 *   - after save, "Add level" is visible and no middle level has a remove button
 *   - add flow PUTs a contiguous 4-level payload with the first 3 unchanged
 *   - remove-bottom 422 LEVEL_COUNT_LOCKED shows the friendly t() message
 *   - at 5 levels, "Add" is hidden
 *
 * GET/PUT /hierarchy/config are intercepted in every scenario below — no test
 * in this file ever sends a live PUT to the real backend. Service workers are
 * blocked so page.route reliably catches every request (see P4/P5 specs).
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p1-org-levels.spec.ts --reporter=line --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return; // expected gated round-trips (402/404/422)
    if (/Failed to fetch RSC payload.*Falling back to browser navigation/.test(msg.text())) return;
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

function fulfillError(route: Route, code: string, message: string, status = 422) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ detail: { code, message } }),
  });
}

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(
    path.join(__dirname, "..", "..", "locales", `${locale}.json`),
    "utf-8"
  );
  const d = JSON.parse(raw);
  const org = d.org_setup;
  return {
    addLevelBelow: (n: number) => (org.add_level_below as string).replace("{n}", String(n)),
    removeLevel: (n: number) => (org.remove_level as string).replace("{n}", String(n)),
    removeLevelBlocked: org.remove_level_blocked as string,
    confirmSave: org.confirm_save as string,
    save: d.common.save as string,
    newLevelHeading: (n: number) => (org.new_level_heading as string).replace("{n}", String(n)),
  };
}

const HIERARCHY_CONFIG_PATH = "**/api/v1/tenants/*/hierarchy/config";

function mkLevel(n: number, name: string, role: string) {
  return {
    id: `lvl-${n}`,
    tenant_id: "t1",
    level_number: n,
    level_name: name,
    default_role_code: role,
    role_display_label: null,
    is_stock_holding: n > 1,
    is_active: true,
  };
}

const THREE_LEVELS = [mkLevel(1, "Main Factory", "NM"), mkLevel(2, "Region", "RM"), mkLevel(3, "Warehouse", "WM")];
const FIVE_LEVELS = [
  mkLevel(1, "Main Factory", "NM"),
  mkLevel(2, "Region", "RM"),
  mkLevel(3, "Zone", "RM"),
  mkLevel(4, "Warehouse", "WM"),
  mkLevel(5, "Counter", "WM"),
];

for (const locale of ["en", "am"] as const) {
  test.describe(`Org Levels — add/remove bottom level (${locale})`, () => {
    test(`saved 3 levels: Add level visible, no remove on middle levels (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS);
        return route.continue();
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
      await page.waitForLoadState("networkidle");

      await expect(page.getByRole("button", { name: s.addLevelBelow(3) })).toBeVisible({ timeout: 10_000 });

      const removeButtons = page.getByRole("button", { name: /^Remove Level|^ደረጃ.*አስወግድ/ });
      await expect(removeButtons).toHaveCount(1);
      await expect(page.getByRole("button", { name: s.removeLevel(3) })).toBeVisible();

      console.log(`--- 3-levels (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`add flow PUTs 4 contiguous levels with the first 3 unchanged (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      let putBody: Array<{ level_number: number; level_name: string }> | null = null;

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        const method = route.request().method();
        if (method === "GET") return fulfillJson(route, THREE_LEVELS);
        if (method === "PUT") {
          putBody = route.request().postDataJSON();
          const newLevel = putBody![3];
          return fulfillJson(route, [...THREE_LEVELS, mkLevel(4, newLevel.level_name, "")]);
        }
        return route.continue();
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: s.addLevelBelow(3) }).click();
      await expect(page.getByText(s.newLevelHeading(4))).toBeVisible();

      const nameInputs = page.locator("input[type='text']");
      // The new-level form's name field is the first visible text input inside
      // the emerald add-level panel — scope by the panel's heading sibling.
      await page.getByText(s.newLevelHeading(4)).locator("..").locator("input[type='text']").first().fill("Sub-Warehouse");

      await page.getByRole("button", { name: s.save, exact: true }).click();
      // Confirmation dialog
      await page.getByRole("button", { name: s.confirmSave }).click();

      await expect.poll(() => putBody, { timeout: 10_000 }).not.toBeNull();
      expect(putBody).toHaveLength(4);
      expect(putBody![0]).toMatchObject({ level_number: 1, level_name: "Main Factory" });
      expect(putBody![1]).toMatchObject({ level_number: 2, level_name: "Region" });
      expect(putBody![2]).toMatchObject({ level_number: 3, level_name: "Warehouse" });
      expect(putBody![3]).toMatchObject({ level_number: 4, level_name: "Sub-Warehouse" });

      console.log(`--- add flow (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`remove-bottom 422 LEVEL_COUNT_LOCKED shows friendly message (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        const method = route.request().method();
        if (method === "GET") return fulfillJson(route, THREE_LEVELS);
        if (method === "PUT") {
          return fulfillError(route, "LEVEL_COUNT_LOCKED", "Cannot remove level 3 — active org nodes exist at that level. Remove or move those nodes first.");
        }
        return route.continue();
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: s.removeLevel(3) }).click();
      await page.getByRole("button", { name: s.confirmSave }).click();

      await expect(page.getByText(s.removeLevelBlocked)).toBeVisible({ timeout: 10_000 });

      console.log(`--- remove blocked (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`at 5 levels, Add is hidden (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, FIVE_LEVELS);
        return route.continue();
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
      await page.waitForLoadState("networkidle");

      await expect(page.getByRole("button", { name: /^Add level below|^ከደረጃ.*በታች ደረጃ አክል/ })).toHaveCount(0);
      await expect(page.getByRole("button", { name: s.removeLevel(5) })).toBeVisible();

      console.log(`--- 5-levels (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
