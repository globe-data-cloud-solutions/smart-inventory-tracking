/**
 * Playwright E2E — P5: write actions on operations pages (Add Product,
 * Receive Stock, transfer detail actions) are disabled when the tenant's
 * contract is READ_ONLY, or — for Add Product specifically — when the SKU
 * cap is reached (CLAUDE.md §29).
 *
 * zz-e2e-ta (STARTER, contract stage ACTIVE, below its SKU cap) is the
 * permanent TA probe — never mutated here. Every scenario in this file uses
 * page.route interception ONLY inside the test; no write click in this file
 * ever reaches the real backend (service workers are blocked below so
 * page.route reliably catches every request — see the P4 spec for why).
 *
 * No SA credentials anywhere in this file.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p5-write-guard.spec.ts --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

// Block the app's service worker for every test in this file — otherwise a
// mocked route can silently fall through to the real backend (see P4's
// p4-contract-renewal.spec.ts for the incident this guards against).
test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (/Failed to load resource.*40[0-9]/.test(msg.text())) return; // expected gated round-trips
    if (/Failed to fetch RSC payload.*Falling back to browser navigation/.test(msg.text())) return; // next dev HMR noise, unrelated to app correctness
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

// Read the live translated strings straight from the locale files instead of
// duplicating them inline — avoids this spec silently drifting from P4/P5's
// actual copy.
function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(
    path.join(__dirname, "..", "..", "locales", `${locale}.json`),
    "utf-8"
  );
  const d = JSON.parse(raw);
  return {
    receiveBtn: d.inventory.receive.title as string,
    addProductBtn: d.product.add.button as string,
    readOnlyReason: d.contract.read_only_error as string,
    skuLimitReason: d.plan.limit_reached.skus as string,
  };
}

const CONTRACT_STATUS_PATH = "**/api/v1/tenants/me/contract-status";
const PLAN_USAGE_PATH = "**/api/v1/tenants/me/plan-usage";
const TRANSFER_DETAIL_PATH = "**/api/v1/transfers/p5-test-transfer";

const DRAFT_PULL_TRANSFER = {
  id: "p5-test-transfer",
  ref: "TRF-P5-TEST",
  transfer_type: "PULL",
  product_id: "p5-product",
  product_name: "P5 Test Product",
  from_warehouse_id: "wh-a",
  from_warehouse_name: "Warehouse A",
  to_warehouse_id: "wh-b",
  to_warehouse_name: "Warehouse B",
  quantity: 10,
  notes: "",
  status: "DRAFT",
  created_at: new Date().toISOString(),
};

// ── READ_ONLY: Add Product, Receive opener, and a transfer detail's action
// buttons are all disabled with the read-only tooltip, and no write request
// is ever sent ──────────────────────────────────────────────────────────────
for (const locale of ["en", "am"] as const) {
  test.describe(`READ_ONLY contract stage (${locale})`, () => {
    test(`Add Product, Receive, and transfer actions all disabled; no write sent (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      let productWriteSent = false;
      let receiveWriteSent = false;
      let transferWriteSent = false;

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
      await page.route("**/api/v1/products", (route) => {
        if (route.request().method() === "POST") { productWriteSent = true; }
        return route.continue();
      });
      await page.route("**/api/v1/inventory/receive/", (route) => {
        receiveWriteSent = true;
        return route.continue();
      });
      // One handler for both verbs on this URL — a second page.route() on the
      // same pattern would shadow this one (Playwright only runs the
      // most-recently-registered matching handler unless it calls
      // route.fallback()), so GET and PATCH must branch inside a single call.
      await page.route(TRANSFER_DETAIL_PATH, (route) => {
        if (route.request().method() === "PATCH") {
          transferWriteSent = true;
          return route.continue();
        }
        return fulfillJson(route, DRAFT_PULL_TRANSFER);
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      // ── Add Product ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/products`);
      await page.waitForLoadState("networkidle");
      const addProductBtn = page.getByRole("button", { name: strings.addProductBtn });
      await expect(addProductBtn).toBeVisible({ timeout: 10_000 });
      await expect(addProductBtn).toBeDisabled();
      expect(await addProductBtn.getAttribute("title")).toBe(strings.readOnlyReason);
      await addProductBtn.click({ force: true, timeout: 2_000 }).catch(() => {});
      // Disabled means the panel never opens — its SKU field must not appear.
      await expect(page.getByLabel(/SKU/i)).toHaveCount(0);

      // ── Receive opener ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
      await page.waitForLoadState("networkidle");
      const receiveBtn = page.getByRole("button", { name: `+ ${strings.receiveBtn}` });
      await expect(receiveBtn).toBeVisible({ timeout: 10_000 });
      await expect(receiveBtn).toBeDisabled();
      expect(await receiveBtn.getAttribute("title")).toBe(strings.readOnlyReason);
      await receiveBtn.click({ force: true, timeout: 2_000 }).catch(() => {});

      // ── Transfer detail action buttons ──
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers/p5-test-transfer`);
      await page.waitForLoadState("networkidle");
      const transferButtons = page.locator("button", { hasText: /./ }).filter({ hasText: /Submit for Review|Cancel/i });
      const count = await transferButtons.count();
      expect(count, "expected at least one transfer action button (Submit for Review / Cancel)").toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        const btn = transferButtons.nth(i);
        await expect(btn).toBeDisabled();
        expect(await btn.getAttribute("title")).toBe(strings.readOnlyReason);
        await btn.click({ force: true, timeout: 2_000 }).catch(() => {});
      }

      expect(productWriteSent, "Add Product must never POST while disabled").toBe(false);
      expect(receiveWriteSent, "Receive must never POST while disabled").toBe(false);
      expect(transferWriteSent, "transfer transition must never PATCH while disabled").toBe(false);

      console.log(`--- READ_ONLY (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── ACTIVE + SKU cap reached: Add Product disabled with the SKU-limit
// tooltip; Receive stays enabled (resource "skus" never gates Receive) ──────
for (const locale of ["en", "am"] as const) {
  test.describe(`ACTIVE stage, SKU cap reached (${locale})`, () => {
    test(`Add Product disabled with SKU-limit tooltip; Receive enabled (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(PLAN_USAGE_PATH, (route) =>
        fulfillJson(route, {
          plan_tier: "STARTER",
          skus: { used: 500, limit: 500 },
          users: { used: 1, limit: 5 },
          warehouses: { used: 1, limit: 3 },
        })
      );

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/products`);
      await page.waitForLoadState("networkidle");
      const addProductBtn = page.getByRole("button", { name: strings.addProductBtn });
      await expect(addProductBtn).toBeVisible({ timeout: 10_000 });
      await expect(addProductBtn).toBeDisabled();
      expect(await addProductBtn.getAttribute("title")).toBe(strings.skuLimitReason);

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
      await page.waitForLoadState("networkidle");
      const receiveBtn = page.getByRole("button", { name: `+ ${strings.receiveBtn}` });
      await expect(receiveBtn).toBeVisible({ timeout: 10_000 });
      await expect(receiveBtn).toBeEnabled();

      console.log(`--- ACTIVE + sku cap (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── ACTIVE + below limit (real zz-e2e-ta data, no interception): everything
// enabled. No submit clicks — read-only assertions only. ───────────────────
test.describe("ACTIVE stage, below limit (real data)", () => {
  test("Add Product and Receive are both enabled", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await login(page, E2E_TA_EMAIL, taPassword);

    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/products`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "+ Add Product" })).toBeEnabled({ timeout: 10_000 });

    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "+ Receive Stock" })).toBeEnabled({ timeout: 10_000 });

    console.log("--- ACTIVE below limit console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});
