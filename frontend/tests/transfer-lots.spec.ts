/**
 * Playwright E2E — lot-aware transfer screens (session/2026-10-13-fefo-c2).
 *
 * Covers, for en + am:
 *   Receive (IN_TRANSIT)        R1 per-lot rows, short receipt with reason + note,
 *                                  exact POST body, toast, discrepancies in the expanded row
 *                               R2 received > sent: inline error, no POST
 *                               R3 422 RECEIPT_LINES_MISMATCH: translated, no raw code
 *                               R4 only Receive is offered (no "Partially Received")
 *                               R5 non-batch line: one row, lot_id null
 *   Approve (PENDING_APPROVAL)  A1 non-final step: plain PATCH, no picker
 *                               A2 final step: suggested split, unchanged -> PATCH
 *                               A3 Change lots: sum error, reason required, POST /approve body
 *                               A4 403 OVERRIDE_NOT_PERMITTED: translated
 *                               A5 422 INSUFFICIENT_STOCK: usable + expired shown
 *   Request panel preview       P1 strategy + likely lots + "nothing is reserved" note
 *                               P2 shortfall warning + expired note
 *                               P3 non-batch product: no info box
 *                               P4 preview 500: no info box, submit still enabled
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real,
 * using the permanent zz-e2e-ta TA probe account. Every transfer / approval /
 * preview / lots / products / warehouses request is answered from the fixed
 * fixtures below by one page.route() handler (installStubs), and that same
 * handler is the catch-all guard: any other non-GET request to an /api/ path
 * is aborted, recorded, and fails the test in finish().
 *
 * The TA probe has no warehouse_id in its JWT, and Receive is offered to the
 * destination warehouse only — so the Receive scenarios patch warehouseId in
 * the browser's localStorage session (client-side only, same approach as
 * lot-receive.spec.ts) to the fixture destination warehouse.
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/transfer-lots.spec.ts --project=chromium
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type Locator, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });
// One worker for this file: 28 parallel real logins (plus each page's real
// tenant / plan / contract GETs) make the local gateway answer 503, which then
// shows up as console errors in otherwise passing scenarios.
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
  const tr = d.transfers;
  return {
    confirm:           d.common.confirm as string,
    cancel:            d.common.cancel as string,
    partialReceive:    tr.partial_receive as string,
    // receive form
    receiveAction:     tr.receive.action as string,
    receiveTitle: (ref: string) => (tr.receive.title as string).replace("{ref}", ref),
    receiveSubmit:     tr.receive.submit as string,
    errRange: (sent: string) => (tr.receive.err_range as string).replace("{sent}", sent),
    toastOne:          tr.receive.toast_discrepancy_one as string,
    lotsToggle:        tr.lots.toggle as string,
    discTitle:         tr.discrepancies.title as string,
    reasonShort:       tr.discrepancies.reason.SHORT as string,
    statusOpen:        tr.discrepancies.status.OPEN as string,
    errReasonRequired: d.errors.RECEIPT_REASON_REQUIRED as string,
    errLinesMismatch:  d.errors.RECEIPT_LINES_MISMATCH as string,
    // approve panel
    approveAction:     tr.action.approve as string,
    approveTitle: (ref: string) => (tr.approve.title as string).replace("{ref}", ref),
    approveSubmit:     tr.approve.submit as string,
    changeLots:        tr.approve.change_lots as string,
    reasonLabel:       tr.approve.reason_label as string,
    errTotal: (chosen: string, required: string) =>
      (tr.approve.err_total as string).replace("{chosen}", chosen).replace("{required}", required),
    stockDetail: (usable: string, expired: string) =>
      (tr.approve.stock_detail as string).replace("{usable}", usable).replace("{expired}", expired),
    errOverrideReason: d.errors.OVERRIDE_REASON_REQUIRED as string,
    errOverrideDenied: d.errors.OVERRIDE_NOT_PERMITTED as string,
    errInsufficient:   d.errors.INSUFFICIENT_STOCK as string,
    // request panel preview
    newTransferButton: `+ ${d.inventory.transfer.title as string}`,
    panelTitle:        d.transfer_panel.title as string,
    selectProduct:     d.receive_panel.select_product as string,
    createSubmit:      d.inventory.transfer.submit as string,
    previewStrategyFefo: (tr.preview.strategy as string).replace("{strategy}", tr.preview.strategies.FEFO as string),
    previewNote:       tr.preview.note as string,
    shortfall: (qty: string) => (tr.preview.shortfall as string).replace("{qty}", qty),
    expiredSkipped: (qty: string) => (tr.preview.expired_skipped as string).replace("{qty}", qty),
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
const LOT_X = { lot_id: "44444444-4444-4444-8444-44444444440c", lot_number: "LOT-X", expiry_date: "2026-01-31" };

interface Line { line_id: string; product_id: string; product_name: string; sku: string; quantity: string; uom: string }
interface Allocation { line_id: string; product_id: string; lot_id: string; lot_number: string; expiry_date: string; quantity: string; is_override: boolean }
interface Transfer {
  transfer_id: string; transfer_type: "PUSH"; status: string;
  from_warehouse_id: string; from_warehouse_name: string;
  to_warehouse_id: string; to_warehouse_name: string;
  lines: Line[]; lot_allocations?: Allocation[];
  created_by: string; created_by_authority_level: number; created_at: string; is_self_approved: boolean;
}

function line(lineId: string, product: typeof PROD_BATCH, quantity: number): Line {
  return { line_id: lineId, product_id: product.id, product_name: product.name, sku: product.sku, quantity: `${quantity}.0000`, uom: "pcs" };
}
function allocation(lineId: string, lot: typeof LOT_A, quantity: number): Allocation {
  return { line_id: lineId, product_id: PROD_BATCH.id, ...lot, quantity: `${quantity}.0000`, is_override: false };
}
function transfer(id: string, status: string, lines: Line[], allocations?: Allocation[]): Transfer {
  return {
    transfer_id: id, transfer_type: "PUSH", status,
    from_warehouse_id: WH_SRC, from_warehouse_name: "Smoke Source WH",
    to_warehouse_id: WH_DST, to_warehouse_name: "Smoke Dest WH",
    lines, ...(allocations ? { lot_allocations: allocations } : {}),
    created_by: OTHER_USER, created_by_authority_level: 1,
    created_at: "2026-10-12T08:00:00Z", is_self_approved: false,
  };
}
const refOf = (id: string) => id.slice(0, 8).toUpperCase();

const LINE_RB = "55555555-5555-4555-8555-555555555501";
const LINE_RP = "55555555-5555-4555-8555-555555555502";
const LINE_PR = "55555555-5555-4555-8555-555555555503";
const LINE_70 = "55555555-5555-4555-8555-555555555570";
const LINE_50 = "55555555-5555-4555-8555-555555555550";

const T_RECV_BATCH = "aaaa0001-0000-4000-8000-000000000001";
const T_RECV_PLAIN = "aaaa0002-0000-4000-8000-000000000002";
const T_PARTIAL    = "aaaa0003-0000-4000-8000-000000000003";
const T_APPR_70    = "bbbb0070-0000-4000-8000-000000000070";
const T_APPR_50    = "bbbb0050-0000-4000-8000-000000000050";

const batchAllocations = (lineId: string) => [allocation(lineId, LOT_A, 30), allocation(lineId, LOT_B, 40)];

function receiveTransfers(): Transfer[] {
  return [
    transfer(T_RECV_BATCH, "IN_TRANSIT", [line(LINE_RB, PROD_BATCH, 70)], batchAllocations(LINE_RB)),
    transfer(T_RECV_PLAIN, "IN_TRANSIT", [line(LINE_RP, PROD_PLAIN, 25)], []),
    transfer(T_PARTIAL, "PARTIALLY_RECEIVED", [line(LINE_PR, PROD_BATCH, 70)], batchAllocations(LINE_PR)),
  ];
}
function approveTransfers(): Transfer[] {
  return [
    transfer(T_APPR_70, "PENDING_APPROVAL", [line(LINE_70, PROD_BATCH, 70)]),
    transfer(T_APPR_50, "PENDING_APPROVAL", [line(LINE_50, PROD_BATCH, 50)]),
  ];
}

const DISCREPANCY_NOTE = "2 cartons crushed";
const LOT_B_DISCREPANCY = {
  id: "66666666-6666-4666-8666-666666666601", transfer_line_id: LINE_RB, product_id: PROD_BATCH.id,
  lot_id: LOT_B.lot_id, lot_number: LOT_B.lot_number,
  sent_quantity: "40.0000", received_quantity: "38.0000", missing_quantity: "2.0000",
  reason: "SHORT", note: DISCREPANCY_NOTE, status: "OPEN", created_at: "2026-10-13T09:00:00Z",
};

interface Preview {
  strategy: string | null; strategy_source: string;
  lines: Array<typeof LOT_A & { quantity: string }>;
  shortfall: string; expired_skipped: Array<typeof LOT_A & { quantity: string }>; available_total: string;
}
/** FEFO split of `quantity` over LOT-A (30, expires first) then LOT-B (40). */
function fefoPreview(quantity: number): Preview {
  const fromA = Math.min(quantity, 30);
  const fromB = Math.min(quantity - fromA, 40);
  const lines = [{ ...LOT_A, quantity: `${fromA}.0000` }];
  if (fromB > 0) lines.push({ ...LOT_B, quantity: `${fromB}.0000` });
  return {
    strategy: "FEFO", strategy_source: "TENANT_DEFAULT", lines,
    shortfall: `${quantity - fromA - fromB}.0000`, expired_skipped: [], available_total: "70.0000",
  };
}
const PLAIN_PREVIEW: Preview = {
  strategy: null, strategy_source: "NOT_BATCH_TRACKED", lines: [],
  shortfall: "0.0000", expired_skipped: [], available_total: "0.0000",
};
/** 50 requested, only LOT-A 30 + LOT-B 10 usable, LOT-X (5) expired and skipped. */
const SHORTFALL_PREVIEW: Preview = {
  strategy: "FEFO", strategy_source: "TENANT_DEFAULT",
  lines: [{ ...LOT_A, quantity: "30.0000" }, { ...LOT_B, quantity: "10.0000" }],
  shortfall: "10.0000", expired_skipped: [{ ...LOT_X, quantity: "5.0000" }], available_total: "40.0000",
};

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface StubReply { status: number; data?: unknown; detail?: unknown }

