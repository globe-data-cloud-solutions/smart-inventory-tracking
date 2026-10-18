/**
 * Playwright E2E — Org Setup page i18n (session 19, prompt P3).
 *
 * Covers, for en + am:
 *   O1 (am) Clicking through every tab, none of the English values of the
 *      locale keys added in P3 (that render on that tab without any data)
 *      is visible.
 *   O2 (en + am) No visible text on any tab matches the raw i18n key pattern
 *      /^[a-z_]+\.[a-z_.]+$/.
 *   O3 (am) The Levels tab role dropdown shows the am values of roles.NM /
 *      roles.WM, not "National Manager" / "Warehouse Manager".
 *
 * zz-e2e-ta may have no saved hierarchy levels, nodes, or transfer types —
 * the GETs for /hierarchy/config, /nodes, and /transfer-types are stubbed to
 * a deterministic empty state so every tab's "no data" copy always renders,
 * instead of skipping those checks. Every other GET reaches the real backend;
 * any non-GET /api/ request is aborted, recorded, and fails the test.
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/org-setup-i18n.spec.ts --project=chromium --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });

type Locale = "en" | "am";
type TabId = "levels" | "tree" | "positions" | "personnel" | "transfer-types" | "approval" | "branding";

const TAB_ORDER: TabId[] = ["levels", "tree", "positions", "personnel", "transfer-types", "approval", "branding"];

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

function fulfillJson(route: Route, data: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ success: true, data, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

interface WriteGuard { unstubbedWrites: string[] }

async function installWriteGuard(page: Page): Promise<WriteGuard> {
  const guard: WriteGuard = { unstubbedWrites: [] };
  await page.route((url) => url.pathname.startsWith("/api/"), (route: Route) => {
    const req = route.request();
    const method = req.method();
    const url2 = new URL(req.url());
    if (method === "GET" || method === "OPTIONS") return route.continue();
    if (method === "POST" && url2.pathname === "/api/v1/auth/token") return route.continue(); // real login
    guard.unstubbedWrites.push(`${method} ${url2.pathname}`);
    return route.abort();
  });
  return guard;
}

/** Deterministic empty state: no saved levels, no nodes, no active transfer
 * types — every "no data" copy added in P3 renders regardless of what
 * zz-e2e-ta actually has configured. */
async function stubEmptyOrgData(page: Page) {
  await page.route("**/api/v1/tenants/*/hierarchy/config", (route) => {
    if (route.request().method() === "GET") return fulfillJson(route, []);
    return route.continue();
  });
  await page.route("**/api/v1/tenants/*/nodes*", (route) => {
    if (route.request().method() === "GET") return fulfillJson(route, []);
    return route.continue();
  });
  await page.route("**/api/v1/tenants/*/transfer-types", (route) => {
    if (route.request().method() === "GET") return fulfillJson(route, []);
    return route.continue();
  });
}

/** Raw i18n keys must never be visible text. */
const RAW_KEY = /^[a-z_]+\.[a-z_.]+$/;

// Each element's OWN text (its direct text nodes only, not its children's) —
// avoids the parent/child duplication a plain textContent walk would produce,
// and keeps each rendered string (a button label, an <option>, …) as its own
// array entry instead of one giant concatenated blob.
async function pageTexts(page: Page): Promise<string[]> {
  return page.$$eval("div.p-8.max-w-5xl *", (els) =>
    els.map((el) => {
      let own = "";
      for (const node of Array.from(el.childNodes)) {
        if (node.nodeType === Node.TEXT_NODE) own += node.textContent ?? "";
      }
      return own.trim();
    }).filter((t) => t.length > 0)
  );
}

interface Ctx { errors: Collected; guard: WriteGuard }

async function open(page: Page, locale: Locale): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const errors = collectErrors(page);
  const guard = await installWriteGuard(page);
  await stubEmptyOrgData(page);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
  await page.waitForLoadState("networkidle");
  return { errors, guard };
}

