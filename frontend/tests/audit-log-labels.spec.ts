/**
 * Playwright E2E — Audit Log readable labels (session 18, prompts E1/E2).
 *
 * Covers, for en + am, with GET /api/v1/audit-log/ answered from a fixture:
 *   a) a transfer_discrepancy row: translated action label (not the raw
 *      "transfer:resolve_discrepancy"), translated resource label, a transfer-ref link to
 *      /<org>/transfers/<transfer_order_id> (not the discrepancy id), and the enrichment line
 *      "<product> · <missing qty> <reason> · <resolution>"
 *   b) a transfer:receive row with discrepancy_count 2: translated action label, the received/short
 *      quantities from abac_context, and "2 discrepancies reported"
 *   c) an unknown action still falls back to the raw code; an unknown resource_type falls back raw
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) is real, using the permanent zz-e2e-ta TA probe
 * account. The audit-log request is matched on a normalised path (trailing slash stripped), and any
 * other non-GET /api/ request is aborted and recorded (fails the test).
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/audit-log-labels.spec.ts --project=chromium --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
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

function localeStrings(locale: Locale) {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  return {
    discAction:   d.audit.actions.transfer_resolve_discrepancy as string,
    recvAction:   d.audit.actions.transfer_receive as string,
    discResource: d.audit.resources.transfer_discrepancy as string,
    reason:       d.transfers.discrepancies.reason.SHORT as string,
    resolution:   d.transfers.discrepancies.resolution.WRITTEN_OFF as string,
    reported:     (n: number) => (d.audit.discrepancies_reported as string).replace("{count}", String(n)),
    quantities:   (r: string, s: string) =>
      (d.audit.receive_quantities as string).replace("{received}", r).replace("{short}", s),
  };
}

/* ── Fixtures ─────────────────────────────────────────────────────────────── */
const T_ID = "aaaa0003-0000-4000-8000-000000000003";
const D_ID = "66666666-6666-4666-8666-666666666601";
const PRODUCT = "SMOKE-BATCH";
const UNKNOWN_ACTION = "transfer:zz_unknown_action";
const UNKNOWN_RESOURCE = "zz_unknown_resource";

const base = {
  timestamp: "2026-10-16T09:00:00Z", user_id: null, user_name: "Smoke User", role: "WM",
  decision: "GRANTED", reason: null, abac_context: null, transfer_type: null,
  from_warehouse_name: null, to_warehouse_name: null, product_summary: null,
  adjustment_reason_code: null, transfer_order_id: null, discrepancy_count: null,
  discrepancy_product_name: null, discrepancy_missing_quantity: null,
  discrepancy_reason: null, discrepancy_resolution: null,
};

const ROWS = [
  {
    ...base, id: "70000000-0000-4000-8000-000000000001",
    action: "transfer:resolve_discrepancy", resource_type: "transfer_discrepancy", resource_id: D_ID,
    transfer_type: "PUSH", from_warehouse_name: "Smoke Source WH", to_warehouse_name: "Smoke Dest WH",
    transfer_order_id: T_ID, discrepancy_product_name: PRODUCT, discrepancy_missing_quantity: "2.0000",
    discrepancy_reason: "SHORT", discrepancy_resolution: "WRITTEN_OFF",
  },
  {
    ...base, id: "70000000-0000-4000-8000-000000000002",
    action: "transfer:receive", resource_type: "transfer", resource_id: T_ID,
    transfer_type: "PUSH", from_warehouse_name: "Smoke Source WH", to_warehouse_name: "Smoke Dest WH",
    product_summary: "SMOKE-BATCH (40)", transfer_order_id: T_ID, discrepancy_count: 2,
    abac_context: { received_quantity_total: "38.0000", short_quantity_total: "2.0000", discrepancy_count: 2 },
  },
  {
    ...base, id: "70000000-0000-4000-8000-000000000003",
    action: UNKNOWN_ACTION, resource_type: UNKNOWN_RESOURCE,
    resource_id: "88888888-8888-4888-8888-888888888888",
  },
];

/* ── Stubs + catch-all write guard ────────────────────────────────────────── */
interface Stubs { unstubbedWrites: string[]; auditGets: number }

function reply(route: Route, data: unknown) {
  return route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ success: true, data, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

async function installStubs(page: Page): Promise<Stubs> {
  const stubs: Stubs = { unstubbedWrites: [], auditGets: 0 };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/+$/, "");   // normalise: "/api/v1/audit-log/" == "/api/v1/audit-log"

    if (method === "GET") {
      if (p === "/api/v1/audit-log") {
        stubs.auditGets += 1;
        return reply(route, ROWS);
      }
      return route.continue();
    }
    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    stubs.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Audit log labels (${locale})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
    });

    test(`discrepancy, receive and unknown rows render readable labels (${locale})`, async ({ page }) => {
      const s = localeStrings(locale);
      const taPassword = e2eTaPasswordOrSkip(test);
      const errors = collectErrors(page);
      const stubs = await installStubs(page);
      await login(page, E2E_TA_EMAIL, taPassword);

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/audit-log`);
      const rows = page.locator("tbody tr");
      await expect(rows).toHaveCount(ROWS.length);
      expect(stubs.auditGets).toBeGreaterThan(0);

      // a) transfer_discrepancy row
      const disc = rows.nth(0);
      await expect(disc).toContainText(s.discAction);
      await expect(disc).not.toContainText("transfer:resolve_discrepancy");
      await expect(disc).toContainText(s.discResource);
      await expect(disc).not.toContainText("transfer_discrepancy");
      const link = disc.getByTestId("audit-transfer-link");
      await expect(link).toHaveAttribute("href", `/${E2E_TA_SLUG}/transfers/${T_ID}`);
      await expect(link).toHaveText(`#${T_ID.slice(0, 8).toUpperCase()}`);
      await expect(disc).not.toContainText(D_ID.slice(0, 8));   // not the discrepancy id
      await expect(disc).toContainText(`${PRODUCT} · 2 ${s.reason} · ${s.resolution}`);

      // b) receive row with discrepancy_count 2
      const recv = rows.nth(1);
      await expect(recv).toContainText(s.recvAction);
      await expect(recv).toContainText(s.quantities("38", "2"));
      await expect(recv).toContainText(s.reported(2));
      await expect(recv.getByTestId("audit-transfer-link"))
        .toHaveAttribute("href", `/${E2E_TA_SLUG}/transfers/${T_ID}`);

      // c) unknown action / resource fall back to the raw code
      const unknown = rows.nth(2);
      await expect(unknown).toContainText(UNKNOWN_ACTION);
      await expect(unknown).toContainText(UNKNOWN_RESOURCE);

      expect(errors.pageErrors, `no page errors (${locale})`).toEqual([]);
      expect(stubs.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
      console.log(`--- ${locale} console errors ---`);
      for (const e of errors.console) console.log(e);
      for (const e of errors.pageErrors) console.log(`[pageerror] ${e}`);
      expect(errors.console, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}
