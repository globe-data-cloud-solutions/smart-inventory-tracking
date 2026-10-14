/**
 * Playwright E2E — resolve receipt discrepancies + transfers page regression
 * (session/2026-10-14-fefo-d2, FEFO Phase D2).
 *
 * Covers, for en + am:
 *   T1  Open-discrepancies panel: count 3, product names, translated reasons, no raw UUID
 *   T2  Panel hidden when the list is empty (T2b: when the call returns 500 — no crash, nothing rendered)
 *   T3  Dialog outcomes per reason: SHORT 3, DAMAGED 1, WRONG_LOT 3 (incl. received-as-lot),
 *       WRONG_LOT without a lot 2 (no received-as-lot)
 *   T4  Written off with an empty note: inline error, no POST
 *   T5  Returned: POST body is exactly {resolution:"RETURNED"} (T5b: plus the typed note);
 *       toast, panel refetch (second call returns []), panel gone
 *   T6  Received as another lot: select lists B and C (not the original A); POST carries the
 *       chosen lot_id; lots call failing -> message + Confirm disabled
 *   T7  409 DISCREPANCY_ALREADY_RESOLVED and 403 DISCREPANCY_OUT_OF_SCOPE: translated, no raw code
 *   T8  Expanded transfer row: RESOLVED rows show the outcome (+ lot number for RECEIVED_AS_LOT)
 *       and no Resolve button; the OPEN row has one
 *   T9  Regression: transfers list with null from/to warehouse names renders (no ReferenceError),
 *       no raw UUID where the warehouse name goes
 *   T10 Role gate (WM sees no Resolve): skipped — see the test.skip reason
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real, using the
 * permanent zz-e2e-ta TA probe account. Every transfer / discrepancy / lots / products / nodes
 * request is answered from the fixtures below by one page.route() handler (installStubs), and
 * that same handler is the catch-all guard: any other non-GET request to an /api/ path is
 * aborted, recorded, and fails the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/discrepancy-resolution.spec.ts --project=chromium --workers=1
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

interface Collected { console: string[]; pageErrors: string[] }

function collectErrors(page: Page): Collected {
  const out: Collected = { console: [], pageErrors: [] };
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
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
  const x = d.transfers.discrepancies;
  return {
    confirm:        d.common.confirm as string,
    lotsToggle:     d.transfers.lots.toggle as string,
    panelTitle: (n: number) => (x.panel_title as string).replace("{count}", String(n)),
    toastResolved:  x.toast_resolved as string,
    resolveButton:  x.resolve as string,
    reason: x.reason as Record<"SHORT" | "DAMAGED" | "WRONG_LOT", string>,
    status: x.status as Record<"OPEN" | "RESOLVED", string>,
    resolution: x.resolution as Record<"WRITTEN_OFF" | "RETURNED" | "ARRIVED_LATE" | "RECEIVED_AS_LOT", string>,
    lotsFailed:     x.lots_failed as string,
    errNoteRequired:   x.errors.RESOLUTION_NOTE_REQUIRED as string,
    errAlreadyResolved: x.errors.DISCREPANCY_ALREADY_RESOLVED as string,
    errOutOfScope:     x.errors.DISCREPANCY_OUT_OF_SCOPE as string,
  };
}
type Strings = ReturnType<typeof localeStrings>;

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const WH_SRC = "11111111-1111-4111-8111-111111111111";
const WH_DST = "22222222-2222-4222-8222-222222222222";
const OTHER_USER = "99999999-9999-4999-8999-999999999999";

const PROD_BATCH = { id: "33333333-3333-4333-8333-333333333301", sku: "SMK-B-01", name: "SMOKE-BATCH" };
const PROD_PLAIN = { id: "33333333-3333-4333-8333-333333333302", sku: "SMK-P-01", name: "SMOKE-PLAIN" };

const LOT_A = { lot_id: "44444444-4444-4444-8444-44444444440a", lot_number: "LOT-A", expiry_date: "2026-11-01" };
const LOT_B = { lot_id: "44444444-4444-4444-8444-44444444440b", lot_number: "LOT-B", expiry_date: "2027-06-30" };
const LOT_C = { lot_id: "44444444-4444-4444-8444-44444444440c", lot_number: "LOT-C", expiry_date: "2027-09-30" };

const T_ID = "aaaa0003-0000-4000-8000-000000000003";
const T_ID_2 = "aaaa0004-0000-4000-8000-000000000004";
const LINE_ID = "55555555-5555-4555-8555-555555555503";

const D_SHORT     = "66666666-6666-4666-8666-666666666601";
const D_DAMAGED   = "66666666-6666-4666-8666-666666666602";
const D_WRONG     = "66666666-6666-4666-8666-666666666603";
const D_WRONG_NIL = "66666666-6666-4666-8666-666666666604";
const D_RES_LOT   = "66666666-6666-4666-8666-666666666611";
const D_RES_OFF   = "66666666-6666-4666-8666-666666666612";
const D_OPEN      = "66666666-6666-4666-8666-666666666613";

interface Discrepancy {
  id: string; transfer_line_id: string; product_id: string;
  lot_id: string | null; lot_number: string | null;
  sent_quantity: string; received_quantity: string; missing_quantity: string;
  reason: string; note: string | null; status: string; created_at: string;
  resolution?: string | null; resolved_lot_id?: string | null; resolved_lot_number?: string | null;
  resolution_note?: string | null; resolved_by?: string | null; resolved_at?: string | null;
}
type ListItem = Discrepancy & {
  transfer_order_id: string; transfer_type: string; from_warehouse_id: string; to_warehouse_id: string;
};

function disc(id: string, product: typeof PROD_BATCH, lot: typeof LOT_A | null, reason: string, extra: Partial<Discrepancy> = {}): Discrepancy {
  return {
    id, transfer_line_id: LINE_ID, product_id: product.id,
    lot_id: lot?.lot_id ?? null, lot_number: lot?.lot_number ?? null,
    sent_quantity: "40.0000", received_quantity: "38.0000", missing_quantity: "2.0000",
    reason, note: "2 cartons crushed", status: "OPEN", created_at: "2026-10-13T09:00:00Z",
    ...extra,
  };
}
const listItem = (d: Discrepancy): ListItem => ({
  ...d, transfer_order_id: T_ID, transfer_type: "PUSH", from_warehouse_id: WH_SRC, to_warehouse_id: WH_DST,
});

const ROW_SHORT     = listItem(disc(D_SHORT, PROD_BATCH, LOT_A, "SHORT"));
const ROW_DAMAGED   = listItem(disc(D_DAMAGED, PROD_PLAIN, null, "DAMAGED"));
const ROW_WRONG     = listItem(disc(D_WRONG, PROD_BATCH, LOT_A, "WRONG_LOT"));
const ROW_WRONG_NIL = listItem(disc(D_WRONG_NIL, PROD_BATCH, null, "WRONG_LOT"));
const THREE_ROWS    = [ROW_SHORT, ROW_DAMAGED, ROW_WRONG];

interface Transfer {
  transfer_id: string; transfer_type: "PUSH"; status: string;
  from_warehouse_id: string; from_warehouse_name: string | null;
  to_warehouse_id: string; to_warehouse_name: string | null;
  lines: Array<{ line_id: string; product_id: string; product_name: string; sku: string; quantity: string; uom: string }>;
  lot_allocations: unknown[];
  created_by: string; created_by_authority_level: number; created_at: string; is_self_approved: boolean;
}

function transfer(id: string, status: string, names: { from: string | null; to: string | null }): Transfer {
  return {
    transfer_id: id, transfer_type: "PUSH", status,
    from_warehouse_id: WH_SRC, from_warehouse_name: names.from,
    to_warehouse_id: WH_DST, to_warehouse_name: names.to,
    lines: [{ line_id: LINE_ID, product_id: PROD_BATCH.id, product_name: PROD_BATCH.name, sku: PROD_BATCH.sku, quantity: "40.0000", uom: "pcs" }],
    lot_allocations: [],
    created_by: OTHER_USER, created_by_authority_level: 1,
    created_at: "2026-10-12T08:00:00Z", is_self_approved: false,
  };
}
const NAMED = { from: "Smoke Source WH", to: "Smoke Dest WH" };
const refOf = (id: string) => id.slice(0, 8).toUpperCase();

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
/** Raw i18n keys and raw backend codes that must never be visible text. */
const RAW_TEXT = /transfers\.discrepancies\.|\berrors\.[A-Z]|\b(DISCREPANCY_[A-Z_]+|RESOLUTION_[A-Z_]+|WRITTEN_OFF|ARRIVED_LATE|RECEIVED_AS_LOT|WRONG_LOT)\b/;

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface StubReply { status: number; data?: unknown; detail?: unknown }