async function finish(page: Page, ctx: Ctx, label: string) {
  expect(ctx.errors.pageErrors, `no page errors (${label})`).toEqual([]);
  expect(ctx.guard.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  console.log(`--- ${label} console errors ---`);
  for (const e of ctx.errors.console) console.log(e);
  for (const e of ctx.errors.pageErrors) console.log(`[pageerror] ${e}`);
  expect(ctx.errors.console, `zero console errors (${label})`).toHaveLength(0);
}

function tabButton(page: Page, idx: number) {
  return page.locator("div.border-b.mb-6 > button").nth(idx);
}

async function clickTab(page: Page, tab: TabId) {
  await tabButton(page, TAB_ORDER.indexOf(tab)).click();
  await page.waitForLoadState("networkidle");
}

/** English values of the P3 keys that render on each tab with zero data,
 * independent of the key's dynamic placeholders. */
function p3NoDataStrings(en: Record<string, Record<string, string>>): Record<TabId, string[]> {
  return {
    levels: [
      en.org_setup.tab_levels,
      en.org_setup.table_level_name,
      en.org_setup.table_role,
      en.org_setup.table_holds_stock,
    ],
    tree: [en.org_setup.tab_tree, en.org_setup.add_root_node],
    positions: [en.org_setup.no_nodes_for_positions],
    personnel: [],
    "transfer-types": [],
    approval: [en.org_setup.no_active_transfer_types],
    branding: [],
  };
}

/* ── O1: am — no English value of a P3 no-data key is visible, per tab ──────── */
test("am: no English P3 string is visible on any Org Setup tab (O1)", async ({ page }) => {
  const ctx = await open(page, "am");
  const en = readLocale("en");
  const expectedEnglish = p3NoDataStrings(en);

  for (const tab of TAB_ORDER) {
    await clickTab(page, tab);
    const texts = await pageTexts(page);
    for (const english of expectedEnglish[tab]) {
      expect(texts, `tab "${tab}" must not show English "${english}" in am`).not.toContain(english);
    }
  }

  await finish(page, ctx, "O1 am");
});

/* ── O2: en + am — no raw i18n key is ever visible, on any tab ──────────────── */
for (const locale of ["en", "am"] as const) {
  test(`${locale}: no raw i18n key is visible on any Org Setup tab (O2)`, async ({ page }) => {
    const ctx = await open(page, locale);

    for (const tab of TAB_ORDER) {
      await clickTab(page, tab);
      const texts = await pageTexts(page);
      for (const txt of texts) {
        expect(txt, `tab "${tab}" (${locale}) text is not a raw i18n key: "${txt}"`).not.toMatch(RAW_KEY);
      }
    }

    await finish(page, ctx, `O2 ${locale}`);
  });
}

/* ── O3: am — Levels tab role dropdown shows am role labels, not English ────── */
test("am: Levels tab role dropdown shows am role labels, not English (O3)", async ({ page }) => {
  const ctx = await open(page, "am");
  const en = readLocale("en");
  const am = readLocale("am");

  await clickTab(page, "levels");

  // No saved levels (stubbed to []) — every row renders its role as an
  // editable <select>, not read-only text, so the dropdown is always present.
  const roleSelect = page.locator("table select").first();
  await expect(roleSelect).toBeVisible({ timeout: 10_000 });

  const optionTexts = await roleSelect.locator("option").allTextContents();
  const joined = optionTexts.join(" | ");

  expect(joined, "am Levels role dropdown must not show English 'National Manager'")
    .not.toContain(en.roles.NM);
  expect(joined, "am Levels role dropdown must not show English 'Warehouse Manager'")
    .not.toContain(en.roles.WM);
  expect(joined, "am Levels role dropdown must show the am NM label").toContain(am.roles.NM);
  expect(joined, "am Levels role dropdown must show the am WM label").toContain(am.roles.WM);

  await finish(page, ctx, "O3 am");
});
