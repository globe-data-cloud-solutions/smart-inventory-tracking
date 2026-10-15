/**
 * Playwright E2E — Transfers list i18n labels + Receive Stock button visibility
 * (session/2026-10-15-fefo-d3).
 *
 * Covers, for en + am:
 *   L1 List labels: column headers, status badges, type badges, action buttons and the
 *      "waiting for…" texts come from the locale pack. In am none of them is English; in
 *      both locales no raw i18n key and no raw status code ("IN_TRANSIT") is visible text.
 *      The confirm dialog opened from an action button shows the translated status.
 *   L2 Tenant type name: with a stubbed tenant transfer type (display_name) the list badge
 *      and the detail page badge show that name; an inactive config is ignored and a type
 *      with no tenant name falls back to the translated generic label.
 *   R1 Receive Stock button: absent for a session with no warehouseId, present with one.
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real, using the
 * permanent zz-e2e-ta TA probe account (the warehouse case patches the client session only,
 * see helpers/session-role.ts). Transfers / approval-info / transfer-types / products /
 * stock / hierarchy requests are answered from the fixtures below by one page.route()
 * handler (installStubs); any other non-GET request to an /api/ path is aborted, recorded,
 * and fails the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/transfers-i18n.spec.ts --project=chromium --workers=1
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

function readLocale(locale: Locale) {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  return JSON.parse(raw);
}

function localeStrings(locale: Locale) {
  const d = readLocale(locale);
  const tr = d.transfers;
  return {
    col:       tr.col as Record<string, string>,
    action:    tr.action as Record<string, string>,
    wait:      tr.wait as Record<string, string>,
    status:    tr.view.status as Record<string, string>,
    type:      tr.view.type as Record<string, string>,
    willChange: tr.status_will_change as string,
    receive:   d.inventory.receive.title as string,
  };
}
type Strings = ReturnType<typeof localeStrings>;

const fill = (text: string, params: Record<string, string>) =>
  Object.entries(params).reduce((acc, [k, v]) => acc.split(`{${k}}`).join(v), text);

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const WH_A = "11111111-1111-4111-8111-111111111111";
const WH_B = "22222222-2222-4222-8222-222222222222";
const OTHER_USER = "99999999-9999-4999-8999-999999999999";
const PROD = { id: "33333333-3333-4333-8333-333333333311", sku: "LST-A-01", name: "LIST-WIDGET-A" };

const ID_APPROVED   = "aaaa0001-0000-4000-8000-000000000001";   // PUSH  APPROVED          -> Issue / Cancel buttons
const ID_DRAFT      = "aaaa0002-0000-4000-8000-000000000002";   // PULL  DRAFT             -> wait text
const ID_SOURCE     = "aaaa0003-0000-4000-8000-000000000003";   // SISTER PENDING_SOURCE   -> wait text
const ID_IN_TRANSIT = "aaaa0004-0000-4000-8000-000000000004";   // PUSH  IN_TRANSIT        -> wait text; detail page
const REF = (id: string) => id.slice(0, 8).toUpperCase();

const NAME_A = "List Source WH";
const NAME_B = "List Dest WH";

function rawTransfer(id: string, type: string, status: string) {
  return {
    transfer_id: id, transfer_type: type, status,
    from_warehouse_id: WH_A, from_warehouse_name: NAME_A,
    to_warehouse_id: WH_B, to_warehouse_name: NAME_B,
    lines: [{ product_id: PROD.id, product_name: PROD.name, sku: PROD.sku, quantity: "10.0000", uom: "pcs" }],
    created_by: OTHER_USER, created_by_authority_level: 4,
    created_at: "2026-10-12T08:00:00Z", is_self_approved: false,
  };
}

const LIST = [
  rawTransfer(ID_APPROVED,   "PUSH",   "APPROVED"),
  rawTransfer(ID_DRAFT,      "PULL",   "DRAFT"),
  rawTransfer(ID_SOURCE,     "SISTER", "PENDING_SOURCE_CONFIRM"),
  rawTransfer(ID_IN_TRANSIT, "PUSH",   "IN_TRANSIT"),
];

function detailOf(id: string) {
  const row = LIST.find((r) => r.transfer_id === id)!;
  return {
    ...row, reference_number: "TRF-I18N-0001",
    lines: [{ line_id: "55555555-5555-4555-8555-555555555501", ...row.lines[0] }],
    lot_allocations: [], discrepancies: [],
  };
}

/** Raw i18n keys and raw status codes ("IN_TRANSIT", "PENDING_SOURCE_CONFIRM") must never be visible. */
const RAW_TEXT = /transfers\.(col|action|wait|toast|list|view)\.|\b[A-Z]{3,}(_[A-Z]+)+\b/;

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
// level_permissions is part of the real response; NewTransferPanel (also on this page) reads it.
interface TenantTypeStub { id: string; underlying_type: string; display_name: string; is_active: boolean; level_permissions: unknown[] }

