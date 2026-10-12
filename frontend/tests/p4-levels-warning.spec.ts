/**
 * Playwright E2E — P4: Org Levels tab warehouse-limit info line and
 * over-capacity warning (CLAUDE.md §29). Frontend/locale only — no level,
 * tree, validation, default, or backend behaviour is exercised here beyond
 * what P1's org-levels spec already covers.
 *
 * zz-e2e-ta (STARTER) is the permanent TA probe — never mutated here.
 * GET hierarchy/config and GET /me/plan-usage are intercepted in every
 * scenario below; no write is ever sent. Service workers are blocked so
 * page.route reliably catches every request.
 *
 * No SA credentials anywhere in this file.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p4-levels-warning.spec.ts --reporter=line --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return; // expected gated round-trips
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

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  const org = d.org_setup;
  return {
    infoLine: (limit: number) =>
      (org.warehouse_limit_info_line as string).replace("{tier}", "Starter").replace("{limit}", String(limit)),
    infoLineUnlimited: org.warehouse_limit_info_line_unlimited as string,
    warning: (n: number, limit: number) =>
      (org.levels_over_capacity_warning as string)
        .replace("{n}", String(n)).replace("{n}", String(n))
        .replace("{tier}", "Starter").replace("{limit}", String(limit)),
    levelHint: org.level_stock_holding_plan_hint as string,
    comparePlans: d.tenant_admin.features.compare_plans_link as string,
    requestUpgrade: d.tenant_admin.features.request_upgrade_btn as string,
    saveLevels: "Save Levels",
  };
}

const HIERARCHY_CONFIG_PATH = "**/api/v1/tenants/*/hierarchy/config";
const PLAN_USAGE_PATH = "**/api/v1/tenants/me/plan-usage";

function mkLevel(n: number, name: string, role: string, isStockHolding: boolean) {
  return {
    id: `lvl-${n}`,
    tenant_id: "t1",
    level_number: n,
    level_name: name,
    default_role_code: role,
    role_display_label: null,
    is_stock_holding: isStockHolding,
    is_active: true,
  };
}

const THREE_LEVELS_ALL_STOCK = [
  mkLevel(1, "Main Factory", "NM", true),
  mkLevel(2, "Region", "RM", true),
  mkLevel(3, "Warehouse", "WM", true),
];

const FIVE_LEVELS_ALL_STOCK = [
  mkLevel(1, "Main Factory", "NM", true),
  mkLevel(2, "Region", "RM", true),
  mkLevel(3, "Zone", "RM", true),
  mkLevel(4, "Warehouse", "WM", true),
  mkLevel(5, "Counter", "WM", true),
];

function planUsage(limit: number | null, tier = "STARTER") {
  return {
    plan_tier: tier,
    skus: { used: 10, limit: 500 },
    users: { used: 1, limit: 5 },
    warehouses: { used: limit ?? 0, limit },
  };
}

async function gotoLevels(page: Page) {
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
  await page.waitForLoadState("networkidle");
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Org Levels — warehouse-limit guidance (${locale})`, () => {
    test(`limit 3 + 3 stock levels: info line shown, no warning (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS_ALL_STOCK);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(3)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await expect(page.getByText(s.infoLine(3))).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/⚠/)).toHaveCount(0);

      console.log(`--- 3-stock, limit 3 (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`limit 3 + 5 stock levels: warning with Compare plans + Request upgrade (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, FIVE_LEVELS_ALL_STOCK);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(3)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await expect(page.getByText(s.warning(5, 3))).toBeVisible({ timeout: 10_000 });

      const compareBtn = page.getByRole("button", { name: s.comparePlans });
      await expect(compareBtn).toBeVisible();
      await expect(page.getByRole("button", { name: s.requestUpgrade })).toBeVisible();

      await compareBtn.click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10_000 });
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);

      console.log(`--- 5-stock, limit 3 (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`limit null: "no warehouse limit" text, no warning regardless of count (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, FIVE_LEVELS_ALL_STOCK);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(null, "ENTERPRISE")));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await expect(page.getByText(s.infoLineUnlimited)).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/⚠/)).toHaveCount(0);

      console.log(`--- unlimited (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`per-level "Holds stock" hint is visible on every row (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS_ALL_STOCK);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(3)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await expect(page.getByText(s.levelHint)).toHaveCount(THREE_LEVELS_ALL_STOCK.length, { timeout: 10_000 });

      console.log(`--- per-level hint (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`warning never disables Save Levels (pre-save, unsaved default levels) (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      // Not yet saved — GET returns empty, so the component falls back to its
      // local default 3-level set (level 1 approval-only, levels 2-3 stock-holding
      // => 2 stock-holding levels), which already exceeds a limit of 1.
      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, []);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(1)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await expect(page.getByText(s.warning(2, 1))).toBeVisible({ timeout: 10_000 });

      const saveBtn = page.getByRole("button", { name: s.saveLevels });
      await expect(saveBtn).toBeVisible();
      await expect(saveBtn).toBeEnabled();

      console.log(`--- save not disabled (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
