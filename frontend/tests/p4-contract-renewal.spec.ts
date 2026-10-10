/**
 * Playwright E2E — P4: contract read-only/plan-limit messages, contract
 * banners, and the TA renewal request card (CLAUDE.md §29).
 *
 * zz-e2e-ta (STARTER, contract stage ACTIVE) is the permanent TA probe —
 * never mutated here. The GRACE/READ_ONLY banner cases and the
 * CONTRACT_EXPIRED_READ_ONLY write-error case use page.route interception
 * ONLY inside this spec to simulate those stages; nothing is faked in app
 * code and nothing is submitted against the real backend for those cases
 * (the intercepted route never reaches the network).
 *
 * The SA renewals panel is not covered here — no SA credentials in this
 * suite; Alex checks that by hand.
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/p4-contract-renewal.spec.ts --workers=1
 */
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);

// The app registers a service worker (frontend/src/app/layout.tsx) which can
// handle fetches inside its own worker thread, outside what page.route() can
// intercept — block it for this whole file so every mocked route below is
// guaranteed to catch the request instead of silently falling through to the
// real backend (critical for the 402 CONTRACT_EXPIRED_READ_ONLY test, which
// clicks a real submit button).
test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (/Failed to load resource.*402/.test(msg.text())) return; // expected plan-gate round-trip
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

const CONTRACT_STATUS_PATH = "**/api/v1/tenants/me/contract-status";
const RENEWAL_REQUESTS_PATH = "**/api/v1/tenants/me/renewal-requests";

function fulfillContractStatus(route: Route, data: Record<string, unknown>) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      success: true,
      data,
      request_id: "test-request-id",
      timestamp: new Date().toISOString(),
    }),
  });
}

// ── Baseline: ACTIVE stage shows no banner, Plan tab shows the Renewal card ──
for (const locale of ["en", "am"] as const) {
  test.describe(`Contract stage ACTIVE — TA zz-e2e-ta (${locale})`, () => {
    test(`no contract banner; Plan tab Renewal card with submit button (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.waitForLoadState("networkidle");

      // No grace/read-only banner on an ACTIVE-stage tenant.
      await expect(page.getByText(/workspace becomes read-only|read-only since|Read-only:/i)).toHaveCount(0);

      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=plan`);
      await page.waitForLoadState("networkidle");

      const renewalHeading = page.getByText(/^(Renewal|ማደስ)$/);
      await expect(renewalHeading).toBeVisible({ timeout: 10_000 });

      const submitBtn = page.getByRole("button", { name: /Request renewal|የማደስ ጥያቄ አቅርብ/i });
      // Either the submit form (no open request) or the "already requested"
      // notice is shown — never both missing. Do NOT click submit — a real
      // click here would create a live renewal request.
      const openNotice = page.getByText(/SMART will contact you|SMART ያገኝዎታል/i);
      await expect(submitBtn.or(openNotice)).toBeVisible({ timeout: 10_000 });

      await page.screenshot({ path: `test-results/p4/renewal-card-${locale}.png`, fullPage: true });

      console.log(`--- ACTIVE stage (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── GRACE / READ_ONLY banners via route interception ────────────────────────
for (const locale of ["en", "am"] as const) {
  test.describe(`Contract banners (intercepted) — TA zz-e2e-ta (${locale})`, () => {
    test(`GRACE stage renders amber banner with TA link (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(CONTRACT_STATUS_PATH, (route) =>
        fulfillContractStatus(route, {
          stage: "GRACE",
          contract_end: "2026-01-01",
          days_left: -5,
          grace_ends: "2026-01-15",
          read_only_since: "2026-01-16",
          open_request: null,
        })
      );

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText(/2026-01-01/).first()).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/2026-01-16/).first()).toBeVisible();
      await expect(page.getByRole("link", { name: /Request renewal|የማደስ ጥያቄ አቅርብ/i })).toBeVisible();

      await page.screenshot({ path: `test-results/p4/banner-grace-${locale}.png`, fullPage: true });

      console.log(`--- GRACE banner (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });

    test(`READ_ONLY stage renders red banner with TA link (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      await page.route(CONTRACT_STATUS_PATH, (route) =>
        fulfillContractStatus(route, {
          stage: "READ_ONLY",
          contract_end: "2026-01-01",
          days_left: -20,
          grace_ends: "2026-01-15",
          read_only_since: "2026-01-16",
          open_request: null,
        })
      );

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText(/2026-01-01/).first()).toBeVisible({ timeout: 10_000 });
      await expect(page.getByRole("link", { name: /Request renewal|የማደስ ጥያቄ አቅርብ/i })).toBeVisible();
      // Never the raw code or a plain HTTP status as visible text.
      await expect(page.getByText("CONTRACT_EXPIRED_READ_ONLY")).toHaveCount(0);
      await expect(page.getByText(/^HTTP 402$/)).toHaveCount(0);

      await page.screenshot({ path: `test-results/p4/banner-read-only-${locale}.png`, fullPage: true });

      console.log(`--- READ_ONLY banner (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── 402 CONTRACT_EXPIRED_READ_ONLY on a save -> friendly text, never raw ────
test.describe("CONTRACT_EXPIRED_READ_ONLY write error (intercepted)", () => {
  test("renewal-request submit shows friendly text, not 'HTTP 402'", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);

    // The renewal-request POST itself is intentionally allowed at any stage
    // on the real backend — this intercept exists purely to exercise the
    // generic 402 CONTRACT_EXPIRED_READ_ONLY -> friendly-message path in
    // lib/api.ts without depending on a real tenant actually being read-only.
    await page.route(RENEWAL_REQUESTS_PATH, (route) => {
      if (route.request().method() !== "POST") return route.continue();
      return route.fulfill({
        status: 402,
        contentType: "application/json",
        body: JSON.stringify({
          detail: {
            code: "CONTRACT_EXPIRED_READ_ONLY",
            action: "tenant:renewal_request",
            contract_end: "2026-01-01",
            read_only_since: "2026-01-16",
          },
        }),
      });
    });

    await login(page, E2E_TA_EMAIL, taPassword);
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin?tab=plan`);
    await page.waitForLoadState("networkidle");

    const submitBtn = page.getByRole("button", { name: "Request renewal" });
    // Only proceed if the submit form is showing (no OPEN request already on
    // file) — this is the intercepted path, so clicking never reaches the
    // real backend or creates a live request.
    if (await submitBtn.isVisible().catch(() => false)) {
      await submitBtn.click();
      await expect(
        page.getByText("Your contract has expired — the workspace is read-only. Contact SMART to renew.")
      ).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/HTTP 402/)).toHaveCount(0);
      await expect(page.getByText("[object Object]")).toHaveCount(0);
    } else {
      test.skip(true, "zz-e2e-ta already has an OPEN renewal request — submit form not shown");
    }
  });
});
