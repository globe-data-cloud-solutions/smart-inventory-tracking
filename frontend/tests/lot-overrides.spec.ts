/**
 * Playwright E2E — near-expiry window setting and the Overrides view on the Lots page
 * (session/2026-10-15-fefo-d3).
 *
 * Covers, for en + am:
 *   W1  TA: window line shows 30 days; edit to 45 -> one PUT {near_expiry_days: 45}; the
 *       lots and expiry-alert requests are made again; the line shows 45
 *   W2  TA: 0 / 366 -> client range error, no PUT
 *   W3  TA: server 422 -> translated range message; server 500 -> translated save error
 *   W4  NM: window line shows, no Edit control; Overrides switch shows
 *   W5  RM (no tenant:configure): window line shows, no Edit control
 *   W6  WM: no Overrides switch; no Edit control
 *   W7  expiry-settings 403: no window line, no error, lots table still renders
 *   O1  Overrides view: summary cards (% and "—" for a null rate, with the hint), table rows
 *       (lot numbers, translated strategy / movement, reason), default 30-day range, no UUID text
 *   O2  Paging: Next requests offset=50, Previous returns to offset=0
 *   O3  Filters: product / strategy / date range are sent, and reset paging
 *   O4  overrides 403 -> access message, no table, no crash; the Lots switch still works
 *
 * NO LIVE WRITES, no SA login. Login (POST /api/v1/auth/token) is the real permanent
 * zz-e2e-ta TA probe account; the role is then patched client-side (helpers/session-role.ts).
 * Every features / lots / expiry-alerts / expiry-settings / overrides / products request is
 * answered from the fixtures below by one page.route() handler (installStubs), which is also the
 * catch-all guard: any write other than the stubbed PUT is aborted, recorded and fails the test.
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/lot-overrides.spec.ts --project=chromium --workers=1
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

function localeStrings(locale: Locale) {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  const l = d.lots;
  return {
    window:        (days: number) => (l.window_label as string).replace("{days}", String(days)),
    rangeError:    l.window_range_error as string,
    saveError:     l.window_save_error as string,
    noAlloc:       l.ov_no_allocations as string,
    accessDenied:  l.ov_access_denied as string,
    empty:         l.ov_empty as string,
    fefo:          l.ov_strategy_fefo as string,
    fifo:          l.ov_strategy_fifo as string,
    transfer:      l.ov_movement_transfer as string,
    issue:         l.ov_movement_issue as string,
    showing:       (from: number, to: number, total: number) =>
      (l.ov_showing as string).replace("{from}", String(from)).replace("{to}", String(to)).replace("{total}", String(total)),
    edit:          d.common.edit as string,
  };
}
type Strings = ReturnType<typeof localeStrings>;

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
function ymd(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

const WH = "11111111-1111-4111-8111-111111111111";
const PRODUCT = { id: "33333333-3333-4333-8333-333333333301", sku: "SMK-MILK-1L", name: "Smoke Milk 1L" };
const PRODUCT_2 = { id: "33333333-3333-4333-8333-333333333302", sku: "SMK-OIL-5L", name: "Smoke Oil 5L" };

const LOT_ROWS = [{
  lot_id: "44444444-4444-4444-8444-44444444440c", lot_number: "LOT-OK",
  product_id: PRODUCT.id, product_name: PRODUCT.name, product_sku: PRODUCT.sku,
  warehouse_id: WH, warehouse_name: "Smoke WH", quantity: "10.0000", expiry_date: ymd(120),
  first_received_at: "2026-09-01T08:00:00Z", is_opening: false, status: "ACTIVE",
  days_to_expiry: 120, expiring_soon: false,
}];

const OV_TOTAL = 120;
const PAGE = 50;

function overrideRow(i: number) {
  return {
    id: `55555555-5555-4555-8555-${String(i).padStart(12, "0")}`,
    created_at: "2026-10-10T09:30:00Z",
    overridden_by: `Manager ${i}`,
    product: PRODUCT,
    warehouse: { id: WH, name: "Smoke WH" },
    strategy: i % 2 === 0 ? "FEFO" : "FIFO",
    movement_type: i % 2 === 0 ? "ISSUE" : "TRANSFER",
    reference_id: `66666666-6666-4666-8666-${String(i).padStart(12, "0")}`,
    requested_qty: "2.0000",
    suggested: [{ lot_id: `77777777-7777-4777-8777-${String(i).padStart(12, "0")}`, lot_number: `S-LOT-${i}`, quantity: "2.0000" }],
    chosen:    [{ lot_id: `88888888-8888-4888-8888-${String(i).padStart(12, "0")}`, lot_number: `C-LOT-${i}`, quantity: "2.0000" }],
    reason: `Customer asked for batch ${i}`,
  };
}

const SUMMARY = {
  date_from: ymd(-29), date_to: ymd(0),
  overall: { decisions: 10, overridden: 2, compliance_rate: 0.8 },
  fefo:    { decisions: 0,  overridden: 0, compliance_rate: null },
  by_movement: {
    TRANSFER: { decisions: 4, overridden: 1, compliance_rate: 0.75 },
    ISSUE:    { decisions: 6, overridden: 1, compliance_rate: 0.8333 },
  },
};

const LOTS_PATH      = "/api/v1/inventory/lots";
const ALERTS_PATH    = "/api/v1/inventory/lots/expiry-alerts";
const SETTINGS_PATH  = "/api/v1/inventory/lots/expiry-settings";
const OVERRIDES_PATH = "/api/v1/inventory/lots/overrides";
const SUMMARY_PATH   = "/api/v1/inventory/lots/overrides/summary";
const FEATURES       = "/api/v1/inventory/features";
const PRODUCTS       = "/api/v1/products";

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface StubReply { status: number; data?: unknown; detail?: unknown }

interface Stubs {
  windowDays: number;
  settingsGet: StubReply | null;       // null -> 200 with windowDays
  settingsPut: StubReply | null;       // null -> 200 echoing the body
  overridesStatus: number;             // 200 | 403
  calls: {
    lotGets: number; alertGets: number;
    puts: Array<Record<string, unknown>>;
    overrideGets: string[]; summaryGets: string[];
    unstubbedWrites: string[];
  };
}

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

const forbidden: StubReply = { status: 403, detail: { code: "RBAC_DENIED", message: "backend-only wording" } };

async function installStubs(page: Page, o: Partial<Pick<Stubs, "settingsGet" | "overridesStatus">> = {}): Promise<Stubs> {
  const stubs: Stubs = {
    windowDays: 30,
    settingsGet: o.settingsGet ?? null,
    settingsPut: null,
    overridesStatus: o.overridesStatus ?? 200,
    calls: { lotGets: 0, alertGets: 0, puts: [], overrideGets: [], summaryGets: [], unstubbedWrites: [] },
  };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === FEATURES) return reply(route, { status: 200, data: { lot_tracking: true } });
      if (p === LOTS_PATH) { stubs.calls.lotGets++; return reply(route, { status: 200, data: LOT_ROWS }); }
      if (p === ALERTS_PATH) {
        stubs.calls.alertGets++;
        return reply(route, { status: 200, data: {
          window_days: stubs.windowDays, counts: { expired: 0, expiring: 0, no_expiry: 0 }, items: [],
        } });
      }
      if (p === SETTINGS_PATH) {
        return reply(route, stubs.settingsGet ?? { status: 200, data: { near_expiry_days: stubs.windowDays } });
      }
      if (p === PRODUCTS) return reply(route, { status: 200, data: [PRODUCT, PRODUCT_2] });
      if (p === SUMMARY_PATH) {
        stubs.calls.summaryGets.push(url.search);
        return stubs.overridesStatus === 200
          ? reply(route, { status: 200, data: SUMMARY })
          : reply(route, forbidden);
      }
      if (p === OVERRIDES_PATH) {
        stubs.calls.overrideGets.push(url.search);
        if (stubs.overridesStatus !== 200) return reply(route, forbidden);
        const offset = Number(url.searchParams.get("offset") ?? "0");
        const n = Math.max(0, Math.min(PAGE, OV_TOTAL - offset));
        return reply(route, { status: 200, data: {
          total: OV_TOTAL, rows: Array.from({ length: n }, (_, k) => overrideRow(offset + k)),
        } });
      }
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    if (method === "PUT" && p === SETTINGS_PATH) {
      const body = req.postDataJSON() as Record<string, unknown>;
      stubs.calls.puts.push(body);
      if (stubs.settingsPut) return reply(route, stubs.settingsPut);
      stubs.windowDays = Number(body.near_expiry_days);
      return reply(route, { status: 200, data: { near_expiry_days: stubs.windowDays } });
    }

    // Catch-all guard: no other write may leave the browser.
    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

interface Ctx { s: Strings; stubs: Stubs; consoleErrors: string[] }

async function open(
  page: Page, locale: Locale, role: string,
  stubOpts: Partial<Pick<Stubs, "settingsGet" | "overridesStatus">> = {},
): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const consoleErrors = collectConsoleErrors(page);
  const stubs = await installStubs(page, stubOpts);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  if (role !== "TA") await asRole(page, role);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/lots`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, consoleErrors };
}

/** Raw i18n keys / backend codes that must never be visible. */
const RAW_KEY = /\b(lots|overrides|common|errors)\.[a-z_]+\b|errors\.[A-Z][A-Z_]+|\bRBAC_DENIED\b/;
const UUID_TEXT = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

