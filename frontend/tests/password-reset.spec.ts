/**
 * Playwright E2E — forgot/reset password (backend f6ca51a / frontend auth-ui)
 *
 * Covers:
 *   - forgot-password: submit shows the generic "sent" message; a mocked 429
 *     shows the rate-limited message
 *   - reset-password: no token shows the invalid state immediately; mismatched
 *     or too-short passwords are blocked client-side (no request sent); a
 *     mocked 200 shows success + link to /login; a mocked 400 shows invalid
 *     state + link to /forgot-password
 *   - login page shows the "Forgot password?" link, carrying the typed email
 *
 * All API calls are mocked via page.route() — the suite never spends the
 * real rate limit or changes a password.
 *
 * Run against both en and am locales. Chromium headless only, against
 * http://localhost:3000 — see CLAUDE.md §29 "Frontend verification".
 *
 * Run:
 *   npx playwright test tests/password-reset.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

// The app registers a PWA service worker (next.config.js /sw.js) whose fetch
// handler can serve/forward requests before page.route() ever sees them.
// Block it here so the mocked API responses below are deterministic.
test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    // Chromium logs any non-2xx fetch response itself as a devtools "error" —
    // that is the expected rejection path exercised by these tests, not an app bug.
    if (/Failed to load resource.*(401|400|429)/.test(msg.text())) return;
    lines.push(msg.text());
  });
  page.on("pageerror", (err) => lines.push(`[pageerror] ${err.message}`));
  return lines;
}

/** CORS headers so a route.fulfill() mock survives the browser's cross-origin check
 * when NEXT_PUBLIC_API_URL points at a different origin (e.g. localhost:8000). */
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "http://localhost:3000",
  "Access-Control-Allow-Credentials": "true",
};

async function setLocaleBeforeLoad(page: Page, locale: "en" | "am") {
  await page.addInitScript((loc) => {
    window.localStorage.setItem("locale", loc);
  }, locale);
}

function assertNoRawKeysOrObjects(bodyText: string) {
  expect(bodyText).not.toContain("[object Object]");
  expect(bodyText).not.toMatch(/\b(forgot_password|reset_password|login)\.[a-z_]+\b/);
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Forgot password (${locale})`, () => {
    test(`submit shows the generic sent message (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await page.route("**/api/v1/auth/forgot-password", (route) =>
        route.fulfill({ status: 202, contentType: "application/json", headers: CORS_HEADERS, body: JSON.stringify({ sent: true }) })
      );

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/forgot-password`);
      await page.fill('input[type="email"]', "someone@example.com");
      await page.click('button[type="submit"]');

      const sentBox = page.locator(".text-emerald-700");
      await expect(sentBox.first()).toBeVisible();
      const bodyText = await page.locator("body").innerText();
      assertNoRawKeysOrObjects(bodyText);

      expect(consoleErrors).toEqual([]);
    });

    test(`mocked 429 shows the rate-limited message (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await page.route("**/api/v1/auth/forgot-password", (route) =>
        route.fulfill({
          status: 429,
          contentType: "application/json",
          headers: CORS_HEADERS,
          body: JSON.stringify({ detail: { code: "RATE_LIMITED", message: "Too many attempts." } }),
        })
      );

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/forgot-password`);
      await page.fill('input[type="email"]', "someone@example.com");
      await page.click('button[type="submit"]');

      const amberBox = page.locator(".text-amber-800");
      await expect(amberBox.first()).toBeVisible();
      const bodyText = await page.locator("body").innerText();
      assertNoRawKeysOrObjects(bodyText);

      expect(consoleErrors).toEqual([]);
    });
  });

  test.describe(`Reset password (${locale})`, () => {
    test(`no token shows the invalid state immediately (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/reset-password`);

      const errorBox = page.locator(".text-red-700");
      await expect(errorBox.first()).toBeVisible();
      const bodyText = await page.locator("body").innerText();
      assertNoRawKeysOrObjects(bodyText);

      expect(consoleErrors).toEqual([]);
    });

    test(`mismatched passwords are blocked client-side (${locale})`, async ({ page }) => {
      let requestSent = false;
      await page.route("**/api/v1/auth/reset-password", (route) => {
        requestSent = true;
        return route.continue();
      });

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/reset-password?token=abc123`);
      await page.fill('input[type="password"] >> nth=0', "Password1");
      await page.fill('input[type="password"] >> nth=1', "Password2");
      await page.click('button[type="submit"]');
      await page.waitForTimeout(300);

      expect(requestSent).toBe(false);
      const bodyText = await page.locator("body").innerText();
      assertNoRawKeysOrObjects(bodyText);
    });

    test(`too-short password is blocked client-side (${locale})`, async ({ page }) => {
      let requestSent = false;
      await page.route("**/api/v1/auth/reset-password", (route) => {
        requestSent = true;
        return route.continue();
      });

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/reset-password?token=abc123`);
      await page.fill('input[type="password"] >> nth=0', "short");
      await page.fill('input[type="password"] >> nth=1', "short");
      await page.click('button[type="submit"]');
      await page.waitForTimeout(300);

      expect(requestSent).toBe(false);
    });

    test(`mocked 200 shows success + link to login (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await page.route("**/api/v1/auth/reset-password", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", headers: CORS_HEADERS, body: JSON.stringify({ reset: true }) })
      );

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/reset-password?token=abc123`);
      await page.fill('input[type="password"] >> nth=0', "NewPassword1");
      await page.fill('input[type="password"] >> nth=1', "NewPassword1");
      await page.click('button[type="submit"]');

      const successBox = page.locator(".text-emerald-700");
      await expect(successBox.first()).toBeVisible();
      await expect(page.locator('a[href="/login"]')).toBeVisible();
      const bodyText = await page.locator("body").innerText();
      assertNoRawKeysOrObjects(bodyText);

      expect(consoleErrors).toEqual([]);
    });

    test(`mocked 400 shows invalid state + link to forgot-password (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await page.route("**/api/v1/auth/reset-password", (route) =>
        route.fulfill({
          status: 400,
          contentType: "application/json",
          headers: CORS_HEADERS,
          body: JSON.stringify({ detail: { code: "INVALID_OR_EXPIRED_TOKEN", message: "Invalid or expired token." } }),
        })
      );

      await setLocaleBeforeLoad(page, locale);
      await page.goto(`${BASE_URL}/reset-password?token=abc123`);
      await page.fill('input[type="password"] >> nth=0', "NewPassword1");
      await page.fill('input[type="password"] >> nth=1', "NewPassword1");
      await page.click('button[type="submit"]');

      const errorBox = page.locator(".text-red-700");
      await expect(errorBox.first()).toBeVisible();
      await expect(page.locator('a[href="/forgot-password"]')).toBeVisible();
      const bodyText = await page.locator("body").innerText();
      assertNoRawKeysOrObjects(bodyText);

      expect(consoleErrors).toEqual([]);
    });
  });
}

test.describe("Login page forgot-password link", () => {
  test("shows the forgot link and it carries the typed email", async ({ page }) => {
    await setLocaleBeforeLoad(page, "en");
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[type="email"]', "someone@example.com");

    const link = page.locator('a[href*="/forgot-password"]');
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/forgot-password?email=someone%40example.com");
  });
});
