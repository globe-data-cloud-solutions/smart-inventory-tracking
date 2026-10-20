/**
 * Playwright E2E — transfer detail page /{org}/transfers/{id}
 * (session/2026-10-14-fefo-closeout).
 *
 * Covers, for en + am:
 *   D1 Loads: header shows reference_number, type, translated status, from -> to names,
 *      lines table (product name, SKU, qty, unit); no console / page errors
 *   D2 reference_number null: header shows the type label and date; no UUID text anywhere
 *   D3 Warehouse names null: from / to show "—", never a UUID
 *   D4 APPROVED (or later) with lot_allocations: the lot split is shown
 *   D5 Discrepancies, TA session: Resolve button visible; it opens the Resolve dialog (not submitted)
 *   D6 Same data, WM stub (asRole): no Resolve button
 *   D7 404 -> translated not-found message; 403 TRANSFER_OUT_OF_SCOPE -> translated no-access
 *      message; neither shows a raw code
 *   D8 Back link goes to the Transfers list
 *   D9 The Open discrepancies panel link lands on this page and it loads
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real, using the
 * permanent zz-e2e-ta TA probe account (the WM cases patch the role in the client session
 * only, see helpers/session-role.ts). Every transfer / discrepancy / lots / products / nodes
 * request is answered from the fixtures below by one page.route() handler (installStubs), and
 * that same handler is the catch-all guard: any other non-GET request to an /api/ path is
 * aborted, recorded, and fails the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/transfer-detail.spec.ts --project=chromium --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { asRole } from "./helpers/session-role";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });
// One worker for this file: parallel real logins make the local gateway answer 503.
test.describe.configure({ mode: "default" });

type Locale = "en" | "am";

interface Collected { console: string[]; pageErrors: string[] }

function collectErrors(page: Page): Collected {
  const out: Collected = { console: [], pageErrors: [] };
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return;
    if (/Failed to fetch RSC payload.*Falling back to browser navigation/.test(msg.text())) return;
    out.console.push(msg.text());
  });
  page.on("pageerror", (err) => out.pageErrors.push(err.message));
  return out;
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
  const v = d.transfers.view;
  return {
    back:         d.transfers.back as string,
    from:         d.transfers.detail.from as string,
    to:           d.transfers.detail.to as string,
    type:         v.type as Record<string, string>,
    status:       v.status as Record<string, string>,
    untitled:     v.untitled as string,
    notFound:     v.not_found as string,
    outOfScope:   v.out_of_scope as string,
    loadFailed:   v.load_failed as string,
    linesTitle:   v.lines_title as string,
    colProduct:   v.col_product as string,
    colSku:       v.col_sku as string,
    colQuantity:  v.col_quantity as string,
    colUnit:      v.col_unit as string,
    lotsTitle:    d.transfers.lots.title as string,
    discTitle:    d.transfers.discrepancies.title as string,
    resolve:      d.transfers.discrepancies.resolve as string,
  };
}
type Strings = ReturnType<typeof localeStrings>;

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const WH_SRC = "11111111-1111-4111-8111-111111111111";
const WH_DST = "22222222-2222-4222-8222-222222222222";
const OTHER_USER = "99999999-9999-4999-8999-999999999999";
const T_ID = "aaaa0005-0000-4000-8000-000000000005";
const LINE_1 = "55555555-5555-4555-8555-555555555501";
const LINE_2 = "55555555-5555-4555-8555-555555555502";
const D_OPEN = "66666666-6666-4666-8666-666666666621";

const PROD_A = { id: "33333333-3333-4333-8333-333333333311", sku: "DET-A-01", name: "DETAIL-WIDGET-A" };
const PROD_B = { id: "33333333-3333-4333-8333-333333333312", sku: "DET-B-02", name: "DETAIL-WIDGET-B" };
const LOT_1 = { lot_id: "44444444-4444-4444-8444-444444444411", lot_number: "DET-LOT-1", expiry_date: "2027-03-31" };
const LOT_2 = { lot_id: "44444444-4444-4444-8444-444444444412", lot_number: "DET-LOT-2", expiry_date: "2027-08-31" };

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
/** Raw i18n keys and raw backend codes that must never be visible text. */
const RAW_TEXT = /transfers\.(view|detail|lots|discrepancies)\.|\berrors\.[A-Z]|\b(TRANSFER_OUT_OF_SCOPE|NOT_FOUND|DISCREPANCY_[A-Z_]+)\b/;