interface Stubs {
  transfers: Transfer[];
  discrepancies: Record<string, unknown[]>;
  /** approval-info step per transfer; default is the final step (1/1). */
  steps: Record<string, { current_step: number; total_steps: number }>;
  preview: (productId: string, quantity: number) => StubReply;
  receive: (id: string, body: unknown) => StubReply;
  approve: (id: string, body: unknown) => StubReply;
  calls: {
    receive: unknown[];
    patch: Array<{ id: string; body: unknown }>;
    approve: Array<{ id: string; body: unknown }>;
    preview: number;
    unstubbedWrites: string[];
  };
}

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

function setStatus(stubs: Stubs, id: string, status: string) {
  const t = stubs.transfers.find((x) => x.transfer_id === id);
  if (t) t.status = status;
}

/**
 * One handler for every /api/ request: fixtures for the transfer screens,
 * real backend for every other GET and for the login POST, and a hard stop
 * (abort + record) for any other write.
 */
async function installStubs(page: Page, transfers: Transfer[]): Promise<Stubs> {
  const stubs: Stubs = {
    transfers,
    discrepancies: {},
    steps: {},
    preview: (productId, quantity) =>
      ({ status: 200, data: productId === PROD_BATCH.id ? fefoPreview(quantity) : PLAIN_PREVIEW }),
    receive: () => ({ status: 200, data: {} }),
    approve: () => ({ status: 200, data: {} }),
    calls: { receive: [], patch: [], approve: [], preview: 0, unstubbedWrites: [] },
  };

  const detailOf = (id: string) => {
    const t = stubs.transfers.find((x) => x.transfer_id === id);
    return t ? { ...t, discrepancies: stubs.discrepancies[id] ?? [] } : null;
  };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");
    const one    = p.match(/^\/api\/v1\/inventory\/transfers\/([0-9a-f-]{36})(\/[a-z-]+)?$/);

    if (method === "GET") {
      if (p === "/api/v1/inventory/transfers") return reply(route, { status: 200, data: stubs.transfers });
      if (one && !one[2]) {
        const detail = detailOf(one[1]);
        return detail
          ? reply(route, { status: 200, data: detail })
          : reply(route, { status: 404, detail: { code: "NOT_FOUND", message: "Transfer not found" } });
      }
      if (one && one[2] === "/approval-info") {
        return reply(route, { status: 200, data: {
          transfer_id: one[1], required_authority_level: 1, required_role_display: "Tenant Admin",
          is_auto_approve: false, can_approve: true, reason: "",
          ...(stubs.steps[one[1]] ?? { current_step: 1, total_steps: 1 }),
        } });
      }
      if (p === "/api/v1/inventory/dispatch/preview") {
        stubs.calls.preview += 1;
        return reply(route, stubs.preview(url.searchParams.get("product_id") ?? "", Number(url.searchParams.get("quantity"))));
      }
      if (p === "/api/v1/inventory/lots") {
        return reply(route, { status: 200, data: [
          { ...LOT_A, quantity: "30.0000" },
          { ...LOT_B, quantity: "40.0000" },
        ] });
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
        return reply(route, { status: 200, data: [
          node(WH_SRC, "Smoke Source WH", 1, null, [node(WH_DST, "Smoke Dest WH", 2, WH_SRC, [])]),
        ] });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/inventory/analytics/stock") return reply(route, { status: 200, data: [] });
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    if (method === "POST" && one && one[2] === "/receive") {
      const body = req.postDataJSON();
      stubs.calls.receive.push(body);
      const r = stubs.receive(one[1], body);
      if (r.status < 400) setStatus(stubs, one[1], "RECEIVED");
      return reply(route, r.status < 400 ? { status: r.status, data: detailOf(one[1]) } : r);
    }
    if (method === "POST" && one && one[2] === "/approve") {
      const body = req.postDataJSON();
      stubs.calls.approve.push({ id: one[1], body });
      const r = stubs.approve(one[1], body);
      if (r.status < 400) setStatus(stubs, one[1], "APPROVED");
      return reply(route, r);
    }
    if (method === "PATCH" && one && !one[2]) {
      const body = req.postDataJSON() as { next_status: string };
      stubs.calls.patch.push({ id: one[1], body });
      setStatus(stubs, one[1], body.next_status);
      return reply(route, { status: 200, data: detailOf(one[1]) });
    }

    // Catch-all guard: no other write may leave the browser.
    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

/** Patch the client-side session (post real login) so the TA probe acts for
 * the fixture destination warehouse. No backend write; localStorage only. */
async function fakeDestinationWarehouse(page: Page) {
  await page.evaluate((whId) => {
    const raw = window.localStorage.getItem("smart_demo_session");
    if (!raw) return;
    const session = JSON.parse(raw) as Record<string, unknown>;
    session.warehouseId = whId;
    session.warehouseName = "Smoke Dest WH";
    window.localStorage.setItem("smart_demo_session", JSON.stringify(session));
  }, WH_DST);
}

interface Ctx { s: Strings; stubs: Stubs; consoleErrors: string[] }

async function openTransfers(
  page: Page,
  locale: Locale,
  transfers: Transfer[],
  opts: { asDestination?: boolean } = {},
): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const consoleErrors = collectConsoleErrors(page);
  const stubs = await installStubs(page, transfers);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  if (opts.asDestination) await fakeDestinationWarehouse(page);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, consoleErrors };
}

/** Raw i18n keys of the C2 screens (dotted names) that must never be visible. */
const RAW_KEY = /transfers\.(receive|lots|discrepancies|preview|approve)\.[a-z_]+|errors\.[A-Z][A-Z_]+/;

/**
 * End-of-test checks shared by every scenario: no unstubbed write, no raw
 * i18n key, zero console errors. `expectedErrors` lists console errors the
 * scenario itself provokes on purpose (a stubbed failure the product logs).
 */
async function finish(page: Page, ctx: Ctx, label: string, expectedErrors: RegExp[] = []) {
  expect(ctx.stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  await expect(page.getByText(RAW_KEY)).toHaveCount(0);

  const unexpected = ctx.consoleErrors.filter((e) => !expectedErrors.some((re) => re.test(e)));
  console.log(`--- ${label} console errors ---`);
  for (const e of unexpected) console.log(e);
  expect(unexpected, `zero console errors (${label})`).toHaveLength(0);
}

/** doTransition logs a failed approval with console.error before the panel shows it. */
const APPROVE_FAILURE_LOG = /\[doTransition\] transition failed/;
/** The browser's own line for the stubbed 500 (the template filter only drops 4xx). */
const PREVIEW_500_LOG = /Failed to load resource.*500/;

const listRow = (page: Page, transferId: string): Locator =>
  page.locator("tr").filter({ hasText: refOf(transferId) });

/** The centred modal (receive form / lot picker) whose heading is `title`. */
const modal = (page: Page, title: string): Locator =>
  page.locator("div.fixed.shadow-2xl").filter({ hasText: title });

async function openReceive(page: Page, s: Strings, transferId: string): Promise<Locator> {
  await listRow(page, transferId).getByRole("button", { name: s.receiveAction, exact: true }).click();
  const panel = modal(page, s.receiveTitle(refOf(transferId)));
  await expect(panel).toBeVisible();
  return panel;
}

async function openLotPicker(page: Page, s: Strings, transferId: string): Promise<Locator> {
  await listRow(page, transferId).getByRole("button", { name: s.approveAction, exact: true }).click();
  const panel = modal(page, s.approveTitle(refOf(transferId)));
  await expect(panel).toBeVisible();
  return panel;
}

const lotRow = (panel: Locator, lotNumber: string): Locator =>
  panel.locator("tbody tr").filter({ hasText: lotNumber });

/** Opens the picker on the 50-unit transfer and enters LOT-A 10 + LOT-B 40 (suggested: 30 + 20). */
async function chooseOverrideLots(page: Page, s: Strings): Promise<Locator> {
  const panel = await openLotPicker(page, s, T_APPR_50);
  await panel.getByRole("button", { name: s.changeLots, exact: true }).click();
  await lotRow(panel, "LOT-A").getByRole("spinbutton").fill("10");
  await lotRow(panel, "LOT-B").getByRole("spinbutton").fill("40");
  return panel;
}

const OVERRIDE_REASON = "LOT-B pallet is at the dock door";
const OVERRIDE_BODY = {
  lot_selections: [{
    line_id: LINE_50,
    lots: [{ lot_id: LOT_A.lot_id, quantity: 10 }, { lot_id: LOT_B.lot_id, quantity: 40 }],
  }],
  override_reason: OVERRIDE_REASON,
};

async function openRequestPanel(page: Page, s: Strings): Promise<Locator> {
  await page.getByRole("button", { name: s.newTransferButton, exact: true }).click();
  const panel = page.locator("div.fixed.top-0.right-0.translate-x-0").filter({ hasText: s.panelTitle });
  await expect(panel).toBeVisible();
  return panel;
}

/** Product + source warehouse + quantity 50 on the request panel. */
async function fillRequest(panel: Locator, s: Strings, productName: string) {
  await panel.getByRole("button").filter({ hasText: s.selectProduct }).click();
  await panel.getByText(productName, { exact: true }).click();
  await panel.locator("select").nth(1).selectOption(WH_SRC);
  await panel.getByPlaceholder("e.g. 1455").fill("50");
}

const previewBox = (panel: Locator): Locator => panel.locator("div.bg-blue-50");
const previewLot = (scope: Locator, lotNumber: string): Locator =>
  scope.locator("li").filter({ hasText: lotNumber }).locator("> span").last();

for (const locale of ["en", "am"] as const) {
  test.describe(`Transfer receive — per-lot form (${locale})`, () => {
    test(`R1 batch line: one row per lot, short receipt needs a reason, exact POST body, discrepancy shown (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, receiveTransfers(), { asDestination: true });
      const { s, stubs } = ctx;
      stubs.receive = (id) => { stubs.discrepancies[id] = [LOT_B_DISCREPANCY]; return { status: 200 }; };

      const panel = await openReceive(page, s, T_RECV_BATCH);
      await expect(panel.locator("tbody tr")).toHaveCount(2);
      for (const [lot, sent] of [["LOT-A", "30"], ["LOT-B", "40"]] as const) {
        await expect(lotRow(panel, lot).locator("td").nth(3)).toHaveText(sent);
        await expect(lotRow(panel, lot).getByRole("spinbutton")).toHaveValue(sent);
      }
      await expect(panel.getByRole("combobox")).toHaveCount(0);

      // Short receipt on LOT-B: a reason is required before anything is sent —
      // the row shows why and the submit button stays disabled until it is chosen.
      const rowB = lotRow(panel, "LOT-B");
      const submit = panel.getByRole("button", { name: s.receiveSubmit, exact: true });
      await expect(submit).toBeEnabled();
      await rowB.getByRole("spinbutton").fill("38");
      const reason = rowB.getByRole("combobox");
      await expect(reason).toHaveAttribute("required", "");
      await expect(rowB.getByText(s.errReasonRequired)).toBeVisible();
      await expect(submit).toBeDisabled();
      expect(stubs.calls.receive).toHaveLength(0);

      await expect(reason.locator('option[value="SHORT"]')).toHaveText(s.reasonShort);
      await reason.selectOption("SHORT");
      await rowB.getByRole("textbox").fill(DISCREPANCY_NOTE);
      await submit.click();

      await expect.poll(() => stubs.calls.receive.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.receive[0]).toEqual({
        lines: [
          { line_id: LINE_RB, lot_id: LOT_A.lot_id, received_quantity: 30, reason: null, note: null },
          { line_id: LINE_RB, lot_id: LOT_B.lot_id, received_quantity: 38, reason: "SHORT", note: DISCREPANCY_NOTE },
        ],
      });

      await expect(page.getByText(s.toastOne)).toBeVisible();
      await expect(panel).toHaveCount(0);

      await listRow(page, T_RECV_BATCH).getByRole("button", { name: s.lotsToggle }).click();
      const details = page.locator("tr").filter({ hasText: s.discTitle });
      await expect(details.getByText(s.discTitle, { exact: true })).toBeVisible();
      await expect(details.getByRole("cell", { name: s.reasonShort, exact: true })).toBeVisible();
      await expect(details.getByRole("cell", { name: s.statusOpen, exact: true })).toBeVisible();
      await expect(details.getByRole("cell", { name: DISCREPANCY_NOTE, exact: true })).toBeVisible();

      await finish(page, ctx, `R1 (${locale})`);
    });

    test(`R2 received more than sent: inline error, nothing is posted (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, receiveTransfers(), { asDestination: true });
      const { s, stubs } = ctx;

      const panel = await openReceive(page, s, T_RECV_BATCH);
      const rowA = lotRow(panel, "LOT-A");
      await rowA.getByRole("spinbutton").fill("31");
      await expect(rowA.getByText(s.errRange("30"))).toBeVisible();

      const submit = panel.getByRole("button", { name: s.receiveSubmit, exact: true });
      await expect(submit).toBeDisabled();
      expect(stubs.calls.receive).toHaveLength(0);
      await expect(panel).toBeVisible();

      // Back in range: the button is enabled again.
      await rowA.getByRole("spinbutton").fill("30");
      await expect(rowA.getByText(s.errRange("30"))).toHaveCount(0);
      await expect(submit).toBeEnabled();

      await finish(page, ctx, `R2 (${locale})`);
    });

    test(`R3 server 422 RECEIPT_LINES_MISMATCH: translated message, no raw code (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, receiveTransfers(), { asDestination: true });
      const { s, stubs } = ctx;
      stubs.receive = () => ({ status: 422, detail: { code: "RECEIPT_LINES_MISMATCH", message: "backend-only wording" } });

      const panel = await openReceive(page, s, T_RECV_BATCH);
      await panel.getByRole("button", { name: s.receiveSubmit, exact: true }).click();

      await expect(panel.getByText(s.errLinesMismatch)).toBeVisible({ timeout: 10_000 });
      expect(stubs.calls.receive).toHaveLength(1);
      await expect(page.getByText(/RECEIPT_LINES_MISMATCH/)).toHaveCount(0);
      await expect(page.getByText("backend-only wording")).toHaveCount(0);

      await finish(page, ctx, `R3 (${locale})`);
    });

    test(`R4 IN_TRANSIT and PARTIALLY_RECEIVED offer only Receive (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, receiveTransfers(), { asDestination: true });
      const { s } = ctx;

      for (const id of [T_RECV_BATCH, T_PARTIAL]) {
        const actions = listRow(page, id).locator("td").last().getByRole("button");
        await expect(actions).toHaveCount(1);
        await expect(actions).toHaveText(s.receiveAction);
      }
      await expect(page.getByRole("button", { name: /partial/i })).toHaveCount(0);
      await expect(page.getByRole("button", { name: s.partialReceive })).toHaveCount(0);

      await finish(page, ctx, `R4 (${locale})`);
    });

    test(`R5 non-batch line: one row, POST body has lot_id null (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, receiveTransfers(), { asDestination: true });
      const { s, stubs } = ctx;

      const panel = await openReceive(page, s, T_RECV_PLAIN);
      await expect(panel.locator("tbody tr")).toHaveCount(1);
      const row = lotRow(panel, PROD_PLAIN.name);
      await expect(row.locator("td").nth(1)).toHaveText("—");
      await expect(row.getByRole("spinbutton")).toHaveValue("25");
      await panel.getByRole("button", { name: s.receiveSubmit, exact: true }).click();

      await expect.poll(() => stubs.calls.receive.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.receive[0]).toEqual({
        lines: [{ line_id: LINE_RP, lot_id: null, received_quantity: 25, reason: null, note: null }],
      });

      await finish(page, ctx, `R5 (${locale})`);
    });
  });

  test.describe(`Transfer approve — lot picker (${locale})`, () => {
    test(`A1 non-final step: Approve sends the plain PATCH, no lot picker (${locale})`, async ({ page }) => {
      const transfers = approveTransfers();
      const ctx = await openTransfers(page, locale, transfers);
      const { s, stubs } = ctx;
      stubs.steps[T_APPR_70] = { current_step: 1, total_steps: 2 };

      await listRow(page, T_APPR_70).getByRole("button", { name: s.approveAction, exact: true }).click();
      await page.getByRole("button", { name: s.confirm, exact: true }).click();

      await expect.poll(() => stubs.calls.patch.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.patch[0]).toEqual({ id: T_APPR_70, body: { next_status: "APPROVED" } });
      expect(stubs.calls.approve).toHaveLength(0);
      await expect(page.getByText(s.approveTitle(refOf(T_APPR_70)))).toHaveCount(0);

      await finish(page, ctx, `A1 (${locale})`);
    });

    test(`A2 final step, batch line: suggested split shown, approving unchanged sends the PATCH (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, approveTransfers());
      const { s, stubs } = ctx;

      const panel = await openLotPicker(page, s, T_APPR_70);
      await expect(panel.locator("li")).toHaveCount(2);
      await expect(previewLot(panel, "LOT-A")).toHaveText("30");
      await expect(previewLot(panel, "LOT-B")).toHaveText("40");

      await panel.getByRole("button", { name: s.approveSubmit, exact: true }).click();

      await expect.poll(() => stubs.calls.patch.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.patch[0]).toEqual({ id: T_APPR_70, body: { next_status: "APPROVED" } });
      expect(stubs.calls.approve).toHaveLength(0);
      await expect(panel).toHaveCount(0);

      await finish(page, ctx, `A2 (${locale})`);
    });

    test(`A3 Change lots: sum error blocks submit, FEFO change needs a reason, POST /approve body (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, approveTransfers());
      const { s, stubs } = ctx;

      // Line of 70: LOT-A 20 + LOT-B 40 = 60 — does not add up.
      const panel70 = await openLotPicker(page, s, T_APPR_70);
      await panel70.getByRole("button", { name: s.changeLots, exact: true }).click();
      await expect(lotRow(panel70, "LOT-B").getByRole("spinbutton")).toHaveValue("40");
      await lotRow(panel70, "LOT-A").getByRole("spinbutton").fill("20");
      await expect(panel70.getByText(s.errTotal("60", "70"))).toBeVisible();
      await expect(panel70.getByRole("button").last()).toBeDisabled();
      await panel70.getByRole("button", { name: s.cancel, exact: true }).click();
      await expect(panel70).toHaveCount(0);

      // Line of 50: LOT-A 10 + LOT-B 40 adds up but is not the FEFO suggestion (30 + 20).
      const panel = await chooseOverrideLots(page, s);
      const submit = panel.getByRole("button").last();
      const reason = panel.getByRole("textbox", { name: s.reasonLabel });
      await expect(reason).toHaveAttribute("required", "");
      await expect(panel.getByText(s.errOverrideReason)).toBeVisible();
      await expect(submit).toBeDisabled();

      await reason.fill(OVERRIDE_REASON);
      await expect(submit).toBeEnabled();
      await submit.click();

      await expect.poll(() => stubs.calls.approve.length, { timeout: 10_000 }).toBe(1);
      expect(stubs.calls.approve[0]).toEqual({ id: T_APPR_50, body: OVERRIDE_BODY });
      expect(stubs.calls.patch).toHaveLength(0);
      await expect(panel).toHaveCount(0);

      await finish(page, ctx, `A3 (${locale})`);
    });

    test(`A4 POST /approve 403 OVERRIDE_NOT_PERMITTED: translated message (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, approveTransfers());
      const { s, stubs } = ctx;
      stubs.approve = () => ({ status: 403, detail: { code: "OVERRIDE_NOT_PERMITTED", message: "backend-only wording" } });

      const panel = await chooseOverrideLots(page, s);
      await panel.getByRole("textbox", { name: s.reasonLabel }).fill(OVERRIDE_REASON);
      await panel.getByRole("button").last().click();

      await expect(panel.getByText(s.errOverrideDenied)).toBeVisible({ timeout: 10_000 });
      expect(stubs.calls.approve).toHaveLength(1);
      await expect(page.getByText(/OVERRIDE_NOT_PERMITTED/)).toHaveCount(0);
      await expect(page.getByText("backend-only wording")).toHaveCount(0);

      await finish(page, ctx, `A4 (${locale})`, [APPROVE_FAILURE_LOG]);
    });

    test(`A5 POST /approve 422 INSUFFICIENT_STOCK: usable and expired quantities shown (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, approveTransfers());
      const { s, stubs } = ctx;
      stubs.approve = () => ({ status: 422, detail: {
        code: "INSUFFICIENT_STOCK", message: "backend-only wording", available: 45, expired_qty: 12,
      } });

      const panel = await chooseOverrideLots(page, s);
      await panel.getByRole("textbox", { name: s.reasonLabel }).fill(OVERRIDE_REASON);
      await panel.getByRole("button").last().click();

      await expect(panel.getByText(s.errInsufficient)).toBeVisible({ timeout: 10_000 });
      await expect(panel.getByText(s.stockDetail("45", "12"))).toBeVisible();
      expect(stubs.calls.approve).toHaveLength(1);
      await expect(page.getByText(/INSUFFICIENT_STOCK/)).toHaveCount(0);

      await finish(page, ctx, `A5 (${locale})`, [APPROVE_FAILURE_LOG]);
    });
  });

  test.describe(`Transfer request — dispatch preview (${locale})`, () => {
    test(`P1 batch product: strategy, likely lots and the nothing-is-reserved note (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, []);
      const { s } = ctx;

      const panel = await openRequestPanel(page, s);
      await fillRequest(panel, s, PROD_BATCH.name);

      const box = previewBox(panel);
      await expect(box).toBeVisible({ timeout: 10_000 });
      await expect(box.getByText(s.previewStrategyFefo, { exact: true })).toBeVisible();
      await expect(previewLot(box, "LOT-A")).toHaveText("30");
      await expect(previewLot(box, "LOT-B")).toHaveText("20");
      await expect(box.getByText(s.previewNote, { exact: true })).toBeVisible();

      await finish(page, ctx, `P1 (${locale})`);
    });

    test(`P2 shortfall and an expired lot skipped: both notes appear (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, []);
      const { s, stubs } = ctx;
      stubs.preview = () => ({ status: 200, data: SHORTFALL_PREVIEW });

      const panel = await openRequestPanel(page, s);
      await fillRequest(panel, s, PROD_BATCH.name);

      const box = previewBox(panel);
      await expect(box).toBeVisible({ timeout: 10_000 });
      await expect(box.getByText(s.shortfall("10"))).toBeVisible();
      await expect(box.getByText(s.expiredSkipped("5"))).toBeVisible();
      await expect(box.getByText("LOT-X")).toHaveCount(0);

      await finish(page, ctx, `P2 (${locale})`);
    });

    test(`P3 non-batch product (strategy null): no info box (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, []);
      const { s, stubs } = ctx;

      const panel = await openRequestPanel(page, s);
      await fillRequest(panel, s, PROD_PLAIN.name);

      await expect.poll(() => stubs.calls.preview, { timeout: 10_000 }).toBeGreaterThan(0);
      await page.waitForTimeout(1_000);
      await expect(previewBox(panel)).toHaveCount(0);

      await finish(page, ctx, `P3 (${locale})`);
    });

    test(`P4 preview returns 500: no info box, request can still be submitted (${locale})`, async ({ page }) => {
      const ctx = await openTransfers(page, locale, []);
      const { s, stubs } = ctx;
      stubs.preview = () => ({ status: 500, detail: "preview unavailable" });

      const panel = await openRequestPanel(page, s);
      await fillRequest(panel, s, PROD_BATCH.name);

      await expect.poll(() => stubs.calls.preview, { timeout: 10_000 }).toBeGreaterThan(0);
      await page.waitForTimeout(1_000);
      await expect(previewBox(panel)).toHaveCount(0);
      await expect(panel.getByRole("button", { name: s.createSubmit, exact: true })).toBeEnabled();

      await finish(page, ctx, `P4 (${locale})`, [PREVIEW_500_LOG]);
    });
  });
}
