/**
 * Playwright E2E — open transit discrepancies: "awaiting resolution" hint and the
 * Adjustments-page link (session 18, prompt D1).
 *
 * Covers, for en + am:
 *   a) non-resolver (WM stub): panel visible, NO Resolve buttons, awaiting-resolution hint visible
 *   b) resolver (TA): Resolve buttons visible, hint NOT visible
 *   c) Adjustments page with 2 open discrepancies: notice shows the count; the link lands on
 *      /<org>/transfers?focus=discrepancies with #open-discrepancies in the viewport and expanded
 *   d) Adjustments page with the discrepancies endpoint answering 403: no notice, page renders
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) is real, using the permanent zz-e2e-ta TA
 * probe account; the session role is patched client-side (asRole) for (a). Transfers /
 * discrepancies / products / nodes requests are answered from fixtures by one page.route()
 * handler, which also aborts and records any other non-GET /api/ request (fails the test).
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/discrepancy-visibility.spec.ts --project=chromium --workers=1
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
  return {
    awaiting:      d.transfers.discrepancies.awaiting_resolution as string,
    resolveButton: d.transfers.discrepancies.resolve as string,
    notice: (n: number) => (d.adjustment.transit_discrepancies_notice as string).replace("{count}", String(n)),
    link:          d.adjustment.transit_discrepancies_link as string,
  };
}

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const WH_SRC = "11111111-1111-4111-8111-111111111111";
const WH_DST = "22222222-2222-4222-8222-222222222222";
const PROD = { id: "33333333-3333-4333-8333-333333333301", sku: "SMK-B-01", name: "SMOKE-BATCH" };
const T_ID = "aaaa0003-0000-4000-8000-000000000003";
const LINE_ID = "55555555-5555-4555-8555-555555555503";
const D_1 = "66666666-6666-4666-8666-666666666601";
const D_2 = "66666666-6666-4666-8666-666666666602";

const row = (id: string) => ({
  id, transfer_line_id: LINE_ID, product_id: PROD.id, lot_id: null, lot_number: null,
  sent_quantity: "40.0000", received_quantity: "38.0000", missing_quantity: "2.0000",
  reason: "SHORT", note: null, status: "OPEN", created_at: "2026-10-13T09:00:00Z",
  transfer_order_id: T_ID, transfer_type: "PUSH", from_warehouse_id: WH_SRC, to_warehouse_id: WH_DST,
});
const TWO_ROWS = [row(D_1), row(D_2)];

const TRANSFER = {
  transfer_id: T_ID, transfer_type: "PUSH", status: "PARTIALLY_RECEIVED",
  from_warehouse_id: WH_SRC, from_warehouse_name: "Smoke Source WH",
  to_warehouse_id: WH_DST, to_warehouse_name: "Smoke Dest WH",
  lines: [{ line_id: LINE_ID, product_id: PROD.id, product_name: PROD.name, sku: PROD.sku, quantity: "40.0000", uom: "pcs" }],
  lot_allocations: [],
  created_by: "99999999-9999-4999-8999-999999999999", created_by_authority_level: 1,
  created_at: "2026-10-12T08:00:00Z", is_self_approved: false,
};

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface StubReply { status: number; data?: unknown; detail?: unknown }
interface Stubs { openList: () => StubReply; unstubbedWrites: string[]; openGets: number }

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installStubs(page: Page, openList: () => StubReply): Promise<Stubs> {
  const stubs: Stubs = { openList, unstubbedWrites: [], openGets: 0 };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === "/api/v1/inventory/transfers") return reply(route, { status: 200, data: [TRANSFER] });
      if (p === "/api/v1/inventory/transfers/discrepancies") {
        stubs.openGets += 1;
        return reply(route, stubs.openList());
      }
      if (p === `/api/v1/inventory/transfers/${T_ID}`) {
        return reply(route, { status: 200, data: { ...TRANSFER, discrepancies: [] } });
      }
      if (p === "/api/v1/inventory/adjustments") return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/inventory/analytics/stock") return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/products") {
        return reply(route, { status: 200, data: [
          { ...PROD, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z", batch_tracking: true, expiry_tracking: true },
        ] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) {
        const node = (id: string, name: string, level: number, parent: string | null, children: unknown[]) =>
          ({ id, name, address: null, hierarchy_level: level, level_name: null, is_stock_holding: true, parent_node_id: parent, children });
        return reply(route, { status: 200, data: [node(WH_SRC, "Smoke Source WH", 1, null, [node(WH_DST, "Smoke Dest WH", 2, WH_SRC, [])])] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return reply(route, { status: 200, data: [] });
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    stubs.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

interface Ctx { stubs: Stubs; errors: Collected }

async function start(
  page: Page,
  openList: () => StubReply,
  role?: { role: string; warehouseId?: string },
): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const errors = collectErrors(page);
  const stubs = await installStubs(page, openList);
  await login(page, E2E_TA_EMAIL, taPassword);
  if (role) await asRole(page, role.role, role.warehouseId);
  return { stubs, errors };
}

async function finish(page: Page, ctx: Ctx, label: string) {
  expect(ctx.errors.pageErrors, `no page errors (${label})`).toEqual([]);
  expect(ctx.stubs.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  console.log(`--- ${label} console errors ---`);
  for (const e of ctx.errors.console) console.log(e);
  for (const e of ctx.errors.pageErrors) console.log(`[pageerror] ${e}`);
  expect(ctx.errors.console, `zero console errors (${label})`).toHaveLength(0);
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Discrepancy visibility (${locale})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
    });

    test(`a) non-resolver sees the panel, no Resolve buttons, and the awaiting hint (${locale})`, async ({ page }) => {
      const s = localeStrings(locale);
      const ctx = await start(page, () => ({ status: 200, data: TWO_ROWS }), { role: "WM", warehouseId: WH_DST });
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers`);
      await page.waitForLoadState("networkidle");

      const panel = page.getByTestId("open-discrepancies-panel");
      await expect(panel).toBeVisible();
      await expect(panel.locator("tbody tr")).toHaveCount(2);
      await expect(panel).toHaveAttribute("id", "open-discrepancies");
      for (const id of [D_1, D_2]) {
        await expect(page.getByTestId(`open-discrepancy-resolve-${id}`)).toHaveCount(0);
      }
      await expect(panel.getByRole("button", { name: s.resolveButton, exact: true })).toHaveCount(0);
      const hint = panel.getByTestId("discrepancy-awaiting-resolution");
      await expect(hint).toBeVisible();
      await expect(hint).toHaveText(s.awaiting);

      await finish(page, ctx, `a ${locale}`);
    });

    test(`b) resolver sees Resolve buttons and no hint (${locale})`, async ({ page }) => {
      const s = localeStrings(locale);
      const ctx = await start(page, () => ({ status: 200, data: TWO_ROWS }));
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers`);
      await page.waitForLoadState("networkidle");

      const panel = page.getByTestId("open-discrepancies-panel");
      await expect(panel).toBeVisible();
      for (const id of [D_1, D_2]) {
        await expect(page.getByTestId(`open-discrepancy-resolve-${id}`)).toBeVisible();
      }
      await expect(page.getByTestId("discrepancy-awaiting-resolution")).toHaveCount(0);
      await expect(page.getByText(s.awaiting, { exact: true })).toHaveCount(0);

      await finish(page, ctx, `b ${locale}`);
    });

    test(`c) Adjustments notice shows the count; the link focuses the Transfers panel (${locale})`, async ({ page }) => {
      const s = localeStrings(locale);
      const ctx = await start(page, () => ({ status: 200, data: TWO_ROWS }));
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/adjustments`);

      const notice = page.getByTestId("adjustments-discrepancy-notice");
      await expect(notice).toBeVisible();
      await expect(notice).toContainText(s.notice(2));
      await notice.getByRole("link", { name: s.link, exact: true }).click();

      await page.waitForURL(new RegExp(`/${E2E_TA_SLUG}/transfers\\?focus=discrepancies$`));
      const panel = page.locator("#open-discrepancies");
      await expect(panel).toBeVisible();
      await expect(panel).toBeInViewport();
      await expect(page.getByTestId("open-discrepancies-toggle")).toHaveAttribute("aria-expanded", "true");
      await expect(panel.locator("tbody tr")).toHaveCount(2);

      await finish(page, ctx, `c ${locale}`);
    });

    test(`d) Adjustments page with the endpoint answering 403: no notice, page renders (${locale})`, async ({ page }) => {
      const ctx = await start(page, () => ({ status: 403, detail: { code: "PERMISSION_DENIED", message: "forbidden" } }));
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/adjustments`);
      await page.waitForLoadState("networkidle");

      await expect.poll(() => ctx.stubs.openGets).toBeGreaterThan(0);
      await expect(page.getByTestId("adjustments-discrepancy-notice")).toHaveCount(0);
      // The page itself still renders (header + New Adjustment panel trigger area).
      await expect(page.locator("h2").first()).toBeVisible();

      await finish(page, ctx, `d ${locale}`);
    });
  });
}