async function finish(page: Page, ctx: Ctx, label: string, expectedErrors: RegExp[] = []) {
  expect(ctx.stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  const text = await page.evaluate(() => document.body.innerText);
  expect(text, "no raw i18n key or backend code in the page text").not.toMatch(RAW_KEY);
  expect(text, "no raw UUID in the page text").not.toMatch(UUID_TEXT);

  const unexpected = ctx.consoleErrors.filter((e) => !expectedErrors.some((re) => re.test(e)));
  console.log(`--- ${label} console errors ---`);
  for (const e of unexpected) console.log(e);
  expect(unexpected, `zero console errors (${label})`).toHaveLength(0);
}

const windowText = (page: Page) => page.getByTestId("lots-window-text");
const overridesSwitch = (page: Page) => page.getByTestId("lots-view-overrides");

async function openOverrides(page: Page) {
  await overridesSwitch(page).click();
  await expect(page.getByTestId("ov-view")).toBeVisible();
  await expect(page.getByTestId("ov-table")).toBeVisible();
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Lots page — near-expiry window (${locale})`, () => {
    test(`W1 TA: 30 days -> edit to 45 -> one PUT; lots and alerts refetched (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA");
      const { s, stubs } = ctx;

      await expect(windowText(page)).toHaveText(s.window(30));
      await expect(page.getByTestId("lots-window-edit")).toBeVisible();
      await expect(page.getByTestId("lots-window-input")).toHaveCount(0);

      await page.getByTestId("lots-window-edit").click();
      const input = page.getByTestId("lots-window-input");
      await expect(input).toHaveValue("30");
      await expect(input).toHaveAttribute("min", "1");
      await expect(input).toHaveAttribute("max", "365");

      const lotsBefore = stubs.calls.lotGets;
      const alertsBefore = stubs.calls.alertGets;
      await input.fill("45");
      await page.getByTestId("lots-window-save").click();

      await expect.poll(() => stubs.calls.puts.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.puts[0]).toEqual({ near_expiry_days: 45 });
      await expect(windowText(page)).toHaveText(s.window(45));
      await expect(page.getByTestId("lots-window-input")).toHaveCount(0);
      await expect.poll(() => stubs.calls.lotGets, { timeout: 10_000 }).toBeGreaterThan(lotsBefore);
      await expect.poll(() => stubs.calls.alertGets, { timeout: 10_000 }).toBeGreaterThan(alertsBefore);
      expect(stubs.calls.puts).toHaveLength(1);

      await finish(page, ctx, `W1 (${locale})`);
    });

    test(`W2 TA: 0 and 366 -> client range error, no PUT; Cancel closes the editor (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA");
      const { s, stubs } = ctx;

      await page.getByTestId("lots-window-edit").click();
      for (const bad of ["0", "366", ""]) {
        await page.getByTestId("lots-window-input").fill(bad);
        await page.getByTestId("lots-window-save").click();
        await expect(page.getByTestId("lots-window-error")).toHaveText(s.rangeError);
      }
      expect(stubs.calls.puts, "no PUT for an out-of-range value").toHaveLength(0);

      await page.getByTestId("lots-window-cancel").click();
      await expect(page.getByTestId("lots-window-input")).toHaveCount(0);
      await expect(page.getByTestId("lots-window-error")).toHaveCount(0);
      await expect(windowText(page)).toHaveText(s.window(30));

      await finish(page, ctx, `W2 (${locale})`);
    });

    test(`W3 TA: server 422 and 500 -> translated messages, never backend text (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA");
      const { s, stubs } = ctx;

      await page.getByTestId("lots-window-edit").click();
      await page.getByTestId("lots-window-input").fill("45");

      stubs.settingsPut = { status: 422, detail: [{ msg: "backend-only wording", type: "value_error" }] };
      await page.getByTestId("lots-window-save").click();
      await expect(page.getByTestId("lots-window-error")).toHaveText(s.rangeError, { timeout: 10_000 });
      await expect(page.getByText("backend-only wording")).toHaveCount(0);

      stubs.settingsPut = { status: 500, detail: { code: "INTERNAL_ERROR", message: "backend-only wording" } };
      await page.getByTestId("lots-window-save").click();
      await expect(page.getByTestId("lots-window-error")).toHaveText(s.saveError, { timeout: 10_000 });
      await expect(page.getByText("backend-only wording")).toHaveCount(0);
      await expect(page.getByTestId("lots-window-input")).toBeVisible();
      expect(stubs.calls.puts).toHaveLength(2);

      await finish(page, ctx, `W3 (${locale})`, [/422|500/]);
    });

    test(`W4 NM: window line, no Edit control, Overrides switch shows (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "NM");
      await expect(windowText(page)).toHaveText(ctx.s.window(30));
      await expect(page.getByTestId("lots-window-edit")).toHaveCount(0);
      await expect(overridesSwitch(page)).toBeVisible();
      await finish(page, ctx, `W4 (${locale})`);
    });

    test(`W5 RM (no tenant:configure): window line, no Edit control (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "RM");
      await expect(windowText(page)).toHaveText(ctx.s.window(30));
      await expect(page.getByTestId("lots-window-edit")).toHaveCount(0);
      await finish(page, ctx, `W5 (${locale})`);
    });

    test(`W6 WM: no Overrides switch, no Edit control (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "WM");
      await expect(windowText(page)).toHaveText(ctx.s.window(30));
      await expect(page.getByTestId("lots-window-edit")).toHaveCount(0);
      await expect(page.getByTestId("lots-row-LOT-OK")).toBeVisible();
      await expect(overridesSwitch(page)).toHaveCount(0);
      await expect(page.getByTestId("lots-view-lots")).toHaveCount(0);
      await finish(page, ctx, `W6 (${locale})`);
    });

    test(`W7 expiry-settings 403: no window line and no error; the table renders (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA", { settingsGet: forbidden });
      await expect(page.getByTestId("lots-row-LOT-OK")).toBeVisible();
      await expect(page.getByTestId("lots-window")).toHaveCount(0);
      await expect(page.getByTestId("lots-window-error")).toHaveCount(0);
      await finish(page, ctx, `W7 (${locale})`, [/403/]);
    });
  });

  test.describe(`Lots page — Overrides view (${locale})`, () => {
    test(`O1 summary cards, table rows, default 30-day range, no UUID text (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA");
      const { s, stubs } = ctx;
      await openOverrides(page);

      await expect(page.getByTestId("ov-card-overall-value")).toHaveText("80%");
      await expect(page.getByTestId("ov-card-fefo-value")).toHaveText("—");
      await expect(page.getByTestId("ov-card-fefo-hint")).toHaveText(s.noAlloc);
      await expect(page.getByTestId("ov-card-overall-hint")).toHaveCount(0);
      await expect(page.getByTestId("ov-card-decisions-value")).toHaveText("10");
      await expect(page.getByTestId("ov-card-overrides-value")).toHaveText("2");

      await expect(page.getByTestId("ov-row")).toHaveCount(PAGE);
      const first = page.getByTestId("ov-row").nth(0);     // i = 0: FEFO, ISSUE
      await expect(first).toContainText("S-LOT-0 × 2");
      await expect(first).toContainText("C-LOT-0 × 2");
      await expect(first).toContainText("Smoke Milk 1L");
      await expect(first).toContainText("SMK-MILK-1L");
      await expect(first).toContainText("Smoke WH");
      await expect(first).toContainText("Manager 0");
      await expect(first).toContainText("Customer asked for batch 0");
      await expect(first.getByTestId("ov-cell-strategy")).toHaveText(s.fefo);
      await expect(first.getByTestId("ov-cell-movement")).toHaveText(s.issue);
      const second = page.getByTestId("ov-row").nth(1);    // i = 1: FIFO, TRANSFER
      await expect(second.getByTestId("ov-cell-strategy")).toHaveText(s.fifo);
      await expect(second.getByTestId("ov-cell-movement")).toHaveText(s.transfer);
      await expect(page.getByTestId("ov-range")).toHaveText(s.showing(1, PAGE, OV_TOTAL));

      // Default period: the 30 calendar days ending today; no warehouse for a TA.
      for (const q of [stubs.calls.overrideGets[0]!, stubs.calls.summaryGets[0]!]) {
        const params = new URLSearchParams(q);
        expect(params.get("date_from")).toBe(ymd(-29));
        expect(params.get("date_to")).toBe(ymd(0));
        expect(params.has("warehouse_id")).toBe(false);
      }
      const list = new URLSearchParams(stubs.calls.overrideGets[0]!);
      expect(list.get("limit")).toBe("50");
      expect(list.get("offset")).toBe("0");

      await finish(page, ctx, `O1 (${locale})`);
    });

    test(`O2 paging: Next requests offset=50, Previous returns to offset=0 (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA");
      const { s, stubs } = ctx;
      await openOverrides(page);

      await expect(page.getByTestId("ov-prev")).toBeDisabled();
      await expect(page.getByTestId("ov-next")).toBeEnabled();

      await page.getByTestId("ov-next").click();
      await expect.poll(
        () => stubs.calls.overrideGets.some((q) => new URLSearchParams(q).get("offset") === "50"),
        { timeout: 10_000 },
      ).toBe(true);
      await expect(page.getByTestId("ov-range")).toHaveText(s.showing(51, 100, OV_TOTAL));
      await expect(page.getByTestId("ov-row").nth(0)).toContainText("S-LOT-50 × 2");
      await expect(page.getByTestId("ov-prev")).toBeEnabled();

      await page.getByTestId("ov-next").click();
      await expect(page.getByTestId("ov-range")).toHaveText(s.showing(101, 120, OV_TOTAL));
      await expect(page.getByTestId("ov-row")).toHaveCount(20);
      await expect(page.getByTestId("ov-next")).toBeDisabled();

      await page.getByTestId("ov-prev").click();
      await page.getByTestId("ov-prev").click();
      await expect(page.getByTestId("ov-range")).toHaveText(s.showing(1, PAGE, OV_TOTAL));
      await expect(page.getByTestId("ov-row").nth(0)).toContainText("S-LOT-0 × 2");

      await finish(page, ctx, `O2 (${locale})`);
    });

    test(`O3 filters: product / strategy / date range are sent and reset paging (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA");
      const { stubs } = ctx;
      await openOverrides(page);

      await page.getByTestId("ov-next").click();
      await expect(page.getByTestId("ov-row").nth(0)).toContainText("S-LOT-50 × 2");

      await page.getByTestId("ov-product").selectOption(PRODUCT_2.id);
      await expect.poll(
        () => stubs.calls.overrideGets.some((q) => {
          const p = new URLSearchParams(q);
          return p.get("product_id") === PRODUCT_2.id && p.get("offset") === "0";
        }),
        { timeout: 10_000 },
      ).toBe(true);
      await expect(page.getByTestId("ov-row").nth(0)).toContainText("S-LOT-0 × 2");

      await page.getByTestId("ov-strategy").selectOption("FEFO");
      await expect.poll(
        () => stubs.calls.overrideGets.some((q) => new URLSearchParams(q).get("strategy") === "FEFO"),
        { timeout: 10_000 },
      ).toBe(true);

      await page.getByTestId("ov-from").fill(ymd(-10));
      await expect.poll(
        () => stubs.calls.summaryGets.some((q) => new URLSearchParams(q).get("date_from") === ymd(-10)),
        { timeout: 10_000 },
      ).toBe(true);
      await expect.poll(
        () => stubs.calls.overrideGets.some((q) => new URLSearchParams(q).get("date_from") === ymd(-10)),
        { timeout: 10_000 },
      ).toBe(true);

      // A from-date after the to-date is a client error and sends no request.
      const before = stubs.calls.overrideGets.length;
      await page.getByTestId("ov-from").fill(ymd(1));
      await expect(page.getByTestId("ov-range-error")).toBeVisible();
      await page.waitForTimeout(500);
      expect(stubs.calls.overrideGets.length).toBe(before);

      await finish(page, ctx, `O3 (${locale})`);
    });

    test(`O4 overrides 403 -> access message, no table, no crash; Lots switch returns (${locale})`, async ({ page }) => {
      const ctx = await open(page, locale, "TA", { overridesStatus: 403 });
      const { s } = ctx;

      await overridesSwitch(page).click();
      await expect(page.getByTestId("ov-denied")).toHaveText(s.accessDenied, { timeout: 10_000 });
      await expect(page.getByTestId("ov-table")).toHaveCount(0);
      await expect(page.getByTestId("ov-summary")).toHaveCount(0);
      await expect(page.getByTestId("ov-load-error")).toHaveCount(0);
      await expect(page.getByText("backend-only wording")).toHaveCount(0);

      await page.getByTestId("lots-view-lots").click();
      await expect(page.getByTestId("lots-row-LOT-OK")).toBeVisible();

      await finish(page, ctx, `O4 (${locale})`, [/403/]);
    });
  });
}