interface Stubs {
  transferTypes: TenantTypeStub[];
  calls: { unstubbedWrites: string[] };
}

function reply(route: Route, data: unknown) {
  return route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ success: true, data, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

async function installStubs(page: Page): Promise<Stubs> {
  const stubs: Stubs = { transferTypes: [], calls: { unstubbedWrites: [] } };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === "/api/v1/inventory/transfers") return reply(route, LIST);
      if (p === "/api/v1/inventory/transfers/discrepancies") return reply(route, []);
      const detailMatch = p.match(/^\/api\/v1\/inventory\/transfers\/([0-9a-f-]{36})$/);
      if (detailMatch && LIST.some((r) => r.transfer_id === detailMatch[1])) return reply(route, detailOf(detailMatch[1]));
      if (/^\/api\/v1\/inventory\/transfers\/[^/]+\/approval-info$/.test(p)) {
        return reply(route, {
          transfer_id: "x", required_authority_level: 1, required_role_display: "Tenant Admin",
          is_auto_approve: false, can_approve: false, reason: "", current_step: 1, total_steps: 1,
        });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return reply(route, stubs.transferTypes);
      if (/^\/api\/v1\/tenants\/[^/]+\/hierarchy\/config$/.test(p)) return reply(route, []);
      if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) return reply(route, []);
      if (p === "/api/v1/inventory/lots") return reply(route, []);
      if (p === "/api/v1/inventory/analytics/stock") return reply(route, []);
      if (p === "/api/v1/products") {
        return reply(route, [{
          ...PROD, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z",
          batch_tracking: false, expiry_tracking: false,
        }]);
      }
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

async function open(
  page: Page, locale: Locale, target: string,
  opts: { setup?: (stubs: Stubs) => void; session?: (page: Page) => Promise<void> } = {},
): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const errors = collectErrors(page);
  const stubs = await installStubs(page);
  opts.setup?.(stubs);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  if (opts.session) await opts.session(page);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/${target}`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, errors };
}

async function finish(page: Page, ctx: Ctx, label: string) {
  expect(ctx.errors.pageErrors, `no page errors (${label})`).toEqual([]);
  expect(ctx.stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  console.log(`--- ${label} console errors ---`);
  for (const e of ctx.errors.console) console.log(e);
  for (const e of ctx.errors.pageErrors) console.log(`[pageerror] ${e}`);
  expect(ctx.errors.console, `zero console errors (${label})`).toHaveLength(0);
}

/* ── L1: list labels ──────────────────────────────────────────────────────── */
for (const locale of ["en", "am"] as const) {
  test(`list labels come from the ${locale} pack (L1)`, async ({ page }) => {
    const ctx = await open(page, locale, "transfers");
    const { s } = ctx;
    const en = localeStrings("en");

    // Column headers
    for (const key of Object.keys(s.col)) {
      await expect(page.getByRole("columnheader", { name: s.col[key], exact: true })).toBeVisible();
      if (locale === "am") {
        expect(s.col[key], `am header ${key} differs from English`).not.toBe(en.col[key]);
        await expect(page.getByRole("columnheader", { name: en.col[key], exact: true })).toHaveCount(0);
      }
    }

    const row = (id: string) => page.locator("tr").filter({ hasText: REF(id) });

    // APPROVED PUSH: status badge, type badge, Issue / Cancel buttons
    await expect(row(ID_APPROVED).getByText(s.status.APPROVED, { exact: true })).toBeVisible();
    await expect(row(ID_APPROVED).getByText(s.type.PUSH, { exact: true })).toBeVisible();
    await expect(row(ID_APPROVED).getByRole("button", { name: s.action.issue, exact: true })).toBeVisible();
    await expect(row(ID_APPROVED).getByRole("button", { name: s.action.cancel, exact: true })).toBeVisible();

    // Waiting texts
    await expect(row(ID_DRAFT).getByText(s.status.DRAFT, { exact: true })).toBeVisible();
    await expect(row(ID_DRAFT).getByText(s.type.PULL, { exact: true })).toBeVisible();
    await expect(row(ID_DRAFT).getByText(fill(s.wait.draft, { name: NAME_B }))).toBeVisible();
    await expect(row(ID_SOURCE).getByText(s.status.PENDING_SOURCE_CONFIRM, { exact: true })).toBeVisible();
    await expect(row(ID_SOURCE).getByText(s.type.SISTER, { exact: true })).toBeVisible();
    await expect(row(ID_SOURCE).getByText(fill(s.wait.source_confirm, { name: NAME_A }))).toBeVisible();
    await expect(row(ID_IN_TRANSIT).getByText(s.status.IN_TRANSIT, { exact: true })).toBeVisible();
    await expect(row(ID_IN_TRANSIT).getByText(fill(s.wait.in_transit, { name: NAME_B }))).toBeVisible();

    if (locale === "am") {
      const tableText = await page.locator("table").innerText();
      const ENGLISH = /\b(Reference|Product|Qty|Status|Date|Actions|Approved|Draft|In transit|Pull request|Sister transfer|Pending source confirmation|Issue|Cancel|Waiting for|Awaiting)\b/;
      expect(tableText, "no English labels in the am table").not.toMatch(ENGLISH);
    }

    // Confirm dialog: translated action label and translated target status, never ISSUED.
    await row(ID_APPROVED).getByRole("button", { name: s.action.issue, exact: true }).click();
    const dialog = page.locator("div.z-\\[201\\]");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(`${s.action.issue} — ${s.willChange}`);
    await expect(dialog.locator("strong")).toHaveText(s.status.ISSUED);
    await expect(dialog).not.toContainText("ISSUED");

    await expect(page.getByText(RAW_TEXT)).toHaveCount(0);
    await finish(page, ctx, `L1 ${locale}`);
  });
}

/* ── L2: tenant type name on list + detail ────────────────────────────────── */
for (const locale of ["en", "am"] as const) {
  test(`tenant transfer type name shows on the list and detail badges (${locale}) (L2)`, async ({ page }) => {
    const TENANT_PUSH = "Dispatch Order";
    const INACTIVE_PULL = "Retired Pull Name";
    const ctx = await open(page, locale, "transfers", {
      setup: (stubs) => {
        stubs.transferTypes = [
          { id: "t1", underlying_type: "PUSH", display_name: TENANT_PUSH, is_active: true, level_permissions: [] },
          { id: "t2", underlying_type: "PULL", display_name: INACTIVE_PULL, is_active: false, level_permissions: [] },
        ];
      },
    });
    const { s } = ctx;
    const row = (id: string) => page.locator("tr").filter({ hasText: REF(id) });

    // List: PUSH rows use the tenant name; PULL (inactive config) and SISTER (no config) use the generic label.
    await expect(row(ID_APPROVED).getByText(TENANT_PUSH, { exact: true })).toBeVisible();
    await expect(row(ID_IN_TRANSIT).getByText(TENANT_PUSH, { exact: true })).toBeVisible();
    await expect(row(ID_APPROVED).getByText(s.type.PUSH, { exact: true })).toHaveCount(0);
    await expect(row(ID_DRAFT).getByText(s.type.PULL, { exact: true })).toBeVisible();
    await expect(page.getByText(INACTIVE_PULL)).toHaveCount(0);
    await expect(row(ID_SOURCE).getByText(s.type.SISTER, { exact: true })).toBeVisible();

    // Detail page of the IN_TRANSIT PUSH transfer: same name on the header badge.
    await row(ID_IN_TRANSIT).getByRole("link", { name: new RegExp(REF(ID_IN_TRANSIT)) }).click();
    await page.waitForURL(new RegExp(`/transfers/${ID_IN_TRANSIT}$`));
    await expect(page.getByText("TRF-I18N-0001", { exact: true })).toBeVisible();
    await expect(page.getByText(TENANT_PUSH, { exact: true })).toBeVisible();
    await expect(page.getByText(s.status.IN_TRANSIT, { exact: true })).toBeVisible();
    await expect(page.getByText(s.type.PUSH, { exact: true })).toHaveCount(0);

    await expect(page.getByText(RAW_TEXT)).toHaveCount(0);
    await finish(page, ctx, `L2 ${locale}`);
  });
}

/* ── R1: Receive Stock button needs a warehouse ───────────────────────────── */
for (const locale of ["en", "am"] as const) {
  test(`Receive Stock button: absent without warehouseId, present with one (${locale}) (R1)`, async ({ page }) => {
    // TA probe session: no warehouseId (TA is tenant-wide).
    const ctx = await open(page, locale, "inventory");
    const receiveBtn = page.getByRole("button", { name: `+ ${ctx.s.receive}` });
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
    await expect(receiveBtn).toHaveCount(0);

    // Same user, client session patched to have a warehouse (no backend write).
    await asRole(page, "TA", "test-wh-001");
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/inventory`);
    await page.waitForLoadState("networkidle");
    await expect(receiveBtn).toHaveCount(1);
    await expect(receiveBtn).toBeVisible();

    await finish(page, ctx, `R1 ${locale}`);
  });
}
