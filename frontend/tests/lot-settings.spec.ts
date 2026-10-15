/**
 * Playwright E2E — product-level Lot tracking settings (session/2026-10-12-fefo-a3).
 *
 * Covers:
 *   a) FEATURE_LOT_TRACKING off -> Lot tracking section absent from the Edit
 *      Product panel
 *   b) feature on -> section present; expiry disabled until batch is on;
 *      expiry on -> FEFO selected, FIFO/LIFO disabled; batch off -> the
 *      dispatch-strategy picker is hidden entirely
 *   c) edit save with a changed value sends PUT .../lot-settings with the
 *      expected payload (asserted on the captured request body)
 *   d) toggling batch tracking on for a product with on-hand stock shows a
 *      confirm dialog first; confirming and saving shows the opening lot
 *      number from the stubbed response and keeps the panel open
 *   e) a stubbed 409 BATCH_TRACKING_IN_USE renders the translated message,
 *      never the raw error code
 *
 * GET /api/v1/products, GET /api/v1/inventory/analytics/stock, GET
 * /api/v1/inventory/features, GET/PUT /api/v1/products/:id/approval-minimums,
 * PATCH /api/v1/products/:id and PUT .../lot-settings are all stubbed with
 * page.route() — this file never sends a live write. Login goes to the real
 * local dev backend using the permanent zz-e2e-ta TA probe account
 * (CLAUDE.md §29), same as lot-receive.spec.ts.
 *
 * Chromium headless only, serviceWorkers blocked, en + am. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/lot-settings.spec.ts --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type Locator, type ConsoleMessage, type Route } from "@playwright/test";
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
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return;
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
    editButton:         d.product.edit as string,
    editTitle:          d.product.edit_title as string,
    saveButton:         d.product.add.save as string,
    lotSectionTitle:    d.product.lot_settings.title as string,
    batchTrackingLabel: d.product.lot_settings.batch_tracking as string,
    expiryTrackingLabel: d.product.lot_settings.expiry_tracking as string,
    confirmConversion:  d.product.lot_settings.confirm_conversion as string,
    confirmConversionOk: d.product.lot_settings.confirm_conversion_ok as string,
    editSuccess:        d.product.edit_success as string,
    batchTrackingInUse: d.errors.BATCH_TRACKING_IN_USE as string,
  };
}

const PRODUCT = {
  id: "prod-lot-1", sku: "LT-100", name: "Lot Settings Widget", unit: "pcs", pack_size: 1,
  category: "Test", type_code: "LTS", is_discontinued: false, is_controlled: false,
  batch_tracking: false, expiry_tracking: false, dispatch_strategy: null as string | null,
};

async function stubCommon(
  page: Page,
  opts: { lotTracking: boolean; product?: typeof PRODUCT; stock?: number },
) {
  const product = opts.product ?? PRODUCT;
  await page.route("**/api/v1/products", (route) => {
    if (route.request().method() === "GET") return fulfillJson(route, [product]);
    return route.continue();
  });
  await page.route("**/api/v1/inventory/features", (route) =>
    fulfillJson(route, { lot_tracking: opts.lotTracking }),
  );
  await page.route("**/api/v1/inventory/analytics/stock", (route) =>
    fulfillJson(route, opts.stock ? [{ product_id: product.id, current_stock: String(opts.stock) }] : []),
  );
  await page.route(`**/api/v1/products/${product.id}/approval-minimums`, (route) => {
    if (route.request().method() === "GET") return fulfillJson(route, { minimums: [] });
    if (route.request().method() === "PUT") return fulfillJson(route, {});
    return route.continue();
  });
  await page.route(`**/api/v1/products/${product.id}`, (route) => {
    if (route.request().method() === "PATCH") return fulfillJson(route, { id: product.id, sku: product.sku });
    return route.continue();
  });
}

function panel(page: Page, titleText: string): Locator {
  return page.getByRole("dialog", { name: titleText });
}

/** Both the batch and expiry toggles are a bare `<label><input/>{text}</label>` —
 * select the checkbox via its enclosing label rather than text-node traversal. */
function checkboxFor(root: Locator, labelText: string): Locator {
  return root.locator("label", { hasText: labelText }).locator('input[type="checkbox"]');
}