interface Stubs {
  transfers: Transfer[];
  /** Per-transfer discrepancies returned by GET /transfers/{id}. */
  detailDiscrepancies: Record<string, Discrepancy[]>;
  /** GET /transfers/discrepancies?status=OPEN. */
  openList: () => StubReply;
  /** GET /inventory/lots (the dialog's "lot that arrived" choices). */
  lots: () => StubReply;
  resolve: (discrepancyId: string, body: unknown) => StubReply;
  /** false = the node tree is empty, so warehouse names can only come from the transfer rows. */
  nodes: boolean;
  calls: {
    openGets: string[];
    lotGets: string[];
    resolve: Array<{ transferId: string; discrepancyId: string; body: unknown }>;
    unstubbedWrites: string[];
  };
}

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

const errReply = (status: number, code: string): StubReply =>
  ({ status, detail: { code, message: "backend english message" } });

async function installStubs(page: Page, transfers: Transfer[]): Promise<Stubs> {
  const stubs: Stubs = {
    transfers,
    detailDiscrepancies: {},
    openList: () => ({ status: 200, data: [] }),
    lots: () => ({ status: 200, data: [] }),
    resolve: () => ({ status: 200, data: {} }),
    nodes: true,
    calls: { openGets: [], lotGets: [], resolve: [], unstubbedWrites: [] },
  };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");
    const one    = p.match(/^\/api\/v1\/inventory\/transfers\/([0-9a-f-]{36})(\/.+)?$/);

    if (method === "GET") {
      if (p === "/api/v1/inventory/transfers") return reply(route, { status: 200, data: stubs.transfers });
      if (p === "/api/v1/inventory/transfers/discrepancies") {
        stubs.calls.openGets.push(url.search);
        return reply(route, stubs.openList());
      }
      if (one && !one[2]) {
        const t = stubs.transfers.find((x) => x.transfer_id === one[1]);
        return t
          ? reply(route, { status: 200, data: { ...t, discrepancies: stubs.detailDiscrepancies[one[1]] ?? [] } })
          : reply(route, { status: 404, detail: { code: "NOT_FOUND", message: "Transfer not found" } });
      }
      if (one && one[2] === "/approval-info") {
        return reply(route, { status: 200, data: {
          transfer_id: one[1], required_authority_level: 1, required_role_display: "Tenant Admin",
          is_auto_approve: false, can_approve: true, reason: "", current_step: 1, total_steps: 1,
        } });
      }
      if (p === "/api/v1/inventory/lots") {
        stubs.calls.lotGets.push(url.search);
        return reply(route, stubs.lots());
      }
      if (p === "/api/v1/products") {
        return reply(route, { status: 200, data: [
          { ...PROD_BATCH, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z", batch_tracking: true,  expiry_tracking: true  },
          { ...PROD_PLAIN, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z", batch_tracking: false, expiry_tracking: false },
        ] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) {
        const node = (id: string, name: string, level: number, parent: string | null, children: unknown[]) =>
          ({ id, name, address: null, hierarchy_level: level, level_name: null, is_stock_holding: true, parent_node_id: parent, children });
        return reply(route, { status: 200, data: stubs.nodes
          ? [node(WH_SRC, "Smoke Source WH", 1, null, [node(WH_DST, "Smoke Dest WH", 2, WH_SRC, [])])]
          : [] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/inventory/analytics/stock") return reply(route, { status: 200, data: [] });
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    const resolveMatch = p.match(/^\/api\/v1\/inventory\/transfers\/([0-9a-f-]{36})\/discrepancies\/([0-9a-f-]{36})\/resolve$/);
    if (method === "POST" && resolveMatch) {
      const body = req.postDataJSON();
      stubs.calls.resolve.push({ transferId: resolveMatch[1] ?? "", discrepancyId: resolveMatch[2] ?? "", body });
      const r = stubs.resolve(resolveMatch[2] ?? "", body);
      return reply(route, r);
    }

    // Catch-all guard: no other write may leave the browser.
    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

interface Ctx { s: Strings; stubs: Stubs; errors: Collected }

async function openTransfers(
  page: Page,
  locale: Locale,
  setup: (stubs: Stubs) => void = () => {},
  transfers: Transfer[] = [transfer(T_ID, "PARTIALLY_RECEIVED", NAMED)],
): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const errors = collectErrors(page);
  const stubs = await installStubs(page, transfers);
  setup(stubs);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, errors };
}

/**
 * End-of-test checks shared by every scenario: no page error, no unstubbed write, no raw
 * key/code on screen, zero console errors. `expectedErrors` lists console errors the
 * scenario itself provokes on purpose (a stubbed failure the product logs).
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

/** The product logs a failed list / resolve / lots call before the UI shows its own state. */
const HTTP_500_LOG      = /Failed to load resource.*500/;
const PANEL_LIST_LOG    = /\[OpenDiscrepanciesPanel\] list failed/;
const RESOLVE_FAIL_LOG  = /\[resolveDiscrepancy\] failed/;

const panelOf  = (page: Page): Locator => page.getByTestId("open-discrepancies-panel");
const dialogOf = (page: Page): Locator => page.getByTestId("resolve-discrepancy-dialog");

async function openDialog(page: Page, discrepancyId: string): Promise<Locator> {
  await page.getByTestId(`open-discrepancy-resolve-${discrepancyId}`).click();
  const dialog = dialogOf(page);
  await expect(dialog).toBeVisible();
  return dialog;
}

const outcomeRadios = (dialog: Locator): Locator => dialog.locator('input[name="resolve-outcome"]');

for (const locale of ["en", "am"] as const) {
  test.describe(`Discrepancy resolution (${locale})`, () => {
    test(`T1 open discrepancies panel: count, product names, translated reasons, no raw UUID (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => { st.openList = () => ({ status: 200, data: THREE_ROWS }); });
      const { s, stubs } = ctx;

      const panel = panelOf(page);
      await expect(panel).toBeVisible();
      await expect(page.getByTestId("open-discrepancies-toggle")).toHaveText(new RegExp(s.panelTitle(3).replace(/[()]/g, "\\$&")));
      expect(stubs.calls.openGets[0]).toBe("?status=OPEN");

      await expect(panel.locator("tbody tr")).toHaveCount(3);
      const short = panel.getByTestId(`open-discrepancy-${D_SHORT}`);
      const damaged = panel.getByTestId(`open-discrepancy-${D_DAMAGED}`);
      const wrong = panel.getByTestId(`open-discrepancy-${D_WRONG}`);
      await expect(short.getByText(PROD_BATCH.name, { exact: true })).toBeVisible();
      await expect(damaged.getByText(PROD_PLAIN.name, { exact: true })).toBeVisible();
      await expect(wrong.getByText(PROD_BATCH.name, { exact: true })).toBeVisible();
      await expect(short.getByRole("cell", { name: s.reason.SHORT, exact: true })).toBeVisible();
      await expect(damaged.getByRole("cell", { name: s.reason.DAMAGED, exact: true })).toBeVisible();
      await expect(wrong.getByRole("cell", { name: s.reason.WRONG_LOT, exact: true })).toBeVisible();
      await expect(short.getByRole("cell", { name: "LOT-A", exact: true })).toBeVisible();

      expect(await panel.innerText(), "no raw UUID in the panel").not.toMatch(UUID_RE);
      await finish(page, ctx, `T1 ${locale}`);
    });

    test(`T2 panel hidden when the list is empty (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => { st.openList = () => ({ status: 200, data: [] }); });
      await expect.poll(() => ctx.stubs.calls.openGets.length).toBeGreaterThan(0);
      await expect(panelOf(page)).toHaveCount(0);
      await expect(page.getByTestId("open-discrepancies-toggle")).toHaveCount(0);
      await finish(page, ctx, `T2 empty ${locale}`);
    });

    test(`T2b panel hidden when the call returns 500: no crash, nothing rendered (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => { st.openList = () => errReply(500, "INTERNAL_ERROR"); });
      await expect.poll(() => ctx.stubs.calls.openGets.length).toBeGreaterThan(0);
      await expect(panelOf(page)).toHaveCount(0);
      await expect(page.getByTestId("open-discrepancies-toggle")).toHaveCount(0);
      // The rest of the page still renders.
      await expect(page.locator("tr").filter({ hasText: refOf(T_ID) })).toBeVisible();
      await finish(page, ctx, `T2b 500 ${locale}`, [HTTP_500_LOG, PANEL_LIST_LOG]);
    });

    test(`T3 dialog outcomes per reason (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => {
        st.openList = () => ({ status: 200, data: [ROW_SHORT, ROW_DAMAGED, ROW_WRONG, ROW_WRONG_NIL] });
      });
      const { s } = ctx;
      const cases: Array<[string, string, string[]]> = [
        [D_SHORT,     "SHORT",     ["WRITTEN_OFF", "RETURNED", "ARRIVED_LATE"]],
        [D_DAMAGED,   "DAMAGED",   ["WRITTEN_OFF"]],
        [D_WRONG,     "WRONG_LOT (batch)",    ["WRITTEN_OFF", "RETURNED", "RECEIVED_AS_LOT"]],
        [D_WRONG_NIL, "WRONG_LOT (lot null)", ["WRITTEN_OFF", "RETURNED"]],
      ];
      for (const [id, label, expected] of cases) {
        const dialog = await openDialog(page, id);
        await expect(outcomeRadios(dialog), label).toHaveCount(expected.length);
        for (const o of expected) {
          await expect(dialog.getByTestId(`resolve-outcome-${o}`), `${label}: ${o}`).toHaveCount(1);
          await expect(dialog.getByText(s.resolution[o as keyof typeof s.resolution], { exact: true })).toBeVisible();
        }
        const received = dialog.getByTestId("resolve-outcome-RECEIVED_AS_LOT");
        await expect(received, `${label}: received-as-lot`).toHaveCount(expected.includes("RECEIVED_AS_LOT") ? 1 : 0);
        if (!expected.includes("RECEIVED_AS_LOT")) {
          await expect(dialog.getByText(s.resolution.RECEIVED_AS_LOT, { exact: true })).toHaveCount(0);
        }
        await page.keyboard.press("Escape");
        await expect(dialogOf(page)).toHaveCount(0);
      }
      await finish(page, ctx, `T3 ${locale}`);
    });

    test(`T4 written off with an empty note: inline error, no POST (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => { st.openList = () => ({ status: 200, data: [ROW_DAMAGED] }); });
      const { s, stubs } = ctx;

      const dialog = await openDialog(page, D_DAMAGED);
      await expect(dialog.getByTestId("resolve-outcome-WRITTEN_OFF")).toBeChecked();
      await dialog.getByTestId("resolve-confirm").click();
      await expect(dialog.getByTestId("resolve-error")).toHaveText(s.errNoteRequired);
      // Whitespace is still empty.
      await dialog.getByTestId("resolve-note").fill("   ");
      await dialog.getByTestId("resolve-confirm").click();
      await expect(dialog.getByTestId("resolve-error")).toHaveText(s.errNoteRequired);
      expect(stubs.calls.resolve, "no request to .../resolve").toHaveLength(0);
      await expect(dialogOf(page)).toBeVisible();
      await finish(page, ctx, `T4 ${locale}`);
    });

    test(`T5 returned: exact POST body, toast, panel refetches and disappears (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => {
        st.openList = () => ({ status: 200, data: [ROW_SHORT] });
        st.resolve = () => { st.openList = () => ({ status: 200, data: [] }); return { status: 200, data: {} }; };
      });
      const { s, stubs } = ctx;
      await expect(panelOf(page)).toBeVisible();
      const getsBefore = stubs.calls.openGets.length;

      const dialog = await openDialog(page, D_SHORT);
      await dialog.getByTestId("resolve-outcome-RETURNED").check();
      await expect(dialog.getByTestId("resolve-confirm")).toBeEnabled();
      await dialog.getByTestId("resolve-confirm").click();

      await expect.poll(() => stubs.calls.resolve.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.resolve[0]).toEqual({ transferId: T_ID, discrepancyId: D_SHORT, body: { resolution: "RETURNED" } });

      await expect(page.getByText(s.toastResolved)).toBeVisible();
      await expect(dialogOf(page)).toHaveCount(0);
      await expect(panelOf(page)).toHaveCount(0);
      expect(stubs.calls.openGets.length, "the list was refetched").toBeGreaterThan(getsBefore);
      await finish(page, ctx, `T5 ${locale}`);
    });

    test(`T5b returned with a typed note: body carries the trimmed note (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => { st.openList = () => ({ status: 200, data: [ROW_SHORT] }); });
      const { stubs } = ctx;

      const dialog = await openDialog(page, D_SHORT);
      await dialog.getByTestId("resolve-outcome-RETURNED").check();
      await dialog.getByTestId("resolve-note").fill("  sent back on truck 7  ");
      await dialog.getByTestId("resolve-confirm").click();

      await expect.poll(() => stubs.calls.resolve.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.resolve[0]?.body).toEqual({ resolution: "RETURNED", note: "sent back on truck 7" });
      await finish(page, ctx, `T5b ${locale}`);
    });

    test(`T6 received as another lot: select lists B and C only, POST has the chosen lot_id (${locale})`, async ({ page }) => {
      const lotRows = [LOT_A, LOT_B, LOT_C].map((l, i) => ({ ...l, product_id: PROD_BATCH.id, quantity: `${(i + 1) * 10}.0000` }));
      const ctx = await openTransfers(page, locale, (st) => {
        st.openList = () => ({ status: 200, data: [ROW_WRONG] });
        st.lots = () => ({ status: 200, data: lotRows });
      });
      const { stubs } = ctx;

      const dialog = await openDialog(page, D_WRONG);
      await dialog.getByTestId("resolve-outcome-RECEIVED_AS_LOT").check();
      const select = dialog.getByTestId("resolve-lot");
      await expect(select).toBeVisible();

      // Lots of the product at the SOURCE warehouse.
      const q = new URLSearchParams(stubs.calls.lotGets[0] ?? "");
      expect(q.get("product_id")).toBe(PROD_BATCH.id);
      expect(q.get("warehouse_id")).toBe(WH_SRC);

      const options = select.locator("option:not([value=''])");
      await expect(options).toHaveCount(2);
      await expect(options.nth(0)).toContainText("LOT-B");
      await expect(options.nth(1)).toContainText("LOT-C");
      await expect(select.locator(`option[value="${LOT_A.lot_id}"]`)).toHaveCount(0);

      // Confirm stays disabled until a lot is chosen.
      await expect(dialog.getByTestId("resolve-confirm")).toBeDisabled();
      await select.selectOption(LOT_C.lot_id);
      await expect(dialog.getByTestId("resolve-confirm")).toBeEnabled();
      await dialog.getByTestId("resolve-confirm").click();

      await expect.poll(() => stubs.calls.resolve.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.resolve[0]).toEqual({
        transferId: T_ID, discrepancyId: D_WRONG,
        body: { resolution: "RECEIVED_AS_LOT", lot_id: LOT_C.lot_id },
      });
      await finish(page, ctx, `T6 ${locale}`);
    });

    test(`T6b lots call failing: message shown, Confirm disabled, no POST (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => {
        st.openList = () => ({ status: 200, data: [ROW_WRONG] });
        st.lots = () => errReply(500, "INTERNAL_ERROR");
      });
      const { s, stubs } = ctx;

      const dialog = await openDialog(page, D_WRONG);
      await dialog.getByTestId("resolve-outcome-RECEIVED_AS_LOT").check();
      await expect(dialog.getByTestId("resolve-lots-error")).toHaveText(s.lotsFailed);
      await expect(dialog.getByTestId("resolve-lot")).toHaveCount(0);
      await expect(dialog.getByTestId("resolve-confirm")).toBeDisabled();
      expect(stubs.calls.resolve).toHaveLength(0);
      await finish(page, ctx, `T6b ${locale}`, [HTTP_500_LOG]);
    });

    test(`T7 409 already resolved and 403 out of scope: translated, no raw code (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => {
        st.openList = () => ({ status: 200, data: [ROW_DAMAGED] });
        st.resolve = () => errReply(409, "DISCREPANCY_ALREADY_RESOLVED");
      });
      const { s, stubs } = ctx;

      const dialog = await openDialog(page, D_DAMAGED);
      await dialog.getByTestId("resolve-note").fill("crushed in transit");
      await dialog.getByTestId("resolve-confirm").click();
      await expect(dialog.getByTestId("resolve-error")).toHaveText(s.errAlreadyResolved);
      expect(stubs.calls.resolve).toHaveLength(1);

      stubs.resolve = () => errReply(403, "DISCREPANCY_OUT_OF_SCOPE");
      await dialog.getByTestId("resolve-confirm").click();
      await expect(dialog.getByTestId("resolve-error")).toHaveText(s.errOutOfScope);
      expect(stubs.calls.resolve).toHaveLength(2);
      await expect(dialogOf(page)).toBeVisible();

      await finish(page, ctx, `T7 ${locale}`, [RESOLVE_FAIL_LOG]);
    });

    test(`T8 expanded transfer row: resolved rows show the outcome, no Resolve button; open row has one (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, (st) => {
        st.detailDiscrepancies[T_ID] = [
          disc(D_RES_LOT, PROD_BATCH, LOT_A, "WRONG_LOT", {
            status: "RESOLVED", resolution: "RECEIVED_AS_LOT",
            resolved_lot_id: LOT_C.lot_id, resolved_lot_number: LOT_C.lot_number,
            resolution_note: "pallet label mix-up", resolved_by: OTHER_USER, resolved_at: "2026-10-14T07:00:00Z",
          }),
          disc(D_RES_OFF, PROD_PLAIN, null, "DAMAGED", {
            status: "RESOLVED", resolution: "WRITTEN_OFF", resolution_note: "water damage",
            resolved_by: OTHER_USER, resolved_at: "2026-10-14T07:30:00Z",
          }),
          disc(D_OPEN, PROD_BATCH, LOT_B, "SHORT"),
        ];
      });
      const { s } = ctx;

      await page.locator("tr").filter({ hasText: refOf(T_ID) }).getByRole("button", { name: s.lotsToggle }).click();

      // Status cell (7th column) = status label + a sub-line with the outcome (+ lot number).
      const statusCell = (row: Locator): Locator => row.locator("td").nth(6);

      const resolvedLot = page.getByTestId(`discrepancy-row-${D_RES_LOT}`);
      await expect(resolvedLot).toBeVisible();
      await expect(statusCell(resolvedLot)).toContainText(s.status.RESOLVED);
      await expect(statusCell(resolvedLot)).toContainText(s.resolution.RECEIVED_AS_LOT);
      await expect(statusCell(resolvedLot)).toContainText("LOT-C");
      await expect(page.getByTestId(`discrepancy-resolve-${D_RES_LOT}`)).toHaveCount(0);
      await expect(resolvedLot.getByRole("button")).toHaveCount(0);

      const resolvedOff = page.getByTestId(`discrepancy-row-${D_RES_OFF}`);
      await expect(statusCell(resolvedOff)).toContainText(s.status.RESOLVED);
      await expect(statusCell(resolvedOff)).toContainText(s.resolution.WRITTEN_OFF);
      await expect(statusCell(resolvedOff)).not.toContainText("LOT-C");
      await expect(page.getByTestId(`discrepancy-resolve-${D_RES_OFF}`)).toHaveCount(0);
      await expect(resolvedOff.getByRole("button")).toHaveCount(0);

      const open = page.getByTestId(`discrepancy-row-${D_OPEN}`);
      await expect(statusCell(open)).toHaveText(s.status.OPEN);
      await expect(open.getByRole("button")).toHaveCount(1);
      await expect(page.getByTestId(`discrepancy-resolve-${D_OPEN}`)).toHaveText(s.resolveButton);

      await finish(page, ctx, `T8 ${locale}`);
    });

    test(`T9 transfers list with null warehouse names renders, no raw UUID as a name (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(
        page, locale,
        (st) => { st.nodes = false; },
        [transfer(T_ID, "IN_TRANSIT", { from: null, to: null }), transfer(T_ID_2, "APPROVED", { from: null, to: "Smoke Dest WH" })],
      );
      const { stubs } = ctx;
      expect(stubs.nodes).toBe(false);

      const row = page.locator("tr").filter({ hasText: refOf(T_ID) });
      await expect(row).toBeVisible();
      // From and To both fall back to the dash, never the warehouse id.
      await expect(row.getByRole("cell", { name: "—", exact: true })).toHaveCount(2);
      const row2 = page.locator("tr").filter({ hasText: refOf(T_ID_2) });
      await expect(row2.getByRole("cell", { name: "—", exact: true })).toHaveCount(1);
      await expect(row2.getByRole("cell", { name: "Smoke Dest WH", exact: true })).toBeVisible();

      const bodyText = await page.locator("body").innerText();
      expect(bodyText, "no raw UUID anywhere on the page").not.toMatch(UUID_RE);
      expect(bodyText).not.toContain(WH_SRC);
      expect(bodyText).not.toContain(WH_DST);
      expect(ctx.errors.pageErrors.filter((e) => /effectiveWarehouses|before initialization/.test(e))).toEqual([]);
      await finish(page, ctx, `T9 ${locale}`);
    });

    test.skip(
      `T10 role gate: WM sees no Resolve buttons (${locale}) — skipped: the existing specs only patch warehouseId in the client session (TA role), there is no WM session/role stub, and no auth path is invented here`,
      async () => {},
    );
  });
}