interface DetailFixture {
  transfer_id: string; transfer_type: string; status: string; reference_number: string | null;
  from_warehouse_id: string; from_warehouse_name: string | null;
  to_warehouse_id: string; to_warehouse_name: string | null;
  created_at: string; is_self_approved: boolean;
  lines: Array<{ line_id: string; product_id: string; product_name: string; sku: string; quantity: string; uom: string }>;
  lot_allocations: Array<{
    line_id: string; product_id: string; lot_id: string; lot_number: string | null;
    expiry_date: string | null; quantity: string; is_override: boolean;
  }>;
  discrepancies: unknown[];
}

function detail(over: Partial<DetailFixture> = {}): DetailFixture {
  return {
    transfer_id: T_ID, transfer_type: "PUSH", status: "IN_TRANSIT", reference_number: "TRF-2026-0042",
    from_warehouse_id: WH_SRC, from_warehouse_name: "Detail Source WH",
    to_warehouse_id: WH_DST, to_warehouse_name: "Detail Dest WH",
    created_at: "2026-10-12T08:00:00Z", is_self_approved: false,
    lines: [
      { line_id: LINE_1, product_id: PROD_A.id, product_name: PROD_A.name, sku: PROD_A.sku, quantity: "40.0000", uom: "pcs" },
      { line_id: LINE_2, product_id: PROD_B.id, product_name: PROD_B.name, sku: PROD_B.sku, quantity: "12.0000", uom: "box" },
    ],
    lot_allocations: [],
    discrepancies: [],
    ...over,
  };
}

const OPEN_DISCREPANCY = {
  id: D_OPEN, transfer_line_id: LINE_1, product_id: PROD_A.id,
  lot_id: LOT_1.lot_id, lot_number: LOT_1.lot_number,
  sent_quantity: "40.0000", received_quantity: "38.0000", missing_quantity: "2.0000",
  reason: "SHORT", note: "2 cartons crushed", status: "OPEN", created_at: "2026-10-13T09:00:00Z",
};

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface StubReply { status: number; data?: unknown; detail?: unknown }

interface Stubs {
  /** GET /inventory/transfers/{T_ID}. */
  detail: () => StubReply;
  /** GET /inventory/transfers (the list page — D8 / D9). */
  list: unknown[];
  /** GET /inventory/transfers/discrepancies?status=OPEN (D9). */
  openList: unknown[];
  calls: { detailGets: number; unstubbedWrites: string[] };
}

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

const errReply = (status: number, code: string): StubReply =>
  ({ status, detail: { code, message: "backend english message" } });

async function installStubs(page: Page, detailFn: () => StubReply): Promise<Stubs> {
  const stubs: Stubs = {
    detail: detailFn, list: [], openList: [],
    calls: { detailGets: 0, unstubbedWrites: [] },
  };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === "/api/v1/inventory/transfers") return reply(route, { status: 200, data: stubs.list });
      if (p === "/api/v1/inventory/transfers/discrepancies") return reply(route, { status: 200, data: stubs.openList });
      if (p === `/api/v1/inventory/transfers/${T_ID}`) {
        stubs.calls.detailGets += 1;
        return reply(route, stubs.detail());
      }
      if (p === `/api/v1/inventory/transfers/${T_ID}/approval-info`) {
        return reply(route, { status: 200, data: {
          transfer_id: T_ID, required_authority_level: 1, required_role_display: "Tenant Admin",
          is_auto_approve: false, can_approve: false, reason: "", current_step: 1, total_steps: 1,
        } });
      }
      if (p === "/api/v1/inventory/lots") return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/products") {
        return reply(route, { status: 200, data: [PROD_A, PROD_B].map((x) => ({
          ...x, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z",
          batch_tracking: true, expiry_tracking: true,
        })) });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) return reply(route, { status: 200, data: [] });
      if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/inventory/analytics/stock") return reply(route, { status: 200, data: [] });
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    // Catch-all guard: no other write may leave the browser.
    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

