/**
 * Playwright E2E — consistent form-submit UX (session 18, B1).
 *
 * Contract under test (shared notify() toast + in-flight Save lock):
 *   a) Add Product with no approval override: Save is disabled while the POST
 *      is in flight (a second click sends no second POST), the panel closes
 *      immediately on success, [data-testid=global-toast] shows the SKU, and
 *      NO approval-minimums PUT is sent.
 *   b) Add Product with one override row configured and the approval-minimums
 *      PUT forced to 403: the product POST already succeeded, so the panel
 *      closes and the toast is the *warning* kind naming the SKU — never the
 *      generic failure.
 *   c) One stock panel (Receive Stock, else Opening Balance — whichever the
 *      zz-e2e-ta TA can open): Save disabled in flight, panel closed on
 *      success, global toast visible.
 *
 * Every product / inventory API call the flows touch is stubbed with
 * page.route(), so this spec never writes real data: the "products" it
 * creates (SKU prefix ZZUX-) exist only in stubbed responses and need no
 * cleanup. Login goes to the real local dev backend using the permanent
 * zz-e2e-ta TA probe account (CLAUDE.md §29), same as lot-settings.spec.ts.
 *
 * Chromium headless only, serviceWorkers blocked, en + am. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/form-submit-ux.spec.ts --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const STUB_SKU = "ZZUX-001";
const IN_FLIGHT_MS = 1500;

test.setTimeout(90_000);
test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return;
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

function fulfillError(route: Route, code: string, status: number) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ success: false, error: { code, message: code } }),
  });
}

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  return {
    addButton:        d.product.add.button as string,
    addTitle:         d.product.add.title as string,
    namePlaceholder:  d.product.add.field.name_placeholder as string,
    saveButton:       d.product.add.save as string,
    saving:           d.common.saving as string,
    enableOverride:   d.product.enable_override as string,
    partialFailure:   d.product.add.partial_failure as string,
    genericError:     d.product.add.error.generic as string,
    receiveButton:    d.inventory.receive.title as string,
    receiveSubmit:    d.inventory.receive.submit as string,
    openingTitle:     d.opening_balance.title as string,
    openingSubmit:    d.opening_balance.submit as string,
  };
}

const POSITION = {
  id: "pos-zz-1", title: "Approver", role_code: "NM", level_number: 1, level_name: "HQ",
  node_id: "node-zz-1", node_name: "Head Office", display_label: "Approver (Head Office)",
  reports_to_position_id: null, reports_to_title: null,
};

interface ProductApiLog { posts: number; minimumPuts: number }

/** Stubs every /api/v1/products* call plus the positions list. */
async function stubProductApi(page: Page, opts: { minimumsStatus?: number } = {}): Promise<ProductApiLog> {
  const log: ProductApiLog = { posts: 0, minimumPuts: 0 };
  await page.route((url) => url.pathname.startsWith("/api/v1/products"), async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname.replace(/\/$/, "");
    const m = req.method();
    if (m === "GET" && p.endsWith("/next-sku")) return fulfillJson(route, { sku: STUB_SKU, counter: 1 });
    if (m === "GET" && /\/(categories|brands|type-codes|uoms|packaging-types)$/.test(p)) return fulfillJson(route, []);
    if (m === "GET" && p.endsWith("/approval-minimums")) return fulfillJson(route, { minimums: [] });
    if (m === "PUT" && p.endsWith("/approval-minimums")) {
      log.minimumPuts += 1;
      if (opts.minimumsStatus && opts.minimumsStatus >= 400) return fulfillError(route, "PERMISSION_DENIED", opts.minimumsStatus);
      return fulfillJson(route, {});
    }
    if (m === "POST" && p === "/api/v1/products") {
      log.posts += 1;
      await new Promise((r) => setTimeout(r, IN_FLIGHT_MS));
      return fulfillJson(route, { id: "prod-zz-ux-1", sku: STUB_SKU }, 201);
    }
    if (m === "GET" && p === "/api/v1/products") return fulfillJson(route, []);
    return route.fallback();
  });
  await page.route("**/api/v1/tenants/*/positions/flat", (route) => fulfillJson(route, [POSITION]));
  await page.route("**/api/v1/inventory/features", (route) => fulfillJson(route, { lot_tracking: false }));
  return log;
}

