/**
 * Playwright E2E — backend error-code i18n (session 19, P6).
 *
 * Verifies frontend/src/lib/api.ts's generic errors.<CODE> fallback: when the
 * backend's HTTP error `detail` carries a `code` with no screen-specific
 * handling, the UI shows the translated errors.<CODE> text (with {placeholder}
 * tokens filled from `detail`), never the raw backend English message, and a
 * FastAPI 422 validation array renders errors.VALIDATION.
 *
 * Uses the New Adjustment panel (frontend/src/components/features/inventory/
 * NewAdjustmentPanel.tsx) as the simple-save screen, with the non-batch
 * product so there is no lot UI to fill — same fixture shape as
 * tests/adjustment-lots.spec.ts, trimmed to just this panel's open/fill/submit.
 *
 *   E1 (am)  POST -> 403 {code: RBAC_DENIED}            -> am errors.RBAC_DENIED text, not the English message
 *   E2 (en)  same stub                                   -> en errors.RBAC_DENIED text
 *   E3 (am)  POST -> 402 {code: FEATURE_NOT_IN_PLAN, ...} -> am text with {feature}/{plan_tier}/{upgrade_to} filled, no literal "{"
 *   E4 (am)  POST -> 422 FastAPI validation array detail  -> am errors.VALIDATION text
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real,
 * using the permanent zz-e2e-ta TA probe account. Every adjustment / products /
 * warehouses / stock / approval-rules request is answered from fixtures by one
 * page.route() handler (installStubs), which is also the catch-all write guard:
 * any other non-GET request to an /api/ path is aborted, recorded, and fails
 * the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/error-i18n.spec.ts --project=chromium --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type Locator, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });
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

function readLocale(locale: Locale) {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  return JSON.parse(raw);
}

function localeStrings(locale: Locale) {
  const d = readLocale(locale);
  return {
    newButton:  d.adjustment.new_btn as string,
    panelTitle: d.adjustment.title as string,
    submit:     d.adjustment.submit as string,
    rbacDenied: d.errors.RBAC_DENIED as string,
    validation: d.errors.VALIDATION as string,
    featureNotInPlan: d.errors.FEATURE_NOT_IN_PLAN as string,
    tierGrowth: d.tenant_admin.plan.tier.GROWTH as string,
  };
}
type Strings = ReturnType<typeof localeStrings>;

/* ── Fixtures — a single non-batch product, no lot UI to fill ────────────── */
const WH_A = "11111111-1111-4111-8111-111111111111";
const PROD_PLAIN = { id: "33333333-3333-4333-8333-333333333399", sku: "ERR-P-01", name: "ERR-I18N-PLAIN" };
const ADJ_PATH = "/api/v1/inventory/adjustments";

interface StubReply { status: number; data?: unknown; detail?: unknown }
interface Stubs {
  post: () => StubReply;
  calls: { posts: number; unstubbedWrites: string[] };
}

function reply(route: Route, r: StubReply) {
  const body = r.status < 400
    ? { success: true, data: r.data, request_id: "test", timestamp: new Date().toISOString() }
    : { detail: r.detail };
  return route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installStubs(page: Page): Promise<Stubs> {
  const stubs: Stubs = {
    post: () => ({ status: 201, data: { adjustment_id: "bbbb0001-0000-4000-8000-000000000001", status: "PENDING_APPROVAL", quantity_delta: "0" } }),
    calls: { posts: 0, unstubbedWrites: [] },
  };

  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req    = route.request();
    const method = req.method();
    const url    = new URL(req.url());
    const p      = url.pathname.replace(/\/$/, "");

    if (method === "GET") {
      if (p === ADJ_PATH) return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/products") {
        return reply(route, {
          status: 200,
          data: [{ ...PROD_PLAIN, type_code: "FG", unit: "pcs", pack_size: 1, created_at: "2026-10-01T00:00:00Z", batch_tracking: false, expiry_tracking: false }],
        });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/nodes$/.test(p)) {
        return reply(route, {
          status: 200,
          data: [{ id: WH_A, name: "Err WH A", address: null, hierarchy_level: 1, level_name: null, is_stock_holding: true, parent_node_id: null, children: [] }],
        });
      }
      if (/^\/api\/v1\/tenants\/[^/]+\/adjustment-approval-rules$/.test(p)) return reply(route, { status: 200, data: [] });
      if (p === "/api/v1/inventory/analytics/stock") {
        return reply(route, { status: 200, data: [{ product_id: PROD_PLAIN.id, warehouse_id: WH_A, current_stock: "1000" }] });
      }
      return route.continue();
    }

    if (method === "OPTIONS") return route.continue();
    if (method === "POST" && p === "/api/v1/auth/token") return route.continue();   // real login

    if (method === "POST" && p === ADJ_PATH) {
      stubs.calls.posts += 1;
      return reply(route, stubs.post());
    }

    // Catch-all guard: no other write may leave the browser.
    stubs.calls.unstubbedWrites.push(`${method} ${url.pathname}`);
    return route.abort();
  });

  return stubs;
}

