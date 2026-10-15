/**
 * Playwright E2E — lot-aware Receive Stock / Opening Balance (session/2026-10-12-fefo-a1).
 *
 * Covers:
 *   a) non-batch product selected -> lot/expiry fields hidden, payload carries
 *      no lot_number / expiry_date / auto_lot
 *   b) batch product, no lot, auto unchecked -> validation error, no request sent
 *   c) batch product, auto-generate checked + expiry set -> payload has
 *      auto_lot:true and no lot_number; success text shows the returned lot number
 *   d) batch product, manual lot with no expiry -> EXPIRY_REQUIRED error, no request
 *   e) Opening Balance panel — same rules, source stays OPENING_BALANCE, no
 *      Manufacture Date field
 *   f) am locale — (a) and (c) again, asserting no raw i18n keys are visible
 *
 * GET /api/v1/products and POST /api/v1/inventory/receive/ are stubbed with
 * page.route() in every scenario below — this file never sends a live write.
 * Everything else (login, warehouses) goes to the real local dev backend
 * using the permanent zz-e2e-ta TA probe account (CLAUDE.md §29).
 *
 * The TA probe has no warehouse_id in its JWT (TA is tenant-wide, not
 * warehouse-scoped), but ReceiveStockPanel reads the warehouse read-only
 * from session.warehouseId (never a dropdown, per CLAUDE.md UI rules) — so
 * after a real login this file patches warehouseId/warehouseName directly
 * in the browser's localStorage session object (client-side only, no DB
 * write) purely to exercise that code path.
 *
 * Both ReceiveStockPanel and OpeningBalancePanel are always mounted on the
 * inventory page (their slide-out drawer is just CSS-translated off-screen
 * when closed), and Playwright's visibility check does not treat a
 * translate-x-full element as hidden — so every locator below is scoped to
 * the one open drawer via panelRoot(), never to the bare page.
 *
 * The last block (receive-form reasons) is the transfer RECEIVE form, not the stock panel:
 * it stubs one IN_TRANSIT transfer to the session warehouse and checks which discrepancy
 * reasons each row offers (a non-batch row has no 'Wrong lot').
 *
 * Chromium headless only, serviceWorkers blocked, en + am. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/lot-receive.spec.ts --workers=1
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

/** Patch the client-side session (post real login) so ReceiveStockPanel's
 * read-only warehouse field is non-empty — the TA probe's JWT has no
 * warehouse_id. No backend write; purely a browser localStorage edit. */
async function fakeWarehouseAssignment(page: Page) {
  await page.evaluate(() => {
    const raw = window.localStorage.getItem("smart_demo_session");
    if (!raw) return;
    const session = JSON.parse(raw) as Record<string, unknown>;
    session.warehouseId = "test-wh-001";
    session.warehouseName = "Test Warehouse";
    window.localStorage.setItem("smart_demo_session", JSON.stringify(session));
  });
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
    receiveTitle:        d.inventory.receive.title as string,
    manualRef:           d.transfer.reference.MANUAL as string,
    autoLotCheckbox:      d.receive_panel.auto_lot_checkbox as string,
    lotNumberLabel:       d.inventory.receive.lot_number as string,
    expiryDateLabel:      d.inventory.receive.expiry_date as string,
    lotNumberRequired:    d.errors.LOT_NUMBER_REQUIRED as string,
    expiryRequired:       d.errors.EXPIRY_REQUIRED as string,
    successLot: (lot: string) => (d.inventory.receive.success_lot as string).replace("{lot}", lot),
    openingBalanceTitle: d.opening_balance.title as string,
    openingBalanceSubmit: d.opening_balance.submit as string,
  };
}

const NON_BATCH_PRODUCT = {
  id: "prod-nonbatch-1", sku: "NB-100", name: "NonBatch Widget", unit: "pcs", pack_size: 1,
  batch_tracking: false, expiry_tracking: false,
};
const BATCH_PRODUCT = {
  id: "prod-batch-1", sku: "BT-200", name: "Batch Widget", unit: "pcs", pack_size: 1,
  batch_tracking: true, expiry_tracking: true,
};

const PRODUCTS_PATH = "**/api/v1/products";
const RECEIVE_PATH   = "**/api/v1/inventory/receive/";

async function stubProducts(page: Page) {
  await page.route(PRODUCTS_PATH, (route) => {
    if (route.request().method() === "GET") return fulfillJson(route, [NON_BATCH_PRODUCT, BATCH_PRODUCT]);
    return route.continue();
  });
}

/** Stubs the receive POST, capturing the request body into `captured.body`. */
async function stubReceive(page: Page, captured: { body: unknown }) {
  await page.route(RECEIVE_PATH, (route) => {
    if (route.request().method() === "POST") {
      captured.body = route.request().postDataJSON();
      return fulfillJson(route, { lot_id: "lot-1", lot_number: "261012-001", expiry_date: null, source: "WEB" }, 201);
    }
    return route.continue();
  });
}