interface Ctx { s: Strings; stubs: Stubs; errors: Collected }

interface OpenOpts {
  role?: string;
  /** Land on the detail page (default), or on the Transfers list. */
  startAt?: "detail" | "list";
  setup?: (stubs: Stubs) => void;
}

async function open(page: Page, locale: Locale, detailFn: () => StubReply, opts: OpenOpts = {}): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const errors = collectErrors(page);
  const stubs = await installStubs(page, detailFn);
  opts.setup?.(stubs);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  if (opts.role) await asRole(page, opts.role);
  const target = opts.startAt === "list" ? "transfers" : `transfers/${T_ID}`;
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/${target}`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, errors };
}

/**
 * End-of-test checks shared by every scenario: no page error, no unstubbed write, no raw
 * key/code on screen, zero console errors. `expectedErrors` lists console errors the
 * scenario itself provokes on purpose.
 */
async function finish(page: Page, ctx: Ctx, label: string, expectedErrors: RegExp[] = []) {
  expect(ctx.errors.pageErrors, `no page errors (${label})`).toEqual([]);
  expect(ctx.stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  await expect(page.getByText(RAW_TEXT)).toHaveCount(0);

  const unexpected = ctx.errors.console.filter((e) => !expectedErrors.some((re) => re.test(e)));
  console.log(`--- ${label} console errors ---`);
  for (const e of unexpected) console.log(e);
  for (const e of ctx.errors.pageErrors) console.log(`[pageerror] ${e}`);
  expect(unexpected, `zero console errors (${label})`).toHaveLength(0);
}

const ok = (data: unknown): StubReply => ({ status: 200, data });

for (const locale of ["en", "am"] as const) {
  test.describe(`Transfer detail page (${locale})`, () => {
    test(`D1 loads: reference, type, translated status, from -> to, lines table (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail()));
      const { s } = ctx;

      await expect(page.getByText("TRF-2026-0042", { exact: true })).toBeVisible();
      await expect(page.getByText(s.type.PUSH!, { exact: true })).toBeVisible();
      await expect(page.getByText(s.status.IN_TRANSIT!, { exact: true })).toBeVisible();

      await expect(page.getByText(s.from, { exact: true })).toBeVisible();
      await expect(page.getByText("Detail Source WH", { exact: true })).toBeVisible();
      await expect(page.getByText(s.to, { exact: true })).toBeVisible();
      await expect(page.getByText("Detail Dest WH", { exact: true })).toBeVisible();

      await expect(page.getByText(s.linesTitle, { exact: true })).toBeVisible();
      for (const h of [s.colProduct, s.colSku, s.colQuantity, s.colUnit]) {
        await expect(page.getByRole("columnheader", { name: h, exact: true })).toBeVisible();
      }
      const rowA = page.locator("tbody tr").filter({ hasText: PROD_A.name });
      await expect(rowA.getByRole("cell", { name: PROD_A.name, exact: true })).toBeVisible();
      await expect(rowA.getByRole("cell", { name: PROD_A.sku, exact: true })).toBeVisible();
      await expect(rowA.getByRole("cell", { name: "40", exact: true })).toBeVisible();
      await expect(rowA.getByRole("cell", { name: "pcs", exact: true })).toBeVisible();
      const rowB = page.locator("tbody tr").filter({ hasText: PROD_B.name });
      await expect(rowB.getByRole("cell", { name: PROD_B.sku, exact: true })).toBeVisible();
      await expect(rowB.getByRole("cell", { name: "12", exact: true })).toBeVisible();
      await expect(rowB.getByRole("cell", { name: "box", exact: true })).toBeVisible();

      await finish(page, ctx, `D1 ${locale}`);
    });

    test(`D2 reference_number null: type label + date in the header, no UUID text anywhere (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail({ reference_number: null })));
      const { s } = ctx;

      const date = await page.evaluate(
        ({ iso, l }) => new Intl.DateTimeFormat(l === "am" ? "am-ET" : "en-US", { year: "numeric", month: "numeric", day: "numeric", calendar: "gregory" }).format(new Date(iso)),
        { iso: "2026-10-12T08:00:00Z", l: locale },
      );
      const title = s.untitled.replace("{type}", s.type.PUSH!).replace("{date}", date);
      await expect(page.getByText(title, { exact: true })).toBeVisible();

      const bodyText = await page.locator("body").innerText();
      expect(bodyText, "the transfer_id string is not visible").not.toContain(T_ID);
      expect(bodyText, "no UUID anywhere on the page").not.toMatch(UUID_RE);
      await finish(page, ctx, `D2 ${locale}`);
    });

    test(`D3 warehouse names null: from / to show a dash, never a UUID (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail({ from_warehouse_name: null, to_warehouse_name: null })));
      const { s } = ctx;

      await expect(page.getByText(s.from, { exact: true })).toBeVisible();
      const dashes = page.getByText("—", { exact: true });
      await expect(dashes).toHaveCount(2);

      const bodyText = await page.locator("body").innerText();
      expect(bodyText).not.toContain(WH_SRC);
      expect(bodyText).not.toContain(WH_DST);
      expect(bodyText, "no UUID anywhere on the page").not.toMatch(UUID_RE);
      await finish(page, ctx, `D3 ${locale}`);
    });

    test(`D4 APPROVED with lot_allocations: the lot split is shown (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail({
        status: "APPROVED",
        lot_allocations: [
          { line_id: LINE_1, product_id: PROD_A.id, ...LOT_1, quantity: "25.0000", is_override: false },
          { line_id: LINE_1, product_id: PROD_A.id, ...LOT_2, quantity: "15.0000", is_override: false },
        ],
      })));
      const { s } = ctx;

      await expect(page.getByText(s.status.APPROVED!, { exact: true })).toBeVisible();
      await expect(page.getByText(s.lotsTitle, { exact: true })).toBeVisible();
      const lot1 = page.locator("tbody tr").filter({ hasText: LOT_1.lot_number });
      await expect(lot1.getByRole("cell", { name: PROD_A.name, exact: true })).toBeVisible();
      await expect(lot1.getByRole("cell", { name: "25", exact: true })).toBeVisible();
      const lot2 = page.locator("tbody tr").filter({ hasText: LOT_2.lot_number });
      await expect(lot2.getByRole("cell", { name: "15", exact: true })).toBeVisible();
      await finish(page, ctx, `D4 ${locale}`);
    });

    test(`D4b before APPROVED there is no lot split (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail({ status: "PENDING_APPROVAL" })));
      await expect(page.getByText("TRF-2026-0042", { exact: true })).toBeVisible();
      await expect(page.getByText(ctx.s.lotsTitle, { exact: true })).toHaveCount(0);
      await finish(page, ctx, `D4b ${locale}`);
    });

    test(`D5 discrepancies, TA session: Resolve is visible and opens the Resolve dialog (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail({
        status: "PARTIALLY_RECEIVED", discrepancies: [OPEN_DISCREPANCY],
      })));
      const { s } = ctx;

      await expect(page.getByText(s.discTitle, { exact: true })).toBeVisible();
      const resolve = page.getByTestId(`discrepancy-resolve-${D_OPEN}`);
      await expect(resolve).toBeVisible();
      await expect(resolve).toHaveText(s.resolve);
      await resolve.click();
      await expect(page.getByTestId("resolve-discrepancy-dialog")).toBeVisible();
      // Opened only — never submitted.
      await finish(page, ctx, `D5 ${locale}`);
    });

    test(`D6 same data, WM stub: the discrepancy shows, no Resolve button (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail({
        status: "PARTIALLY_RECEIVED", discrepancies: [OPEN_DISCREPANCY],
      })), { role: "WM" });
      const { s } = ctx;

      await expect(page.getByText(s.discTitle, { exact: true })).toBeVisible();
      await expect(page.getByTestId(`discrepancy-row-${D_OPEN}`)).toBeVisible();
      await expect(page.getByTestId(`discrepancy-resolve-${D_OPEN}`)).toHaveCount(0);
      await expect(page.getByRole("button", { name: s.resolve, exact: true })).toHaveCount(0);
      await finish(page, ctx, `D6 ${locale}`);
    });

    test(`D7 404 and 403 TRANSFER_OUT_OF_SCOPE: translated messages, no raw code (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => errReply(404, "NOT_FOUND"));
      const { s } = ctx;
      await expect(page.getByText(s.notFound, { exact: true })).toBeVisible();
      await expect(page.getByText(s.outOfScope, { exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: s.back })).toBeVisible();
      await finish(page, ctx, `D7 404 ${locale}`);

      // Same page, now a 403: reload re-asks the stubbed endpoint.
      ctx.stubs.detail = () => errReply(403, "TRANSFER_OUT_OF_SCOPE");
      await page.reload();
      await page.waitForLoadState("networkidle");
      await expect(page.getByText(s.outOfScope, { exact: true })).toBeVisible();
      await expect(page.getByText(s.notFound, { exact: true })).toHaveCount(0);
      await finish(page, ctx, `D7 403 ${locale}`);
    });

    test(`D8 back link goes to the Transfers list (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, () => ok(detail()), {
        setup: (st) => { st.list = [{ ...detail(), lines: detail().lines }]; },
      });
      const { s } = ctx;

      await expect(page.getByText("TRF-2026-0042", { exact: true })).toBeVisible();
      await page.getByRole("link", { name: s.back }).click();
      await page.waitForURL(new RegExp(`/${E2E_TA_SLUG}/transfers$`));
      await expect(page.getByRole("link", { name: s.back })).toHaveCount(0);
      await page.waitForLoadState("networkidle");
      await finish(page, ctx, `D8 ${locale}`);
    });

    test(`D9 the Open discrepancies panel link lands on the detail page and it loads (${locale})`, async ({ page }) => {
      const base = detail({ status: "PARTIALLY_RECEIVED", discrepancies: [OPEN_DISCREPANCY] });
      const ctx = await open(page, locale, () => ok(base), {
        startAt: "list",
        setup: (st) => {
          st.list = [base];
          st.openList = [{
            ...OPEN_DISCREPANCY,
            transfer_order_id: T_ID, transfer_type: "PUSH", from_warehouse_id: WH_SRC, to_warehouse_id: WH_DST,
          }];
        },
      });
      const { s, stubs } = ctx;

      const panel = page.getByTestId("open-discrepancies-panel");
      await expect(panel).toBeVisible();
      await panel.getByTestId(`open-discrepancy-${D_OPEN}`).getByRole("link").click();

      await page.waitForURL(new RegExp(`/${E2E_TA_SLUG}/transfers/${T_ID}$`));
      await expect(page.getByText("TRF-2026-0042", { exact: true })).toBeVisible();
      await expect(page.getByText(s.status.PARTIALLY_RECEIVED!, { exact: true })).toBeVisible();
      await expect(page.getByText(s.discTitle, { exact: true })).toBeVisible();
      expect(stubs.calls.detailGets, "the detail endpoint was called").toBeGreaterThan(0);
      await finish(page, ctx, `D9 ${locale}`);
    });
  });
}