interface Ctx { s: Strings; stubs: Stubs; consoleErrors: string[] }

async function openAdjustments(page: Page, locale: Locale): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const s = localeStrings(locale);
  const consoleErrors = collectConsoleErrors(page);
  const stubs = await installStubs(page);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/adjustments`);
  await page.waitForLoadState("networkidle");
  return { s, stubs, consoleErrors };
}

async function finish(page: Page, ctx: Ctx, label: string) {
  expect(ctx.stubs.calls.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  console.log(`--- ${label} console errors ---`);
  for (const e of ctx.consoleErrors) console.log(e);
  expect(ctx.consoleErrors, `zero console errors (${label})`).toHaveLength(0);
}

async function openPanel(page: Page, s: Strings): Promise<Locator> {
  await page.getByRole("button", { name: s.newButton, exact: true }).click();
  const panel = page.locator("div.fixed.top-0.right-0.translate-x-0").filter({ hasText: s.panelTitle });
  await expect(panel).toBeVisible();
  return panel;
}

/** Non-batch product, DAMAGE reason (single quantity field, no lot UI). */
async function fillAndSubmit(panel: Locator, s: Strings) {
  await panel.locator("select").nth(0).selectOption(PROD_PLAIN.id);
  await panel.locator("select").nth(1).selectOption(WH_A);
  await panel.locator("select").nth(2).selectOption("DAMAGE");
  await panel.locator('input[type="number"]').first().fill("5");
  await panel.getByRole("button", { name: s.submit, exact: true }).click();
}

const panelError = (panel: Locator) => panel.getByTestId("panel-error");

/* ── E1/E2: an unhandled 403 code falls back to errors.<CODE>, not the backend English ── */
for (const locale of ["am", "en"] as const) {
  test(`E${locale === "am" ? 1 : 2} (${locale}): 403 RBAC_DENIED renders the translated errors.RBAC_DENIED text`, async ({ page }) => {
    const ctx = await openAdjustments(page, locale);
    const { s, stubs } = ctx;
    stubs.post = () => ({ status: 403, detail: { code: "RBAC_DENIED", message: "backend-only wording" } });

    const panel = await openPanel(page, s);
    await fillAndSubmit(panel, s);

    await expect(panelError(panel)).toHaveText(s.rbacDenied, { timeout: 10_000 });
    await expect(page.getByText("backend-only wording")).toHaveCount(0);
    await expect(page.getByText(/RBAC_DENIED/)).toHaveCount(0);
    expect(stubs.calls.posts).toBe(1);

    await finish(page, ctx, `E-rbac-${locale}`);
  });
}

/* ── E3: a code with {placeholder} fields gets them filled, never a literal "{" ── */
test("E3 (am): 402 FEATURE_NOT_IN_PLAN fills {feature}/{plan_tier}/{upgrade_to}, no literal \"{\"", async ({ page }) => {
  const ctx = await openAdjustments(page, "am");
  const { s, stubs } = ctx;
  stubs.post = () => ({
    status: 402,
    detail: {
      code: "FEATURE_NOT_IN_PLAN", feature: "LOT_TRACEABILITY",
      plan_tier: "STARTER", upgrade_to: "GROWTH",
      message: "'LOT_TRACEABILITY' is not available on your current plan (STARTER). Upgrade to GROWTH to unlock this feature.",
    },
  });

  const panel = await openPanel(page, s);
  await fillAndSubmit(panel, s);

  const errEl = panelError(panel);
  await expect(errEl).toBeVisible({ timeout: 10_000 });
  const text = await errEl.innerText();
  expect(text, "placeholder filled, no literal {").not.toContain("{");
  expect(text, "feature flag value present").toContain("LOT_TRACEABILITY");
  expect(text, "upgrade_to tier shown via tierLabel").toContain(s.tierGrowth);
  expect(stubs.calls.posts).toBe(1);

  await finish(page, ctx, "E3");
});

/* ── E4: a FastAPI 422 validation-array detail renders errors.VALIDATION ─────── */
test("E4 (am): 422 validation-array detail renders errors.VALIDATION", async ({ page }) => {
  const ctx = await openAdjustments(page, "am");
  const { s, stubs } = ctx;
  stubs.post = () => ({
    status: 422,
    detail: [{ loc: ["body", "notes"], msg: "field required", type: "value_error.missing" }],
  });

  const panel = await openPanel(page, s);
  await fillAndSubmit(panel, s);

  await expect(panelError(panel)).toHaveText(s.validation, { timeout: 10_000 });
  expect(stubs.calls.posts).toBe(1);

  await finish(page, ctx, "E4");
});
