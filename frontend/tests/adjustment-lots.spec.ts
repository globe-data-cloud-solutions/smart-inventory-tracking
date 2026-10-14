/**
 * Playwright E2E — lot-aware stock adjustment screens (session/2026-10-13-fefo-c3).
 *
 * Covers, for en + am:
 *   New Adjustment panel   N1 batch + DAMAGE (forced negative): lot select, expired lot with
 *                             the Expired badge; submit without a lot -> inline error, no POST
 *                          N2 negative with a lot -> POST has lot_id and no lot_number /
 *                             expiry_date / auto_lot; quantity above the lot's available ->
 *                             adj-lot-error, no POST
 *                          N3 positive existing lot (COUNT_DISCREPANCY +qty): each lot listed
 *                             once although present in two warehouses; POST has lot_id only
 *                          N4 positive new lot: typed number + expiry -> lot_number +
 *                             expiry_date, no lot_id; Generate -> auto_lot true, no lot_number
 *                          N5 expiry-tracked product, new lot without expiry -> blocked with a
 *                             message, no POST (a non-expiry product is allowed through)
 *                          N6 switching DAMAGE -> COUNT_DISCREPANCY +qty clears the chosen lot
 *                             (no stale lot_id in the body)
 *                          N7 non-batch product -> no lot UI, POST has none of the lot fields
 *                          N8 backend 422 LOT_EXPIRY_MISMATCH / INSUFFICIENT_LOT_STOCK ->
 *                             translated text shown, no raw code visible
 *   Adjustments list       L1 adj-row-lot for four rows: lot number (+ expiry) / "New lot:
 *                             <number>" / generated-at-posting text / "—"
 *   Approval view          L2 adj-approval-lot shows the lot
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real,
 * using the permanent zz-e2e-ta TA probe account. Every adjustment / lots /
 * products / warehouses / stock request is answered from the fixed fixtures
 * below by one page.route() handler (installStubs), and that same handler is
 * the catch-all guard: any other non-GET request to an /api/ path is aborted,
 * recorded, and fails the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/adjustment-lots.spec.ts --project=chromium --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type Locator, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });
// One worker for this file: parallel real logins make the local gateway answer 503.
test.describe.configure({ mode: "default" });

type Locale = "en" | "am";

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
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

function localeStrings(locale: Locale) {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  const a = d.adjustment;
  return {
    newButton:       a.new_btn as string,
    panelTitle:      a.title as string,
    submit:          a.submit as string,
    lotExisting:     a.lot_mode_existing as string,
    lotNew:          a.lot_mode_new as string,
    lotExceeds: (available: string) => (a.lot_error_exceeds as string).replace("{available}", available),
    lotNewNamed: (n: string) => (a.lot_new_named as string).replace("{number}", n),
    lotNewAuto:      a.lot_new_auto as string,
    lotHeader:       d.table.lot as string,
    expired:         d.lots.expired as string,
    autoLotLabel:    d.receive_panel.auto_lot_checkbox as string,
    errLotRequired:  d.errors.LOT_REQUIRED as string,
    errLotNumber:    d.errors.LOT_NUMBER_REQUIRED as string,
    errExpiry:       d.errors.EXPIRY_REQUIRED as string,
    errMismatch:     d.errors.LOT_EXPIRY_MISMATCH as string,
    errInsufficient: d.errors.INSUFFICIENT_LOT_STOCK as string,
    approve:         a.approve as string,
  };
}
type Strings = ReturnType<typeof localeStrings>;

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const WH_A = "11111111-1111-4111-8111-111111111111";
const WH_B = "22222222-2222-4222-8222-222222222222";
const OTHER_USER = "99999999-9999-4999-8999-999999999999";

const PROD_EXP   = { id: "33333333-3333-4333-8333-333333333301", sku: "ADJ-E-01", name: "ADJ-BATCH-EXPIRY" };
const PROD_NOEXP = { id: "33333333-3333-4333-8333-333333333302", sku: "ADJ-N-01", name: "ADJ-BATCH-NOEXPIRY" };
const PROD_PLAIN = { id: "33333333-3333-4333-8333-333333333303", sku: "ADJ-P-01", name: "ADJ-PLAIN" };

interface LotRow { lot_id: string; lot_number: string; quantity: string; expiry_date: string | null; status: string }
const lot = (n: string, id: string, quantity: string, expiry: string | null, status = "ACTIVE"): LotRow =>
  ({ lot_id: `44444444-4444-4444-8444-4444444444${id}`, lot_number: n, quantity, expiry_date: expiry, status });

const LOT_A = lot("LOT-A", "0a", "30.0000", "2027-11-01");
const LOT_B = lot("LOT-B", "0b", "40.0000", "2027-06-30");
const LOT_X = lot("LOT-X", "0c", "5.0000", "2026-01-31", "EXPIRED");
// Lots with stock at WH_A (negative path): includes the expired one.
const LOTS_AT_WH_A = [LOT_A, LOT_X];
// Every lot of the product, one row per warehouse holding it: LOT-A is in both
// warehouses, so it appears twice and the panel must show it once.
const LOTS_ALL_WAREHOUSES = [LOT_A, { ...LOT_A, quantity: "12.0000" }, LOT_B, LOT_X];

const ADJ_PATH = "/api/v1/inventory/adjustments";

/** Adjustments list fixtures (L1 / L2): four PENDING_APPROVAL rows, one lot shape each. */
function adjRow(id: string, productName: string, extra: Record<string, unknown>) {
  return {
    id, adjustment_id: id, product_id: PROD_EXP.id, product_name: productName, product_sku: "ADJ-LST",
    warehouse_id: WH_A, warehouse_name: "Adj WH A", quantity_delta: 7, reason_code: "COUNT_DISCREPANCY",
    notes: "", status: "PENDING_APPROVAL", approval_required_role: "TA", created_by: OTHER_USER,
    created_at: "2026-10-12T08:00:00Z", is_self_approved: false, ...extra,
  };
}
const ROW_EXISTING = adjRow("aaaa0001-0000-4000-8000-000000000001", "ROW-EXISTING-LOT",
  { lot_id: LOT_A.lot_id, lot_number: LOT_A.lot_number, expiry_date: LOT_A.expiry_date });
