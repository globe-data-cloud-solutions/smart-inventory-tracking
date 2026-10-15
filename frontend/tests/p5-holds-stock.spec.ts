/**
 * Playwright E2E — P5: guarded "Holds stock" changes for saved levels and
 * existing nodes (session/2026-10-12). Covers:
 *   - level toggle off blocked -> LEVEL_HAS_STOCK_NODES message lists names
 *   - level toggle on -> confirm dialog, then PATCH body {is_stock_holding:true}
 *   - node toggle off -> friendly NODE_STOCK_ACTIVITY message (NODE_HAS_STOCK reason)
 *   - node toggle on at cap -> existing plan-limit notice
 *   - "Save Levels" button text is translated in am
 *
 * GET/PATCH /hierarchy/config, GET /nodes, PATCH /nodes/{id}, and GET
 * /me/plan-usage are intercepted in every scenario below — no test in this
 * file ever sends a live write to the real backend. Service workers are
 * blocked so page.route reliably catches every request (see P1/P4 specs).
 *
 * zz-e2e-ta (STARTER) is the permanent TA probe — never mutated here.
 * No SA credentials anywhere in this file.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p5-holds-stock.spec.ts --reporter=line --workers=1
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
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return; // expected gated round-trips (402/422)
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

function fulfillError(route: Route, detail: Record<string, unknown>, status = 422) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ detail }),
  });
}

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  const org = d.org_setup;
  return {
    saveLevels: org.save_levels as string,
    confirmLevelOnTitle: org.confirm_level_on_title as string,
    confirmLevelOnBody: org.confirm_level_on_body as string,
    confirmSave: org.confirm_save as string,
    levelHasStockNodes: (names: string) => (org.level_has_stock_nodes as string).replace("{names}", names),
    nodeStockActivityStock: org.node_stock_activity_stock as string,
    isStockHoldingLabel: org.is_stock_holding as string,
    warehouseCapNotice: (tier: string, limit: number) =>
      (org.warehouse_cap_notice as string).replace("{tier}", tier).replace("{limit}", String(limit)),
  };
}

const HIERARCHY_CONFIG_PATH = "**/api/v1/tenants/*/hierarchy/config/*";
const NODES_PATH = "**/api/v1/tenants/*/nodes*";
const NODE_PATCH_PATH = "**/api/v1/tenants/*/nodes/node-wh";
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

const THREE_LEVELS = [
  mkLevel(1, "Main Factory", "NM", true),
  mkLevel(2, "Region", "RM", false),
  mkLevel(3, "Warehouse", "WM", true),
];

function mkNode(id: string, name: string, level: number, isStockHolding: boolean) {
  return {
    id,
    name,
    code: id.toUpperCase(),
    hierarchy_level: level,
    level_name: level === 1 ? "Main Factory" : level === 2 ? "Region" : "Warehouse",
    is_stock_holding: isStockHolding,
    parent_node_id: null,
    manager_name: null,
    manager_role: null,
    is_active: true,
    children: [],
  };
}

const ONE_NODE_TREE = [mkNode("node-wh", "WH North", 3, true)];

function planUsage(used: number, limit: number | null, tier = "STARTER") {
  return {
    plan_tier: tier,
    skus: { used: 10, limit: 500 },
    users: { used: 1, limit: 5 },
    warehouses: { used, limit },
  };
}

async function gotoLevels(page: Page) {
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
  await page.waitForLoadState("networkidle");
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Org Setup — holds-stock guard (${locale})`, () => {
    test(`level toggle off blocked: lists node names (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(HIERARCHY_CONFIG_PATH, (route) => {
        if (route.request().method() === "PATCH") {
          return fulfillError(route, {
            code: "LEVEL_HAS_STOCK_NODES",
            nodes: [{ id: "node-wh", name: "WH North" }],
            message: "Switch these locations to approval-only first.",
          });
        }
        return route.continue();
      });
      await page.route("**/api/v1/tenants/*/hierarchy/config", (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(2, 5)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      // THREE_LEVELS row order: 1 Main Factory, 2 Region, 3 Warehouse (index 2).
      // Level 3 ("Warehouse") is currently stock-holding — uncheck its box.
      const row = page.locator("tbody tr").nth(2);
      await row.locator('input[type="checkbox"]').click();

      await expect(page.getByText(s.levelHasStockNodes("WH North"))).toBeVisible({ timeout: 10_000 });

      console.log(`--- level off blocked (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`level toggle on: confirm dialog then PATCH body is_stock_holding=true (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      let patchBody: unknown = null;
      await page.route("**/api/v1/tenants/*/hierarchy/config/lvl-2", (route) => {
        if (route.request().method() === "PATCH") {
          patchBody = route.request().postDataJSON();
          return fulfillJson(route, { ...THREE_LEVELS[1], is_stock_holding: true });
        }
        return route.continue();
      });
      await page.route("**/api/v1/tenants/*/hierarchy/config", (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(2, 5)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      // THREE_LEVELS row order: 1 Main Factory, 2 Region, 3 Warehouse (index 1).
      // Level 2 ("Region") is currently approval-only — check its box to turn it on.
      const row = page.locator("tbody tr").nth(1);
      await row.locator('input[type="checkbox"]').click();

      await expect(page.getByText(s.confirmLevelOnTitle)).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(s.confirmLevelOnBody)).toBeVisible();
      await page.getByRole("button", { name: s.confirmSave }).click();

      await expect.poll(() => patchBody, { timeout: 10_000 }).toEqual({ is_stock_holding: true });

      console.log(`--- level on confirm (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`node toggle off blocked by stock: friendly NODE_STOCK_ACTIVITY message (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route("**/api/v1/tenants/*/hierarchy/config", (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS);
        return route.continue();
      });
      await page.route(NODES_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, ONE_NODE_TREE);
        return route.continue();
      });
      await page.route(NODE_PATCH_PATH, (route) => {
        if (route.request().method() === "PATCH") {
          return fulfillError(route, {
            code: "NODE_STOCK_ACTIVITY",
            reason: "NODE_HAS_STOCK",
            message: "Move or issue the remaining stock and close open transfers/adjustments "
              + "before making this an approval-only location.",
          });
        }
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(2, 5)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await page.getByRole("button", { name: "Organisation Tree" }).click();
      await expect(page.getByText("WH North")).toBeVisible({ timeout: 10_000 });

      await page.getByTitle("Edit node").click();
      const holdsStockCheckbox = page.locator("label", { hasText: s.isStockHoldingLabel })
        .locator('input[type="checkbox"]');
      await holdsStockCheckbox.uncheck();
      await page.getByRole("button", { name: "Save Node" }).click();

      await expect(page.getByText(s.nodeStockActivityStock)).toBeVisible({ timeout: 10_000 });

      console.log(`--- node off blocked by stock (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`node toggle on at plan cap: existing plan-limit notice shown (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route("**/api/v1/tenants/*/hierarchy/config", (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, THREE_LEVELS);
        return route.continue();
      });
      await page.route(NODES_PATH, (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, [mkNode("node-wh", "WH North", 3, false)]);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(1, 1, "STARTER")));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await page.getByRole("button", { name: "Organisation Tree" }).click();
      await expect(page.getByText("WH North")).toBeVisible({ timeout: 10_000 });

      await page.getByTitle("Edit node").click();
      const holdsStockCheckbox = page.locator("label", { hasText: s.isStockHoldingLabel })
        .locator('input[type="checkbox"]');
      await holdsStockCheckbox.check();

      await expect(page.getByText(s.warehouseCapNotice("Starter", 1)).first()).toBeVisible({ timeout: 10_000 });
      await expect(page.getByRole("button", { name: "Save Node" })).toBeDisabled();

      console.log(`--- node on at cap (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`"Save Levels" button is translated (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route("**/api/v1/tenants/*/hierarchy/config", (route) => {
        if (route.request().method() === "GET") return fulfillJson(route, []);
        return route.continue();
      });
      await page.route(PLAN_USAGE_PATH, (route) => fulfillJson(route, planUsage(2, 5)));

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoLevels(page);

      await expect(page.getByRole("button", { name: s.saveLevels })).toBeVisible({ timeout: 10_000 });

      console.log(`--- save levels translated (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
