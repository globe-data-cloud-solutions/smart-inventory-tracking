/**
 * Playwright E2E — Sidebar + header i18n labels (session 19, prompt P2).
 *
 * Covers, for en + am:
 *   N1 Sidebar link and section-header text comes from the locale pack: none is
 *      empty, none is a raw i18n key (pattern /^[a-z_]+\.[a-z_.]+$/).
 *   N2 (am) None of the visible sidebar texts equals its English value for the
 *      nav.* keys the sidebar actually uses (read from locales/en.json).
 *   N3 (am) The mobile hamburger button's aria-label is not the English
 *      "Toggle menu" string.
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real,
 * using the permanent zz-e2e-ta TA probe account. GET requests reach the real
 * backend; any other non-GET /api/ request is aborted, recorded, and fails
 * the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/nav-i18n.spec.ts --project=chromium --workers=1
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

function readLocale(locale: Locale) {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  return JSON.parse(raw);
}

// The nav.* keys the TENANT_NAV sidebar (TA role) actually renders, in order.
const USED_NAV_KEYS = [
  "section_inventory", "dashboard", "products", "warehouses", "lot_traceability",
  "section_operations", "inventory", "transfers", "adjustments", "stock_count",
  "section_reports", "analytics", "reports", "audit", "approval_policies",
  "settings", "org_setup", "personnel", "tenant_admin", "help_section", "help",
];

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

/** Raw i18n keys must never be visible text. */
const RAW_KEY = /^[a-z_]+\.[a-z_.]+$/;

async function sidebarTexts(page: Page): Promise<string[]> {
  return page.$$eval("aside nav > a, aside nav > p, aside nav > span", (els) =>
    els.map((el) => {
      const clone = el.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("span").forEach((s) => s.remove());
      return (clone.textContent ?? "").trim();
    }).filter((t) => t.length > 0)
  );
}

interface Ctx { errors: Collected; guard: WriteGuard }

async function open(page: Page, locale: Locale): Promise<Ctx> {
  const taPassword = e2eTaPasswordOrSkip(test);
  const errors = collectErrors(page);
  const guard = await installWriteGuard(page);

  await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/dashboard`);
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

/* ── N1: sidebar text comes from the locale pack, no raw keys, no empties ──── */
for (const locale of ["en", "am"] as const) {
  test(`sidebar link and section-header text comes from the ${locale} pack, no raw keys (N1)`, async ({ page }) => {
    const ctx = await open(page, locale);

    const texts = await sidebarTexts(page);
    expect(texts.length, "sidebar has rendered items").toBeGreaterThan(0);
    for (const txt of texts) {
      expect(txt.length, `sidebar text not empty: "${txt}"`).toBeGreaterThan(0);
      expect(txt, `sidebar text is not a raw i18n key: "${txt}"`).not.toMatch(RAW_KEY);
    }

    await finish(page, ctx, `N1 ${locale}`);
  });
}

/* ── N2: am sidebar text never equals the English value (used keys) ─────────── */
test("am sidebar text never equals the English nav.* value (N2)", async ({ page }) => {
  const ctx = await open(page, "am");
  const en = readLocale("en");
  const englishValues = USED_NAV_KEYS.map((k) => en.nav[k] as string);

  const texts = await sidebarTexts(page);
  for (const txt of texts) {
    expect(englishValues, `am sidebar text "${txt}" must not equal an English nav label`).not.toContain(txt);
  }

  await finish(page, ctx, "N2 am");
});

/* ── N3: am hamburger aria-label is not the English "Toggle menu" ───────────── */
test("am hamburger aria-label is not the English 'Toggle menu' (N3)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const ctx = await open(page, "am");
  const en = readLocale("en");

  const hamburger = page.locator("header button[aria-label]").first();
  await expect(hamburger).toBeVisible();
  const ariaLabel = await hamburger.getAttribute("aria-label");
  expect(ariaLabel, "hamburger aria-label must not be the English value").not.toBe(en.nav.toggle_menu);

  await finish(page, ctx, "N3 am");
});