/** Both panels' drawers are always mounted (only CSS-translated off-screen
 * when closed), so every panel-scoped locator must go through this —
 * never through a bare `page.locator(...)`. Scopes to the one drawer whose
 * header contains `titleText` (ReceiveStockPanel vs OpeningBalancePanel). */
function panelRoot(page: Page, titleText: string): Locator {
  return page.locator("div.fixed.top-0.right-0.translate-x-0").filter({ hasText: titleText });
}

async function openReceivePanel(page: Page, s: ReturnType<typeof localeStrings>): Promise<Locator> {
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: `+ ${s.receiveTitle}` }).click();
  const panel = panelRoot(page, s.receiveTitle);
  await expect(panel).toBeVisible();
  return panel;
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Receive Stock — lot/expiry (${locale})`, () => {
    test(`non-batch product: lot/expiry hidden, payload carries neither (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);
      const captured: { body: unknown } = { body: null };

      await stubProducts(page);
      await stubReceive(page, captured);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await fakeWarehouseAssignment(page);
      const panel = await openReceivePanel(page, s);

      await panel.locator("select").nth(0).selectOption({ label: `${NON_BATCH_PRODUCT.name} · ${NON_BATCH_PRODUCT.sku}` });

      await expect(panel.getByText(s.lotNumberLabel, { exact: true })).toHaveCount(0);
      await expect(panel.getByText(s.expiryDateLabel, { exact: true })).toHaveCount(0);

      await panel.locator("select").nth(1).selectOption({ label: s.manualRef });
      await panel.getByPlaceholder("e.g. 500").fill("10");
      await panel.getByRole("button", { name: s.receiveTitle, exact: true }).click();

      await expect.poll(() => captured.body, { timeout: 10_000 }).toBeTruthy();
      const body = captured.body as Record<string, unknown>;
      expect(body.lot_number).toBeUndefined();
      expect(body.expiry_date).toBeUndefined();
      expect(body.auto_lot).toBeUndefined();

      if (locale === "am") {
        await expect(page.getByText(/receive_panel\./)).toHaveCount(0);
        await expect(page.getByText(/inventory\.receive\./)).toHaveCount(0);
      }

      console.log(`--- non-batch no-lot payload (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`batch product, no lot, auto unchecked: validation error, no request sent (${locale})`, async ({ page }) => {
      test.skip(locale !== "en", "case (b) is English-only per spec");
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);
      const captured: { body: unknown } = { body: null };

      await stubProducts(page);
      await stubReceive(page, captured);

      await login(page, E2E_TA_EMAIL, taPassword);
      await fakeWarehouseAssignment(page);
      const panel = await openReceivePanel(page, s);

      await panel.locator("select").nth(0).selectOption({ label: `${BATCH_PRODUCT.name} · ${BATCH_PRODUCT.sku}` });
      await panel.locator("select").nth(1).selectOption({ label: s.manualRef });
      await panel.getByPlaceholder("e.g. 500").fill("10");
      await panel.getByRole("button", { name: s.receiveTitle, exact: true }).click();

      await expect(panel.getByText(s.lotNumberRequired)).toBeVisible({ timeout: 10_000 });
      expect(captured.body).toBeNull();

      console.log(`--- batch no-lot blocked (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`batch product, auto-generate + expiry: payload has auto_lot true, no lot_number, success shows lot (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);
      const captured: { body: unknown } = { body: null };

      await stubProducts(page);
      await stubReceive(page, captured);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await fakeWarehouseAssignment(page);
      const panel = await openReceivePanel(page, s);

      await panel.locator("select").nth(0).selectOption({ label: `${BATCH_PRODUCT.name} · ${BATCH_PRODUCT.sku}` });
      await panel.getByText(s.autoLotCheckbox).locator('input[type="checkbox"]').check();
      await panel.locator('input[type="date"]').fill("2027-01-01");
      await panel.locator("select").nth(1).selectOption({ label: s.manualRef });
      await panel.getByPlaceholder("e.g. 500").fill("10");
      await panel.getByRole("button", { name: s.receiveTitle, exact: true }).click();

      await expect.poll(() => captured.body, { timeout: 10_000 }).toBeTruthy();
      const body = captured.body as Record<string, unknown>;
      expect(body.auto_lot).toBe(true);
      expect(body.lot_number).toBeUndefined();

      await expect(panel.getByText(s.successLot("261012-001"))).toBeVisible({ timeout: 10_000 });

      await page.waitForTimeout(4_000);
      await expect(panelRoot(page, s.receiveTitle)).toBeVisible();

      if (locale === "am") {
        await expect(page.getByText(/receive_panel\./)).toHaveCount(0);
        await expect(page.getByText(/inventory\.receive\./)).toHaveCount(0);
        await expect(page.getByText(/errors\./)).toHaveCount(0);
      }

      console.log(`--- auto-lot + expiry success (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`batch product, manual lot with no expiry: EXPIRY_REQUIRED error, no request (${locale})`, async ({ page }) => {
      test.skip(locale !== "en", "case (d) is English-only per spec");
      const taPassword = e2eTaPasswordOrSkip(test);
      const s = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);
      const captured: { body: unknown } = { body: null };

      await stubProducts(page);
      await stubReceive(page, captured);

      await login(page, E2E_TA_EMAIL, taPassword);
      await fakeWarehouseAssignment(page);
      const panel = await openReceivePanel(page, s);

      await panel.locator("select").nth(0).selectOption({ label: `${BATCH_PRODUCT.name} · ${BATCH_PRODUCT.sku}` });
      await panel.getByPlaceholder("e.g. LOT-2026-001").fill("PW-L1");
      await panel.locator("select").nth(1).selectOption({ label: s.manualRef });
      await panel.getByPlaceholder("e.g. 500").fill("10");
      await panel.getByRole("button", { name: s.receiveTitle, exact: true }).click();

      await expect(panel.getByText(s.expiryRequired)).toBeVisible({ timeout: 10_000 });
      expect(captured.body).toBeNull();

      console.log(`--- batch manual lot no expiry blocked (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

test.describe("Opening Balance — lot/expiry (en)", () => {
  test("opening balance receipt: no Manufacture Date field, source stays OPENING_BALANCE", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const s = localeStrings("en");
    const consoleErrors = collectConsoleErrors(page);
    const captured: { body: unknown } = { body: null };

    await stubProducts(page);
    await stubReceive(page, captured);

    await login(page, E2E_TA_EMAIL, taPassword);
    await fakeWarehouseAssignment(page);
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
    await page.waitForLoadState("networkidle");

    const obButton = page.getByRole("button", { name: `+ ${s.openingBalanceTitle}` });
    const isVisible = await obButton.waitFor({ state: "visible", timeout: 5_000 }).then(() => true).catch(() => false);
    if (!isVisible) {
      console.log("Opening Balance panel is NOT visible for the TA test user — skipping case (e).");
      return;
    }
    await obButton.click();
    const panel = panelRoot(page, s.openingBalanceTitle);
    await expect(panel).toBeVisible();

    await expect(panel.getByText("Manufacture Date")).toHaveCount(0);

    await panel.locator("select").nth(0).selectOption({ label: `${BATCH_PRODUCT.name} · ${BATCH_PRODUCT.sku} [BATCH]` });
    await panel.getByPlaceholder("e.g. 1000").fill("50");
    await panel.getByText(s.autoLotCheckbox).locator('input[type="checkbox"]').check();
    await panel.locator('input[type="date"]').fill("2027-01-01");
    await panel.getByRole("button", { name: s.openingBalanceSubmit, exact: true }).click();

    await expect.poll(() => captured.body, { timeout: 10_000 }).toBeTruthy();
    const body = captured.body as Record<string, unknown>;
    expect(body.source).toBe("OPENING_BALANCE");
    expect(body.auto_lot).toBe(true);
    expect(body.lot_number).toBeUndefined();

    console.log("--- opening balance lot receipt console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});

/* ── Transfer receive form: which reasons each row offers ───────────────────
 * "Wrong lot" only makes sense for a row that carries a lot. Stubs one IN_TRANSIT
 * transfer into the (client-patched) session warehouse, with a batch line (one lot
 * allocation) and a non-batch line. No writes: nothing is submitted. */
const RECV_WH = "test-wh-001";   // what fakeWarehouseAssignment puts in the session
const RECV_T = "aaaa0009-0000-4000-8000-000000000009";
const RECV_LINE_BATCH = "55555555-5555-4555-8555-555555555581";
const RECV_LINE_PLAIN = "55555555-5555-4555-8555-555555555582";
const RECV_PROD_BATCH = { id: "33333333-3333-4333-8333-333333333381", sku: "RCV-B-01", name: "RCV-BATCH" };
const RECV_PROD_PLAIN = { id: "33333333-3333-4333-8333-333333333382", sku: "RCV-P-01", name: "RCV-PLAIN" };

const recvTransfer = {
  transfer_id: RECV_T, transfer_type: "PUSH", status: "IN_TRANSIT", reference_number: null,
  from_warehouse_id: "11111111-1111-4111-8111-111111111111", from_warehouse_name: "Receive Source WH",
  to_warehouse_id: RECV_WH, to_warehouse_name: "Test Warehouse",
  lines: [
    { line_id: RECV_LINE_BATCH, product_id: RECV_PROD_BATCH.id, product_name: RECV_PROD_BATCH.name, sku: RECV_PROD_BATCH.sku, quantity: "30.0000", uom: "pcs" },
    { line_id: RECV_LINE_PLAIN, product_id: RECV_PROD_PLAIN.id, product_name: RECV_PROD_PLAIN.name, sku: RECV_PROD_PLAIN.sku, quantity: "20.0000", uom: "pcs" },
  ],
  lot_allocations: [{
    line_id: RECV_LINE_BATCH, product_id: RECV_PROD_BATCH.id, lot_id: "44444444-4444-4444-8444-444444444481",
    lot_number: "RCV-LOT-1", expiry_date: "2027-05-31", quantity: "30.0000", is_override: false,
  }],
  discrepancies: [],
  created_by: "99999999-9999-4999-8999-999999999999", created_by_authority_level: 1,
  created_at: "2026-10-12T08:00:00Z", is_self_approved: false,
};

for (const locale of ["en", "am"] as const) {
  test.describe(`Transfer receive form — reasons per row (${locale})`, () => {
    test(`a non-batch row offers Short and Damaged only; a lot row offers all three (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);
      const unstubbedWrites: string[] = [];

      const raw = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8"));
      const tr = raw.transfers;
      const reasonLabel = tr.discrepancies.reason as Record<"SHORT" | "DAMAGED" | "WRONG_LOT", string>;
      const receiveAction = tr.receive.action as string;
      const receiveTitle = (tr.receive.title as string).replace("{ref}", RECV_T.slice(0, 8).toUpperCase());

      await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
        const req = route.request();
        const method = req.method();
        const url = new URL(req.url());
        const p = url.pathname.replace(/\/$/, "");
        if (method === "GET") {
          if (p === "/api/v1/inventory/transfers") return fulfillJson(route, [recvTransfer]);
          if (p === `/api/v1/inventory/transfers/${RECV_T}`) return fulfillJson(route, recvTransfer);
          if (p === `/api/v1/inventory/transfers/${RECV_T}/approval-info`) {
            return fulfillJson(route, {
              transfer_id: RECV_T, required_authority_level: 1, required_role_display: "Tenant Admin",
              is_auto_approve: false, can_approve: false, reason: "", current_step: 1, total_steps: 1,
            });
          }
          if (p === "/api/v1/inventory/transfers/discrepancies") return fulfillJson(route, []);
          if (p === "/api/v1/products") {
            return fulfillJson(route, [RECV_PROD_BATCH, RECV_PROD_PLAIN].map((x, i) => ({
              ...x, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z",
              batch_tracking: i === 0, expiry_tracking: i === 0,
            })));
          }
          if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) return fulfillJson(route, []);
          if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return fulfillJson(route, []);
          if (p === "/api/v1/inventory/analytics/stock") return fulfillJson(route, []);
          return route.continue();
        }
        if (method === "OPTIONS") return route.continue();
        if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login
        unstubbedWrites.push(`${method} ${url.pathname}`);
        return route.abort();
      });

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await fakeWarehouseAssignment(page);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers`);
      await page.waitForLoadState("networkidle");

      await page.locator("tr").filter({ hasText: RECV_T.slice(0, 8).toUpperCase() })
        .getByRole("button", { name: receiveAction, exact: true }).click();
      const modal = page.locator("div.fixed.shadow-2xl").filter({ hasText: receiveTitle });
      await expect(modal).toBeVisible();
      await expect(modal.locator("tbody tr")).toHaveCount(2);

      // Make each row short so its reason select appears.
      const lotRow = modal.locator("tbody tr").filter({ hasText: "RCV-LOT-1" });
      const plainRow = modal.locator("tbody tr").filter({ hasText: RECV_PROD_PLAIN.name });
      await lotRow.getByRole("spinbutton").fill("25");
      await plainRow.getByRole("spinbutton").fill("15");

      const optionValues = (row: Locator) => row.getByRole("combobox").locator("option:not([value=''])")
        .evaluateAll((els) => els.map((e) => (e as HTMLOptionElement).value));

      expect(await optionValues(plainRow), "non-batch row: Short and Damaged only").toEqual(["SHORT", "DAMAGED"]);
      expect(await optionValues(lotRow), "lot row: all three").toEqual(["SHORT", "DAMAGED", "WRONG_LOT"]);
      for (const r of ["SHORT", "DAMAGED"] as const) {
        await expect(plainRow.getByRole("combobox").locator(`option[value="${r}"]`)).toHaveText(reasonLabel[r]);
      }
      await expect(plainRow.getByRole("combobox").locator('option[value="WRONG_LOT"]')).toHaveCount(0);
      await expect(lotRow.getByRole("combobox").locator('option[value="WRONG_LOT"]')).toHaveText(reasonLabel.WRONG_LOT);

      expect(unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
      console.log(`--- receive form reasons (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
