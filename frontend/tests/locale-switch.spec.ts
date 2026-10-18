/**
 * Playwright E2E — Oromo hidden from every locale picker (session 19, prompt P5b).
 *
 *   L1 The header language switcher shows exactly the en and am options
 *      (no "Afaan Oromoo"/"OR").
 *   L2 With localStorage locale = "or" before load, the app renders English
 *      (resolveLocale fallback) — document.documentElement.lang stays "en".
 *   L3 /signup (no login) language picker and default-language select show
 *      no Oromo option.
 *
 * NO LIVE WRITES. Login (POST /api/v1/auth/token) and the session are real,
 * using the permanent zz-e2e-ta TA probe account. GET requests reach the real
 * backend; any other non-GET /api/ request is aborted, recorded, and fails
 * the test in finish().
 *
 * Chromium headless only, serviceWorkers blocked, one worker. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/locale-switch.spec.ts --project=chromium --workers=1
 */
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });
test.describe.configure({ mode: "default" });

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

interface Ctx { errors: Collected; guard: WriteGuard }

function finish(ctx: Ctx, label: string) {
  expect(ctx.errors.pageErrors, `no page errors (${label})`).toEqual([]);
  expect(ctx.guard.unstubbedWrites, "no write reached an unstubbed /api/ path").toEqual([]);
  console.log(`--- ${label} console errors ---`);
  for (const e of ctx.errors.console) console.log(e);
  for (const e of ctx.errors.pageErrors) console.log(`[pageerror] ${e}`);
  expect(ctx.errors.console, `zero console errors (${label})`).toHaveLength(0);
}

async function login(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(admin|[a-z0-9-]+)\/dashboard/);
}

/** Lang-switcher buttons render t(`lang.${code}`) — "EN"/"AM"/"OR" — and nothing else. */
async function headerLangCodes(page: Page): Promise<string[]> {
  return page.$$eval("header button", (btns) =>
    btns
      .map((b) => (b.textContent ?? "").trim())
      .filter((t) => /^(EN|AM|OR)$/.test(t))
  );
}

/* ── L1: header switcher shows exactly en + am ───────────────────────────── */
test("L1: header language switcher shows exactly en and am (no Oromo)", async ({ page }) => {
  const taPassword = e2eTaPasswordOrSkip(test);
  const errors = collectErrors(page);
  const guard = await installWriteGuard(page);

  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/dashboard`);
  await page.waitForLoadState("networkidle");

  const codes = await headerLangCodes(page);
  expect(codes, "header language switcher options").toEqual(["EN", "AM"]);

  finish({ errors, guard }, "L1");
});

/* ── L2: localStorage locale="or" before load renders English ───────────── */
test("L2: stored locale=or before load falls back to English", async ({ page }) => {
  const taPassword = e2eTaPasswordOrSkip(test);
  const errors = collectErrors(page);
  const guard = await installWriteGuard(page);

  await page.addInitScript(() => window.localStorage.setItem("locale", "or"));
  await login(page, E2E_TA_EMAIL, taPassword);
  await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/dashboard`);
  await page.waitForLoadState("networkidle");

  expect(await page.evaluate(() => localStorage.getItem("locale")), "locale is still stored as or").toBe("or");
  expect(await page.evaluate(() => document.documentElement.lang), "resolved render locale falls back to en").toBe("en");

  const codes = await headerLangCodes(page);
  expect(codes, "header language switcher options").toEqual(["EN", "AM"]);

  finish({ errors, guard }, "L2");
});

/* ── L3: /signup (no login) shows no Oromo option ────────────────────────── */
test("L3: signup language picker and default-language select show no Oromo", async ({ page }) => {
  const errors = collectErrors(page);
  const guard = await installWriteGuard(page);

  await page.goto(`${BASE_URL}/signup`);
  await page.waitForLoadState("networkidle");

  const pickerCodes = await page.$$eval("button", (btns) =>
    btns
      .map((b) => (b.textContent ?? "").trim())
      .filter((t) => /^(EN|AM|OR)$/.test(t))
  );
  expect(pickerCodes, "signup page language picker options").toEqual(["EN", "AM"]);

  const starterCard = page.locator('[data-testid="package-card-STARTER"] button').first();
  await expect(starterCard).toBeVisible({ timeout: 10_000 });
  await starterCard.click();
  await page.getByRole("button", { name: "Continue" }).click();

  const localeSelect = page.locator("select").filter({ has: page.locator('option[value="en"]') }).first();
  await expect(localeSelect).toBeVisible();
  const selectValues = await localeSelect.locator("option").evaluateAll((opts) =>
    opts.map((o) => (o as HTMLOptionElement).value)
  );
  expect(selectValues, "signup default-language select options").toEqual(["en", "am"]);

  finish({ errors, guard }, "L3");
});