const ROW_NEWNAMED = adjRow("aaaa0002-0000-4000-8000-000000000002", "ROW-NEW-NAMED",
  { lot_id: null, lot_number: "NEW-77", expiry_date: "2028-01-15" });
const ROW_AUTO = adjRow("aaaa0003-0000-4000-8000-000000000003", "ROW-NEW-AUTO",
  { lot_id: null, lot_number: null, auto_lot: true });
const ROW_NONE = adjRow("aaaa0004-0000-4000-8000-000000000004", "ROW-NO-LOT", {});
const ADJ_ROWS = [ROW_EXISTING, ROW_NEWNAMED, ROW_AUTO, ROW_NONE];

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface StubReply { status: number; data?: unknown; detail?: unknown }

interface Stubs {
  adjustments: unknown[];
  post: (body: Record<string, unknown>) => StubReply;
  approve: () => StubReply;
  calls: { posts: Array<Record<string, unknown>>; approves: string[]; lotGets: string[]; unstubbedWrites: string[] };
}

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

/**
 * One handler for every /api/ request: fixtures for the adjustment screens,
 * real backend for every other GET and for the login POST, and a hard stop
 * (abort + record) for any other write.
 */
async function installStubs(page: Page, adjustments: unknown[]): Promise<Stubs> {
  const stubs: Stubs = {
    adjustments,
    post: () => ({ status: 201, data: { adjustment_id: "bbbb0001-0000-4000-8000-000000000001", status: "PENDING_APPROVAL", quantity_delta: "0" } }),
    approve: () => ({ status: 200, data: { status: "POSTED" } }),
    calls: { posts: [], approves: [], lotGets: [], unstubbedWrites: [] },
  };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === ADJ_PATH) return reply(route, { status: 200, data: stubs.adjustments });
      if (new RegExp(`^${ADJ_PATH}/[0-9a-f-]{36}/approval-info$`).test(p)) {
        return reply(route, { status: 200, data: { product_override_applied: false, approver_escalated: false, can_approve: true } });
      }
      if (p === "/api/v1/inventory/lots") {
        stubs.calls.lotGets.push(url.search);
        const rows = url.searchParams.get("include_depleted") === "true" ? LOTS_ALL_WAREHOUSES : LOTS_AT_WH_A;
        return reply(route, { status: 200, data: rows });
      }
      if (p === "/api/v1/products") {
        const prod = (x: typeof PROD_EXP, batch: boolean, expiry: boolean) =>
          ({ ...x, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z", batch_tracking: batch, expiry_tracking: expiry });
        return reply(route, { status: 200, data: [prod(PROD_EXP, true, true), prod(PROD_NOEXP, true, false), prod(PROD_PLAIN, false, false)] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) {
        const node = (id: string, name: string) =>
          ({ id, name, address: null, hierarchy_level: 1, level_name: null, is_stock_holding: true, parent_node_id: null, children: [] });
        return reply(route, { status: 200, data: [node(WH_A, "Adj WH A"), node(WH_B, "Adj WH B")] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/adjustment-approval-rules$/.test(p)) return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/inventory/analytics/stock") {
        return reply(route, { status: 200, data: [PROD_EXP, PROD_NOEXP, PROD_PLAIN].flatMap((x) =>
          [WH_A, WH_B].map((wh) => ({ product_id: x.id, warehouse_id: wh, current_stock: "1000" }))) });
      }
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    if (method === "POST" && p === ADJ_PATH) {
      const body = req.postDataJSON() as Record<string, unknown>;
      stubs.calls.posts.push(body);
      return reply(route, stubs.post(body));
    }

    if (method === "POST" && new RegExp(`^${ADJ_PATH}/[0-9a-f-]{36}/approve$`).test(p)) {
      stubs.calls.approves.push(p);
      return reply(route, stubs.approve());
    }

    // Catch-all guard: no other write may leave the browser.
    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

interface Ctx { s: Strings; stubs: Stubs; consoleErrors: string[] }

async function openAdjustments(page: Page, locale: Locale, adjustments: unknown[] = []): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const consoleErrors = collectConsoleErrors(page);
  const stubs = await installStubs(page, adjustments);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/adjustments`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, consoleErrors };
}

/** Raw i18n keys / backend codes of the C3 adjustment screens that must never be visible. */
const RAW_KEY = /adjustment\.[a-z_]+|errors\.[A-Z][A-Z_]+|\b(LOT_REQUIRED|LOT_NUMBER_REQUIRED|EXPIRY_REQUIRED|LOT_EXPIRY_MISMATCH|INSUFFICIENT_LOT_STOCK)\b/;

/**
 * End-of-test checks shared by every scenario: no unstubbed write, no raw
 * i18n key / code, zero console errors. `expectedErrors` lists console errors
 * the scenario itself provokes on purpose.
 */
async function finish(page: Page, ctx: Ctx, label: string, expectedErrors: RegExp[] = []) {
  expect(ctx.stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  await expect(page.getByText(RAW_KEY)).toHaveCount(0);

  const unexpected = ctx.consoleErrors.filter((e) => !expectedErrors.some((re) => re.test(e)));
  console.log(`--- ${label} console errors ---`);
  for (const e of unexpected) console.log(e);
  expect(unexpected, `zero console errors (${label})`).toHaveLength(0);
}

/* ── Panel helpers ────────────────────────────────────────────────────────── */
async function openPanel(page: Page, s: Strings): Promise<Locator> {
  await page.getByRole("button", { name: s.newButton, exact: true }).click();
  const panel = page.locator("div.fixed.top-0.right-0.translate-x-0").filter({ hasText: s.panelTitle });
  await expect(panel).toBeVisible();
  return panel;
}

/** Product, warehouse, reason, then the quantity (magnitude for DAMAGE; "add" for the rest). */
async function fillPanel(
  panel: Locator,
  o: { product: { id: string }; reason: "DAMAGE" | "COUNT_DISCREPANCY"; qty: string; remove?: boolean },
) {
  await panel.locator("select").nth(0).selectOption(o.product.id);
  await panel.locator("select").nth(1).selectOption(WH_A);
  await panel.locator("select").nth(2).selectOption(o.reason);
  const inputs = panel.locator('input[type="number"]');
  // DAMAGE has a single quantity input; other reasons have Add then Remove.
  await inputs.nth(o.remove ? 1 : 0).fill(o.qty);
}

const lotSelect = (panel: Locator): Locator => panel.getByTestId("adj-lot-select");
/** The "existing lot" dropdown of the positive path is the last select in the panel. */
const existingLotSelect = (panel: Locator): Locator => panel.locator("select").last();
const submitButton = (panel: Locator, s: Strings): Locator => panel.getByRole("button", { name: s.submit, exact: true });
const lotId = (l: LotRow) => l.lot_id;

const LOT_FIELDS = ["lot_id", "lot_number", "expiry_date", "auto_lot"] as const;
function lotFieldsOf(body: Record<string, unknown>) {
  return Object.fromEntries(LOT_FIELDS.filter((k) => body[k] !== undefined).map((k) => [k, body[k]]));
}

for (const locale of ["en", "am"] as const) {
  test.describe(`New Adjustment panel — lots (${locale})`, () => {
    test(`N1 batch + DAMAGE: lot select with an Expired badge; no lot -> inline error, no POST (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      const panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "DAMAGE", qty: "5" });

      await expect(lotSelect(panel)).toBeVisible();
      await expect(lotSelect(panel).locator("option")).toHaveCount(3);   // placeholder + LOT-A + LOT-X
      await expect(lotSelect(panel).locator("option", { hasText: "LOT-A" })).not.toContainText(s.expired);
      await expect(lotSelect(panel).locator("option", { hasText: "LOT-X" })).toContainText(s.expired);

      await submitButton(panel, s).click();
      await expect(panel.getByText(s.errLotRequired)).toBeVisible();
      await page.waitForTimeout(1_000);
      expect(stubs.calls.posts).toHaveLength(0);

      await finish(page, ctx, `N1 (${locale})`);
    });

    test(`N2 negative with a lot: POST has lot_id only; above the lot's available -> adj-lot-error, no POST (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      const panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "DAMAGE", qty: "31" });
      await lotSelect(panel).selectOption(lotId(LOT_A));

      await expect(panel.getByTestId("adj-lot-error")).toHaveText(s.lotExceeds("30"));
      await submitButton(panel, s).click();
      await page.waitForTimeout(1_000);
      expect(stubs.calls.posts).toHaveLength(0);

      await panel.locator('input[type="number"]').first().fill("5");
      await expect(panel.getByTestId("adj-lot-error")).toHaveCount(0);
      await submitButton(panel, s).click();

      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(1);
      const body = stubs.calls.posts[0]!;
      expect(body).toMatchObject({ product_id: PROD_EXP.id, warehouse_id: WH_A, quantity_delta: -5, reason_code: "DAMAGE", lot_id: LOT_A.lot_id });
      expect(lotFieldsOf(body)).toEqual({ lot_id: LOT_A.lot_id });

      await finish(page, ctx, `N2 (${locale})`);
    });

    test(`N3 positive, existing lot: each lot once despite two warehouses; POST has lot_id only (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      const panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "COUNT_DISCREPANCY", qty: "7" });
      await expect(panel.getByTestId("adj-lot-mode-existing")).toHaveText(s.lotExisting);

      const select = existingLotSelect(panel);
      await expect(select.locator("option")).toHaveCount(4);              // placeholder + LOT-A + LOT-B + LOT-X
      await expect(select.locator("option", { hasText: "LOT-A" })).toHaveCount(1);
      await expect(select.locator("option", { hasText: "LOT-B" })).toHaveCount(1);
      expect(stubs.calls.lotGets.some((q) => q.includes("include_depleted=true"))).toBe(true);

      await select.selectOption(lotId(LOT_B));
      await submitButton(panel, s).click();

      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(1);
      const body = stubs.calls.posts[0]!;
      expect(body).toMatchObject({ quantity_delta: 7, reason_code: "COUNT_DISCREPANCY" });
      expect(lotFieldsOf(body)).toEqual({ lot_id: LOT_B.lot_id });

      await finish(page, ctx, `N3 (${locale})`);
    });

    test(`N4 positive, new lot: typed number + expiry; Generate sends auto_lot without a number (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      let panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "COUNT_DISCREPANCY", qty: "7" });
      await panel.getByTestId("adj-lot-mode-new").click();
      await expect(panel.getByTestId("adj-lot-mode-new")).toHaveText(s.lotNew);
      await panel.getByPlaceholder("e.g. LOT-2026-001").fill("NEW-LOT-1");
      await panel.locator('input[type="date"]').fill("2027-12-31");
      await submitButton(panel, s).click();

      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(1);
      const typed = stubs.calls.posts[0]!;
      expect(typed).toMatchObject({ quantity_delta: 7 });
      expect(lotFieldsOf(typed)).toEqual({ lot_number: "NEW-LOT-1", expiry_date: "2027-12-31", auto_lot: false });
      expect(typed).not.toHaveProperty("lot_id");

      // The success toast closes the panel after 3 s; reopening resets the form.
      await expect(page.locator("div.fixed.top-0.right-0.translate-x-full")).toHaveCount(1, { timeout: 10_000 });
      panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "COUNT_DISCREPANCY", qty: "9" });
      await panel.getByTestId("adj-lot-mode-new").click();
      await panel.getByLabel(s.autoLotLabel).check();
      await expect(panel.getByPlaceholder("e.g. LOT-2026-001")).toBeDisabled();
      await panel.locator('input[type="date"]').fill("2028-03-01");
      await submitButton(panel, s).click();

      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(2);
      const generated = stubs.calls.posts[1]!;
      expect(generated).toMatchObject({ quantity_delta: 9 });
      expect(lotFieldsOf(generated)).toEqual({ expiry_date: "2028-03-01", auto_lot: true });
      expect(generated).not.toHaveProperty("lot_id");
      expect(generated).not.toHaveProperty("lot_number");

      await finish(page, ctx, `N4 (${locale})`);
    });

    test(`N5 expiry-tracked new lot without expiry is blocked; a non-expiry product goes through (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      let panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "COUNT_DISCREPANCY", qty: "7" });
      await panel.getByTestId("adj-lot-mode-new").click();
      await panel.getByPlaceholder("e.g. LOT-2026-001").fill("NEW-LOT-2");
      await submitButton(panel, s).click();

      await expect(panel.getByText(s.errExpiry)).toBeVisible();
      await page.waitForTimeout(1_000);
      expect(stubs.calls.posts).toHaveLength(0);

      // Same flow on the batch product that does not track expiry: allowed, no expiry_date sent.
      await panel.getByRole("button", { name: "✕" }).click();
      panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_NOEXP, reason: "COUNT_DISCREPANCY", qty: "3" });
      await panel.getByTestId("adj-lot-mode-new").click();
      await panel.getByPlaceholder("e.g. LOT-2026-001").fill("NEW-LOT-3");
      await submitButton(panel, s).click();

      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(1);
      expect(lotFieldsOf(stubs.calls.posts[0]!)).toEqual({ lot_number: "NEW-LOT-3", auto_lot: false });

      await finish(page, ctx, `N5 (${locale})`);
    });

    test(`N6 DAMAGE -> COUNT_DISCREPANCY +qty clears the chosen lot: no stale lot_id (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      const panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "DAMAGE", qty: "5" });
      await lotSelect(panel).selectOption(lotId(LOT_A));
      await expect(lotSelect(panel)).toHaveValue(lotId(LOT_A));

      await panel.locator("select").nth(2).selectOption("COUNT_DISCREPANCY");
      await panel.locator('input[type="number"]').first().fill("7");
      await expect(panel.getByTestId("adj-lot-select")).toHaveCount(0);
      await expect(existingLotSelect(panel)).toHaveValue("");

      // Nothing is selected any more, so submitting is refused rather than sending LOT-A.
      await submitButton(panel, s).click();
      await expect(panel.getByText(s.errLotRequired)).toBeVisible();
      await page.waitForTimeout(1_000);
      expect(stubs.calls.posts).toHaveLength(0);

      await panel.getByTestId("adj-lot-mode-new").click();
      await panel.getByPlaceholder("e.g. LOT-2026-001").fill("NEW-LOT-6");
      await panel.locator('input[type="date"]').fill("2027-12-31");
      await submitButton(panel, s).click();

      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(1);
      const body = stubs.calls.posts[0]!;
      expect(lotFieldsOf(body)).toEqual({ lot_number: "NEW-LOT-6", expiry_date: "2027-12-31", auto_lot: false });
      expect(body).not.toHaveProperty("lot_id");

      await finish(page, ctx, `N6 (${locale})`);
    });

    test(`N7 non-batch product: no lot UI, POST has none of the lot fields (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      const panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_PLAIN, reason: "DAMAGE", qty: "5" });
      await expect(panel.getByTestId("adj-lot-select")).toHaveCount(0);
      await expect(panel.getByTestId("adj-lot-mode-existing")).toHaveCount(0);
      await expect(panel.getByTestId("adj-lot-mode-new")).toHaveCount(0);

      await submitButton(panel, s).click();
      await expect.poll(() => stubs.calls.posts.length, { timeout: 10_000 }).toBe(1);
      const body = stubs.calls.posts[0]!;
      expect(body).toMatchObject({ product_id: PROD_PLAIN.id, quantity_delta: -5 });
      expect(lotFieldsOf(body)).toEqual({});
      expect(stubs.calls.lotGets).toHaveLength(0);

      await finish(page, ctx, `N7 (${locale})`);
    });

    test(`N8 backend 422 LOT_EXPIRY_MISMATCH / INSUFFICIENT_LOT_STOCK: translated text, no raw code (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale);
      const { s, stubs } = ctx;

      const panel = await openPanel(page, s);
      await fillPanel(panel, { product: PROD_EXP, reason: "COUNT_DISCREPANCY", qty: "7" });
      await panel.getByTestId("adj-lot-mode-new").click();
      await panel.getByPlaceholder("e.g. LOT-2026-001").fill("NEW-LOT-8");
      await panel.locator('input[type="date"]').fill("2027-12-31");

      stubs.post = () => ({ status: 422, detail: { code: "LOT_EXPIRY_MISMATCH", message: "backend-only wording" } });
      await submitButton(panel, s).click();
      await expect(panel.getByText(s.errMismatch)).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/LOT_EXPIRY_MISMATCH/)).toHaveCount(0);
      await expect(page.getByText("backend-only wording")).toHaveCount(0);
      expect(stubs.calls.posts).toHaveLength(1);

      // Negative path: the lot cannot cover the deduction.
      await panel.locator("select").nth(2).selectOption("DAMAGE");
      await panel.locator('input[type="number"]').first().fill("5");
      await lotSelect(panel).selectOption(lotId(LOT_A));
      stubs.post = () => ({ status: 422, detail: { code: "INSUFFICIENT_LOT_STOCK", message: "backend-only wording" } });
      await submitButton(panel, s).click();
      await expect(panel.getByText(s.errInsufficient)).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/INSUFFICIENT_LOT_STOCK/)).toHaveCount(0);
      await expect(page.getByText("backend-only wording")).toHaveCount(0);
      expect(stubs.calls.posts).toHaveLength(2);

      await finish(page, ctx, `N8 (${locale})`);
    });
  });

  test.describe(`Adjustments list and approval view — lot column (${locale})`, () => {
    test(`L1 list rows: lot + expiry / New lot: <number> / generated at posting / dash (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale, ADJ_ROWS);
      const { s } = ctx;

      await expect(page.locator("th", { hasText: s.lotHeader })).toBeVisible();
      const cell = (name: string) => page.locator("tr").filter({ hasText: name }).getByTestId("adj-row-lot");
      const expiry = await page.evaluate((d) => new Date(d).toLocaleDateString(), LOT_A.expiry_date!);

      await expect(cell("ROW-EXISTING-LOT")).toHaveText(`LOT-A · ${expiry}`);
      await expect(cell("ROW-NEW-NAMED")).toHaveText(s.lotNewNamed("NEW-77"));
      await expect(cell("ROW-NEW-AUTO")).toHaveText(s.lotNewAuto);
      await expect(cell("ROW-NO-LOT")).toHaveText("—");

      await finish(page, ctx, `L1 (${locale})`);
    });

    test(`L2 approval view: adj-approval-lot shows the lot (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale, ADJ_ROWS);
      const { s } = ctx;

      const card = (name: string) => page.locator("div.bg-white.border-amber-200").filter({ hasText: name }).filter({ has: page.getByTestId("adj-approval-lot") });
      const expiry = await page.evaluate((d) => new Date(d).toLocaleDateString(), LOT_A.expiry_date!);

      await expect(card("ROW-EXISTING-LOT").getByTestId("adj-approval-lot")).toHaveText(`${s.lotHeader}: LOT-A · ${expiry}`);
      await expect(card("ROW-NEW-NAMED").getByTestId("adj-approval-lot")).toHaveText(`${s.lotHeader}: ${s.lotNewNamed("NEW-77")}`);
      await expect(card("ROW-NEW-AUTO").getByTestId("adj-approval-lot")).toHaveText(`${s.lotHeader}: ${s.lotNewAuto}`);
      await expect(card("ROW-NO-LOT").getByTestId("adj-approval-lot")).toHaveText(`${s.lotHeader}: —`);

      await finish(page, ctx, `L2 (${locale})`);
    });

    test(`N9 approve returns 422 INSUFFICIENT_LOT_STOCK: translated text on the Adjustments page, no raw code (${locale})`, async ({ page }) => {
      const ctx = await openAdjustments(page, locale, ADJ_ROWS);
      const { s, stubs } = ctx;
      stubs.approve = () => ({ status: 422, detail: { code: "INSUFFICIENT_LOT_STOCK", message: "backend-only wording" } });

      const card = page.locator("div.bg-white.border-amber-200").filter({ hasText: "ROW-EXISTING-LOT" });
      await card.getByRole("button", { name: s.approve, exact: true }).click();

      await expect(page.getByTestId("adj-action-error")).toHaveText(s.errInsufficient, { timeout: 10_000 });
      await expect(page.getByText(/INSUFFICIENT_LOT_STOCK/)).toHaveCount(0);
      await expect(page.getByText("backend-only wording")).toHaveCount(0);
      expect(stubs.calls.approves).toHaveLength(1);
      expect(stubs.calls.unstubbedWrites).toHaveLength(0);

      await finish(page, ctx, `N9 (${locale})`, [/422/]);
    });
  });
}
