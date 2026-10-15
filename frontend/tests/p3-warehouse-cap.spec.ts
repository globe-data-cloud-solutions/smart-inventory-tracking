/**
 * Playwright E2E — P3: warehouse cap counts stock-holding org nodes only
 * (CLAUDE.md §29). Covers the Org Tree tab's live usage counter, the
 * cap notice (Compare plans + Request upgrade), and the friendly 402
 * PLAN_LIMIT_REACHED message on reactivate.
 *
 * zz-e2e-ta (STARTER) is the permanent TA probe — never mutated here.
 * Every node create/update/reactivate request in this file is intercepted
 * and fulfilled; no write click ever reaches the real backend (service
 * workers are blocked below so page.route reliably catches every request).
 *
 * No SA credentials anywhere in this file.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p3-warehouse-cap.spec.ts --workers=1 --reporter=line
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
    if (/Failed to load resource.*40[0-9]/.test(msg.text())) return; // expected gated round-trips
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

function fulfillError(route: Route, status: number, detail: Record<string, unknown>) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ success: false, error: detail, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  return {
    isStockHolding: d.org_setup.is_stock_holding as string,
    warehouseNote: d.org_setup.warehouse_usage_note as string,
    capNotice: (d.org_setup.warehouse_cap_notice as string)
      .replace("{tier}", "Starter")
      .replace("{limit}", "3"),
    unlimited: d.org_setup.warehouse_usage_unlimited as string,
    comparePlans: d.tenant_admin.features.compare_plans_link as string,
    requestUpgrade: d.tenant_admin.features.request_upgrade_btn as string,
    limitReachedWarehouses: d.plan.limit_reached.warehouses as string,
    reactivateBtn: d.org_setup.reactivate_node as string,
    levelApprovalOnlyHint: d.org_setup.level_approval_only_hint as string,
  };
}

const TENANT_META_PATH = new RegExp(`/api/v1/tenants/${E2E_TA_SLUG}(\\?.*)?$`);
const PLAN_USAGE_PATH = /\/api\/v1\/tenants\/me\/plan-usage(\?.*)?$/;
const HIERARCHY_CONFIG_PATH = /\/api\/v1\/tenants\/[^/]+\/hierarchy\/config(\?.*)?$/;
// Matches both the list endpoint (GET/POST .../nodes) and a single node's
// sub-actions (PATCH .../nodes/{id}, .../nodes/{id}/reactivate, .../deactivate).
const NODES_PATH = /\/api\/v1\/tenants\/[^/]+\/nodes(\/[^/?]+)?(\/(reactivate|deactivate))?(\?.*)?$/;
const APPROVAL_COVERAGE_PATH = /\/api\/v1\/tenants\/[^/]+\/approval-coverage(\?.*)?$/;
const CLONE_PERMS_PATH = /\/clone-level-permissions(\?.*)?$/;

const FAKE_TENANT_ID = "aaaaaaaa-1111-1111-1111-000000000001";

// Root nodes always land on L1 (NodeForm's childLevel is 1 when there is no
// parent — see "Add root node (L1)" in org-setup/page.tsx), so L1 must hold
// stock for these warehouse-cap scenarios to exercise a stock-holding node.
// L2 is deliberately approval-only (is_stock_holding: false) to cover the
// level holds-stock guard: a node added under an L1 parent must default to
// a disabled, unchecked "Holds stock" checkbox with its hint.
const LEVELS = [
  { id: "lvl-1", level_number: 1, level_name: "Warehouse", default_role_code: "WM", role_display_label: "Warehouse Manager", is_stock_holding: true },
  { id: "lvl-2", level_number: 2, level_name: "Regional Office", default_role_code: "RM", role_display_label: "Regional Manager", is_stock_holding: false },
];

function rootNode(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "node-root-1",
    name: "Head Office",
    code: "HO-1",
    address: null,
    hierarchy_level: 1,
    parent_node_id: null,
    is_stock_holding: true,
    is_active: true,
    children: [],
    ...overrides,
  };
}

async function gotoOrgTree(page: Page) {
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Organisation Tree" }).click();
  await page.waitForLoadState("networkidle");
}

async function mockCommon(page: Page, nodes: unknown[]) {
  await page.route(TENANT_META_PATH, (route) => fulfillJson(route, { id: FAKE_TENANT_ID, name: "E2E TA" }));
  await page.route(HIERARCHY_CONFIG_PATH, (route) => fulfillJson(route, LEVELS));
  await page.route(APPROVAL_COVERAGE_PATH, (route) =>
    fulfillJson(route, {
      transfer_rules_exist: true, transfer_level_covered: true,
      adj_rules_exist: true, adj_level_covered: true,
      self_approval_covered: true, transfer_level_perms_exist: true,
    })
  );
  await page.route(CLONE_PERMS_PATH, (route) => fulfillJson(route, {}));
  await page.route(NODES_PATH, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, nodes);
  });
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Org Tree — warehouse usage counter (${locale})`, () => {
    test(`counter renders and updates live after a stock-holding node is created (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      let planUsageUsed = 2;
      await page.route(PLAN_USAGE_PATH, (route) =>
        fulfillJson(route, {
          plan_tier: "STARTER",
          skus: { used: 10, limit: 500 },
          users: { used: 1, limit: 5 },
          warehouses: { used: planUsageUsed, limit: 3 },
        })
      );
      let nodeCreated = false;
      await mockCommon(page, [rootNode()]);
      await page.route(NODES_PATH, (route) => {
        const req = route.request();
        if (req.method() === "POST") {
          nodeCreated = true;
          planUsageUsed = 3;
          return fulfillJson(route, rootNode({ id: "node-new-1", name: "New Warehouse", is_stock_holding: true }), 201);
        }
        if (req.method() !== "GET") return route.fallback();
        return fulfillJson(route, [rootNode()]);
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoOrgTree(page);

      await expect(page.getByText(/2.*3.*STARTER|2.*3.*Starter/i).first()).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(strings.warehouseNote)).toBeVisible();

      await page.getByRole("button", { name: /Add root node/i }).click();
      await page.getByPlaceholder(/North Addis Warehouse/i).fill("New Warehouse");
      const holdsStockCheckbox = page.getByText(strings.isStockHolding).locator("xpath=..").locator('input[type="checkbox"]');
      await expect(holdsStockCheckbox).toBeChecked();

      await page.getByRole("button", { name: /Save Node/i }).click();
      await expect.poll(() => nodeCreated).toBe(true);

      await expect(page.getByText(/3.*3.*STARTER|3.*3.*Starter/i).first()).toBeVisible({ timeout: 10_000 });

      console.log(`--- warehouse counter (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`at cap: non-stock node submits freely, stock node shows the cap notice (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(PLAN_USAGE_PATH, (route) =>
        fulfillJson(route, {
          plan_tier: "STARTER",
          skus: { used: 10, limit: 500 },
          users: { used: 1, limit: 5 },
          warehouses: { used: 3, limit: 3 },
        })
      );
      let nonStockWriteSent = false;
      let stockWriteSent = false;
      await mockCommon(page, [rootNode()]);
      await page.route(NODES_PATH, (route) => {
        const req = route.request();
        if (req.method() === "POST") {
          const body = req.postDataJSON() as { is_stock_holding: boolean };
          if (body.is_stock_holding) { stockWriteSent = true; } else { nonStockWriteSent = true; }
          return fulfillJson(route, rootNode({ id: "node-new-2", name: body.is_stock_holding ? "Stock Node" : "Approval Node", is_stock_holding: body.is_stock_holding }), 201);
        }
        if (req.method() !== "GET") return route.fallback();
        return fulfillJson(route, [rootNode()]);
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoOrgTree(page);

      // Persistent cap notice at the top of the tab.
      await expect(page.getByText(strings.capNotice)).toBeVisible({ timeout: 10_000 });

      // Add a non-stock (approval-only) node — never blocked by the cap.
      await page.getByRole("button", { name: /Add root node/i }).click();
      await page.getByPlaceholder(/North Addis Warehouse/i).fill("Approval Node");
      const holdsStockCheckbox = page.getByText(strings.isStockHolding).locator("xpath=..").locator('input[type="checkbox"]');
      await holdsStockCheckbox.uncheck();
      const saveBtn = page.getByRole("button", { name: /Save Node/i });
      await expect(saveBtn).toBeEnabled();
      await saveBtn.click();
      await expect.poll(() => nonStockWriteSent).toBe(true);

      // Add a stock-holding node — blocked with the inline notice.
      await page.getByRole("button", { name: /Add root node/i }).click();
      await page.getByPlaceholder(/North Addis Warehouse/i).fill("Stock Node");
      const holdsStockCheckbox2 = page.getByText(strings.isStockHolding).locator("xpath=..").locator('input[type="checkbox"]');
      await expect(holdsStockCheckbox2).toBeChecked();
      const saveBtn2 = page.getByRole("button", { name: /Save Node/i });
      await expect(saveBtn2).toBeDisabled();
      await expect(page.getByText(strings.capNotice).last()).toBeVisible();
      await expect(page.getByRole("button", { name: strings.comparePlans }).last()).toBeVisible();
      await expect(page.getByRole("button", { name: strings.requestUpgrade }).last()).toBeVisible();
      await saveBtn2.click({ force: true, timeout: 2_000 }).catch(() => {});
      expect(stockWriteSent, "a capped stock-holding node must never POST while disabled").toBe(false);

      // Compare plans opens the modal.
      await page.getByRole("button", { name: strings.comparePlans }).last().click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10_000 });
      await page.keyboard.press("Escape");

      console.log(`--- cap notice (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`402 PLAN_LIMIT_REACHED on reactivate shows the friendly notice, never raw JSON (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(PLAN_USAGE_PATH, (route) =>
        fulfillJson(route, {
          plan_tier: "STARTER",
          skus: { used: 10, limit: 500 },
          users: { used: 1, limit: 5 },
          warehouses: { used: 3, limit: 3 },
        })
      );
      const inactiveNode = rootNode({ id: "node-inactive-1", name: "Old Warehouse", is_stock_holding: true, is_active: false });
      await mockCommon(page, [inactiveNode]);
      await page.route(NODES_PATH, (route) => {
        const req = route.request();
        if (req.method() === "PATCH" && req.url().includes("/reactivate")) {
          return fulfillError(route, 402, {
            code: "PLAN_LIMIT_REACHED",
            resource: "warehouses",
            current: 3,
            limit: 3,
            plan_tier: "STARTER",
            upgrade_to: "GROWTH",
            message: "raw-backend-message-should-not-be-shown",
          });
        }
        if (req.method() !== "GET") return route.fallback();
        return fulfillJson(route, [inactiveNode]);
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoOrgTree(page);

      await page.getByRole("button", { name: strings.reactivateBtn }).click();
      await expect(page.getByText(strings.limitReachedWarehouses)).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText("raw-backend-message-should-not-be-shown")).toHaveCount(0);

      console.log(`--- reactivate 402 (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`unlimited plan shows "Unlimited" (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(PLAN_USAGE_PATH, (route) =>
        fulfillJson(route, {
          plan_tier: "ENTERPRISE",
          skus: { used: 10, limit: null },
          users: { used: 1, limit: null },
          warehouses: { used: 12, limit: null },
        })
      );
      await mockCommon(page, [rootNode()]);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await gotoOrgTree(page);

      await expect(page.getByText(strings.unlimited)).toBeVisible({ timeout: 10_000 });

      // Approval-only level (L2, added under the L1 root): "Holds stock" is
      // disabled + unchecked, with the approval-only hint — the level
      // holds-stock guard, not the plan cap, is what's driving this state.
      await page.getByTitle("Add child node").first().click();
      const childHoldsStockCheckbox = page.getByText(strings.isStockHolding).last().locator("xpath=..").locator('input[type="checkbox"]');
      await expect(childHoldsStockCheckbox).toBeDisabled();
      await expect(childHoldsStockCheckbox).not.toBeChecked();
      await expect(page.getByText(strings.levelApprovalOnlyHint)).toBeVisible();

      console.log(`--- unlimited plan (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
