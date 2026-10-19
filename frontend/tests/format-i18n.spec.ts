/**
 * Playwright E2E — date/number formatting follows the app language, and help
 * documents are served in the viewer's locale with an English fallback
 * (session 19, frontend/src/lib/format.ts + frontend/src/lib/help/fetchHelpDoc.ts).
 *
 * F1/F2: the Transfers list date cell for a stubbed transfer (created_at
 *   2026-10-18) renders with the app's locale (am-ET digit order in am,
 *   en-US digit order in en), never an English month name ("Oct"/"October").
 * F3/F3b: the public /getting-started page renders the Amharic document in
 *   am (frontend/public/help/am/getting-started.md) and the English one in en
 *   — these are real static files, not stubbed.
 *
 * NO LIVE WRITES for F1/F2 (zz-e2e-ta TA probe login; catch-all write guard,
 * same pattern as transfers-i18n.spec.ts). F3/F3b need no login (public page).
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/format-i18n.spec.ts --project=chromium --workers=1
 */
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });

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

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const WH_A = "11111111-1111-4111-8111-111111111111";
const WH_B = "22222222-2222-4222-8222-222222222222";
const OTHER_USER = "99999999-9999-4999-8999-999999999999";
const PROD = { id: "33333333-3333-4333-8333-333333333312", sku: "FMT-A-01", name: "FORMAT-WIDGET-A" };
const ID_APPROVED = "bbbb0001-0000-4000-8000-000000000001";
const REF = ID_APPROVED.slice(0, 8).toUpperCase();

// Fixed date — 18 October 2026. en-US renders "10/18/2026", am-ET renders "18/10/2026"
// (day/month order swaps; neither ever spells out a month name).
const CREATED_AT = "2026-10-18T09:00:00Z";

function rawTransfer() {
  return {
    transfer_id: ID_APPROVED, transfer_type: "PUSH", status: "APPROVED",
    from_warehouse_id: WH_A, from_warehouse_name: "Format Source WH",
    to_warehouse_id: WH_B, to_warehouse_name: "Format Dest WH",
    lines: [{ product_id: PROD.id, product_name: PROD.name, sku: PROD.sku, quantity: "5.0000", uom: "pcs" }],
    created_by: OTHER_USER, created_by_authority_level: 4,
    created_at: CREATED_AT, is_self_approved: false,
  };
}

interface Stubs { calls: { unstubbedWrites: string[] } }

function reply(route: Route, data: unknown) {
  return route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ success: true, data, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

async function installStubs(page: Page): Promise<Stubs> {
  const stubs: Stubs = { calls: { unstubbedWrites: [] } };
  const LIST = [rawTransfer()];

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req = route.request();
    const method = req.method();
    const url = new URL(req.url());
    const p = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === "/api/v1/inventory/transfers") return reply(route, LIST);
      if (p === "/api/v1/inventory/transfers/discrepancies") return reply(route, []);
      if (/^\/api\/v1\/inventory\/transfers\/[^/]+\/approval-info$/.test(p)) {
        return reply(route, {
          transfer_id: "x", required_authority_level: 1, required_role_display: "Tenant Admin",
          is_auto_approve: false, can_approve: false, reason: "", current_step: 1, total_steps: 1,
        });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/transfer-types$/.test(p)) return reply(route, []);
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
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();

    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

async function finish(page: Page, errors: Collected, stubs: Stubs, label: string) {
  expect(errors.pageErrors, `no page errors (${label})`).toEqual([]);
  expect(stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  for (const e of errors.console) console.log(`[console] ${e}`);
  for (const e of errors.pageErrors) console.log(`[pageerror] ${e}`);
  expect(errors.console, `zero console errors (${label})`).toHaveLength(0);
}

/* ── F1/F2: Transfers list date cell follows the app locale ──────────────── */
for (const locale of ["am", "en"] as const) {
  test(`Transfers list date cell follows the app locale (${locale}) (F1/F2)`, async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const errors = collectErrors(page);
    const stubs = await installStubs(page);

    await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
    await login(page, E2E_TA_EMAIL, taPassword);
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/transfers`);
    await page.waitForLoadState("networkidle");

    const row = page.locator("tr").filter({ hasText: REF });
    await expect(row).toBeVisible();
    const rowText = await row.innerText();

    expect(rowText, `no English month abbreviation in the ${locale} date cell`).not.toMatch(/\bOct(ober)?\b/);
    if (locale === "en") {
      expect(rowText, "en renders month/day/year order").toContain("10/18/2026");
    } else {
      expect(rowText, "am renders day/month/year order (am-ET), not the en-US order").toContain("18/10/2026");
      expect(rowText, "am date cell must differ from the en rendering").not.toContain("10/18/2026");
    }

    await finish(page, errors, stubs, `F1/F2 ${locale}`);
  });
}

/* ── F3/F3b: /getting-started renders the locale-matched help document ──── */
for (const locale of ["am", "en"] as const) {
  test(`/getting-started renders the ${locale} document (F3/F3b)`, async ({ page }) => {
    const errors = collectErrors(page);
    await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
    await page.goto(`${BASE_URL}/getting-started`);
    await page.waitForLoadState("networkidle");

    if (locale === "am") {
      await expect(page.getByRole("heading", { level: 1, name: "SMART Inventory — መጀመሪያ ገጽ" })).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { level: 1, name: "SMART Inventory — Getting Started" })).toBeVisible();
    }

    expect(errors.pageErrors, `no page errors (F3 ${locale})`).toEqual([]);
  });
}