async function openEditPanel(page: Page, s: ReturnType<typeof localeStrings>): Promise<Locator> {
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/products`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: s.editButton, exact: true }).click();
  const p = panel(page, s.editTitle);
  await expect(p).toBeVisible();
  return p;
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Product Lot tracking settings (${locale})`, () => {
    test(`features false: Lot tracking section is absent (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await stubCommon(page, { lotTracking: false });
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      const p = await openEditPanel(page, s);

      await expect(p.getByText(s.lotSectionTitle, { exact: true })).toHaveCount(0);

      console.log(`--- features-false section-absent (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`features true: expiry gated on batch, FEFO forced when expiry on, strategy hidden when batch off (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await stubCommon(page, { lotTracking: true });
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      const p = await openEditPanel(page, s);

      await expect(p.getByText(s.lotSectionTitle, { exact: true })).toBeVisible();

      const batchCb  = checkboxFor(p, s.batchTrackingLabel);
      const expiryCb = checkboxFor(p, s.expiryTrackingLabel);

      await expect(expiryCb).toBeDisabled();
      await expect(p.getByRole("radio", { name: "FIFO" })).toHaveCount(0);

      await batchCb.check();
      await expect(expiryCb).toBeEnabled();
      const fifoRadio = p.getByRole("radio", { name: "FIFO" });
      const fefoRadio = p.getByRole("radio", { name: "FEFO" });
      const lifoRadio = p.getByRole("radio", { name: "LIFO" });
      await expect(fifoRadio).toBeChecked();
      await expect(fefoRadio).toBeDisabled();

      await expiryCb.check();
      await expect(fefoRadio).toBeChecked();
      await expect(fifoRadio).toBeDisabled();
      await expect(lifoRadio).toBeDisabled();

      await batchCb.uncheck();
      await expect(p.getByRole("radio", { name: "FIFO" })).toHaveCount(0);
      await expect(expiryCb).toBeDisabled();

      if (locale === "am") {
        await expect(page.getByText(/product\.lot_settings\./)).toHaveCount(0);
      }

      console.log(`--- gating (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

test.describe("Product Lot tracking settings — mutations (en)", () => {
  test("edit save with a change sends PUT lot-settings with the expected payload", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const s = localeStrings("en");
    const consoleErrors = collectConsoleErrors(page);
    const captured: { body: unknown } = { body: null };

    await stubCommon(page, { lotTracking: true, stock: 0 });
    await page.route(`**/api/v1/inventory/products/${PRODUCT.id}/lot-settings`, (route) => {
      captured.body = route.request().postDataJSON();
      return fulfillJson(route, { batch_tracking: true, expiry_tracking: false, dispatch_strategy: "FIFO", opening_lots: [] });
    });

    await login(page, E2E_TA_EMAIL, taPassword);
    const p = await openEditPanel(page, s);

    const batchCb = checkboxFor(p, s.batchTrackingLabel);
    await batchCb.check();
    await p.getByRole("button", { name: s.saveButton, exact: true }).click();

    await expect.poll(() => captured.body, { timeout: 10_000 }).toBeTruthy();
    expect(captured.body).toEqual({ batch_tracking: true, expiry_tracking: false, dispatch_strategy: "FIFO" });

    // No opening lots on this save (no stock) — the panel closes on success,
    // same as any other product edit (unrelated to lot settings).
    await expect(panel(page, s.editTitle)).toHaveCount(0, { timeout: 10_000 });

    console.log("--- edit save payload console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });

  test("batch off->on with stock: confirm shown; confirming and saving lists the opening lot, panel stays open", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const s = localeStrings("en");
    const consoleErrors = collectConsoleErrors(page);
    const captured: { body: unknown } = { body: null };

    await stubCommon(page, { lotTracking: true, stock: 25 });
    await page.route(`**/api/v1/inventory/products/${PRODUCT.id}/lot-settings`, (route) => {
      captured.body = route.request().postDataJSON();
      return fulfillJson(route, {
        batch_tracking: true, expiry_tracking: false, dispatch_strategy: "FIFO",
        opening_lots: [{ warehouse_id: "wh-1", lot_id: "lot-opening-1", lot_number: "OPENING-WH1", quantity: 25 }],
      });
    });

    await login(page, E2E_TA_EMAIL, taPassword);
    const p = await openEditPanel(page, s);

    const batchCb = checkboxFor(p, s.batchTrackingLabel);
    // Use click(), not check() — the checkbox intentionally does NOT flip
    // until the confirm dialog is accepted, which check() would treat as a
    // failed state change.
    await batchCb.click();

    await expect(page.getByText(s.confirmConversion)).toBeVisible({ timeout: 5_000 });
    await expect(batchCb).not.toBeChecked();
    await page.getByRole("button", { name: s.confirmConversionOk, exact: true }).click();
    await expect(batchCb).toBeChecked();

    await p.getByRole("button", { name: s.saveButton, exact: true }).click();

    await expect.poll(() => captured.body, { timeout: 10_000 }).toBeTruthy();
    await expect(p.getByText("OPENING-WH1")).toBeVisible({ timeout: 10_000 });
    await expect(panel(page, s.editTitle)).toBeVisible();

    console.log("--- conversion confirm+success console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });

  test("stubbed 409 BATCH_TRACKING_IN_USE shows the translated message, never the raw code", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const s = localeStrings("en");
    const consoleErrors = collectConsoleErrors(page);

    const batchOnProduct = { ...PRODUCT, batch_tracking: true };
    await stubCommon(page, { lotTracking: true, product: batchOnProduct, stock: 10 });
    await page.route(`**/api/v1/inventory/products/${batchOnProduct.id}/lot-settings`, (route) =>
      fulfillError(route, "BATCH_TRACKING_IN_USE", 409),
    );

    await login(page, E2E_TA_EMAIL, taPassword);
    const p = await openEditPanel(page, s);

    const batchCb = checkboxFor(p, s.batchTrackingLabel);
    await expect(batchCb).toBeChecked();
    await batchCb.uncheck();
    await p.getByRole("button", { name: s.saveButton, exact: true }).click();

    await expect(p.getByText(s.batchTrackingInUse)).toBeVisible({ timeout: 10_000 });
    await expect(p.getByText("BATCH_TRACKING_IN_USE")).toHaveCount(0);

    console.log("--- 409 translated-error console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});