async function openAddProduct(page: Page, s: ReturnType<typeof localeStrings>) {
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/products`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: s.addButton, exact: false }).first().click();
  const panel = page.getByRole("dialog", { name: s.addTitle });
  await expect(panel).toBeVisible();
  await panel.getByPlaceholder(s.namePlaceholder).fill("ZZ UX Probe Widget");
  await panel.getByPlaceholder("e.g. Beverages, Cement, Packaging").fill("ZZ Test");
  await panel.getByPlaceholder("e.g. BRD, CEM, PKG").fill("ZZUX");
  await expect(panel.getByText(STUB_SKU).first()).toBeVisible();
  return panel;
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Form submit UX (${locale})`, () => {
    test(`a) Add Product: Save locks in flight, panel closes, toast names SKU, no approval-minimums PUT (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);
      const log = await stubProductApi(page);
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      const panel = await openAddProduct(page, s);
      const save = panel.getByRole("button", { name: s.saveButton, exact: true });
      await expect(save).toBeEnabled();
      await save.click();

      // In flight: Save disabled and relabelled; a forced second click sends nothing.
      const saving = panel.getByRole("button", { name: s.saving, exact: true });
      await expect(saving).toBeDisabled();
      await saving.click({ force: true }).catch(() => undefined);
      await panel.press("Enter").catch(() => undefined);

      const toast = page.locator("[data-testid=global-toast]");
      await expect(toast).toBeVisible({ timeout: 10_000 });
      await expect(toast).toContainText(STUB_SKU);
      await expect(panel).not.toBeInViewport();

      expect(log.posts, "exactly one product POST").toBe(1);
      expect(log.minimumPuts, "no approval-minimums PUT without an override").toBe(0);

      console.log(`--- a) Add Product (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`b) Add Product: approval-minimums 403 after create -> panel closes, warning toast names SKU (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);
      const log = await stubProductApi(page, { minimumsStatus: 403 });
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      const panel = await openAddProduct(page, s);
      // Configure one active override row: enable it and pick an approver.
      await panel.locator("label", { hasText: s.enableOverride }).first().locator('input[type="checkbox"]').check();
      await panel.locator("select").filter({ has: page.locator(`option[value="${POSITION.id}"]`) }).first()
        .selectOption(POSITION.id);

      await panel.getByRole("button", { name: s.saveButton, exact: true }).click();

      const toast = page.locator("[data-testid=global-toast]");
      await expect(toast).toBeVisible({ timeout: 10_000 });
      await expect(toast).toHaveAttribute("data-kind", "warning");
      await expect(toast).toContainText(STUB_SKU);
      // The warning is the partial-failure message ("Product <SKU> created, but ..."),
      // not the generic failure. (The detail may reuse the generic wording, so assert
      // on the translated lead-in instead of on absence.)
      await expect(toast).toContainText(s.partialFailure.split("{{step}}")[0].replace("{{sku}}", STUB_SKU).trim());
      await expect(panel).not.toBeInViewport();

      expect(log.posts, "exactly one product POST").toBe(1);
      expect(log.minimumPuts, "the approval-minimums PUT was attempted once").toBe(1);

      console.log(`--- b) partial failure (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`c) Stock panel: Save locks in flight, panel closes, global toast shown (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      let receivePosts = 0;
      await page.route("**/api/v1/inventory/receive/", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        receivePosts += 1;
        await new Promise((r) => setTimeout(r, IN_FLIGHT_MS));
        return fulfillJson(route, { lot_number: null }, 201);
      });
      await page.route((url) => url.pathname.replace(/\/$/, "") === "/api/v1/products", (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return fulfillJson(route, [{
          id: "prod-zz-ux-2", sku: STUB_SKU, name: "ZZ UX Probe Widget", unit: "pcs", pack_size: 1,
          category: "ZZ Test", type_code: "ZZUX", is_discontinued: false, is_controlled: false,
          batch_tracking: false, expiry_tracking: false, dispatch_strategy: null,
        }]);
      });
      // The zz-e2e-ta tenant has no stock-holding node; Opening Balance needs one to pick.
      await page.route("**/api/v1/tenants/*/nodes", (route) =>
        fulfillJson(route, [{
          id: "node-zz-ux-1", name: "ZZ UX Probe WH", address: null, hierarchy_level: 1,
          level_name: "HQ", is_stock_holding: true, parent_node_id: null, children: [],
        }]),
      );
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
      await page.waitForLoadState("networkidle");

      const receiveOpener = page.getByRole("button", { name: s.receiveButton, exact: false }).first();
      const openingOpener = page.getByRole("button", { name: s.openingTitle, exact: false }).first();
      const useReceive = await receiveOpener.isVisible().catch(() => false);
      const opener = useReceive ? receiveOpener : openingOpener;
      await expect(opener, "TA can open Receive Stock or Opening Balance").toBeVisible();
      await opener.click();

      // Both panels: product select (first real option), optional reference type, quantity.
      const submitName = useReceive ? s.receiveSubmit : s.openingSubmit;
      const submit = page.getByRole("button", { name: submitName, exact: true });
      const sidePanel = page.locator("div.fixed.right-0").filter({ has: submit });
      const form = sidePanel.locator("form");
      if (useReceive) {
        await form.locator("select").nth(0).selectOption({ index: 1 });   // product
        await form.locator("select").nth(1).selectOption("MANUAL");       // reference type
      } else {
        await form.locator("select").nth(0).selectOption({ index: 1 });   // warehouse (TA has no session warehouse)
        await form.locator("select").nth(1).selectOption({ index: 1 });   // product
      }
      await form.locator('input[type="number"]').first().fill("5");

      await expect(submit).toBeEnabled();
      await submit.click();

      const saving = page.getByRole("button", { name: s.saving, exact: true });
      await expect(saving).toBeDisabled();
      await saving.click({ force: true }).catch(() => undefined);

      const toast = page.locator("[data-testid=global-toast]");
      await expect(toast).toBeVisible({ timeout: 10_000 });
      await expect(toast).toContainText(STUB_SKU);
      await expect(form).not.toBeInViewport();
      expect(receivePosts, "exactly one receive POST").toBe(1);

      console.log(`--- c) stock panel via ${useReceive ? "Receive Stock" : "Opening Balance"} (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
