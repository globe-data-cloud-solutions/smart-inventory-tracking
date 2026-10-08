/**
 * Playwright E2E — email/password login (backend 68b3cf8 / frontend auth-ui)
 *
 * Covers the single POST /api/v1/auth/token {email, password} login path:
 *   - SA success lands on the SA dashboard with a JWT in the stored session
 *   - wrong password shows a generic invalid-credentials message (no raw key,
 *     no "[object Object]")
 *   - an empty password is blocked client-side (no request is ever sent)
 *   - the permanent E2E TA account logs in to its own tenant dashboard
 *     (skipped with a clear message when E2E_TA_PASSWORD is unset)
 *
 * Run against both en and am locales. Chromium headless only, against
 * http://localhost:3000 — see CLAUDE.md §29 "Frontend verification".
 *
 * Run:
 *   npx playwright test tests/auth-login.spec.ts
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { SA_EMAIL, SA_PASSWORD } from "./helpers/sa-credentials";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    // Chromium logs the 401 fetch response itself as a devtools "error" —
    // that is the expected invalid-credentials flow, not an app bug.
    if (/Failed to load resource.*401/.test(msg.text())) return;
    lines.push(msg.text());
  });
  page.on("pageerror", (err) => lines.push(`[pageerror] ${err.message}`));
  return lines;
}

/** Set the stored UI locale before the page's providers mount and load it. */
async function setLocaleBeforeLoad(page: Page, locale: "en" | "am") {
  await page.addInitScript((loc) => {
    window.localStorage.setItem("locale", loc);
  }, locale);
}

async function gotoLogin(page: Page, locale: "en" | "am") {
  await setLocaleBeforeLoad(page, locale);
  await page.goto(`${BASE_URL}/login`);
}

for (const locale of ["en", "am"] as const) {
  test.describe(`Email/password login (${locale})`, () => {
    test(`SA login succeeds and lands on the SA dashboard (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);

      await gotoLogin(page, locale);
      await page.fill('input[type="email"]', SA_EMAIL);
      await page.fill('input[type="password"]', SA_PASSWORD);
      await page.click('button[type="submit"]');

      await page.waitForURL(/\/admin\/dashboard/);

      const session = await page.evaluate(() => {
        const raw = window.localStorage.getItem("smart_demo_session");
        return raw ? (JSON.parse(raw) as { jwtToken?: string; role?: string }) : null;
      });
      expect(session?.jwtToken).toBeTruthy();
      expect(session?.role).toBe("SA");

      expect(consoleErrors).toEqual([]);
    });

    test(`wrong password shows a generic invalid-credentials message (${locale})`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);

      await gotoLogin(page, locale);
      await page.fill('input[type="email"]', SA_EMAIL);
      await page.fill('input[type="password"]', "definitely-wrong-password");
      await page.click('button[type="submit"]');

      // Wait for the request/response round-trip (300ms artificial delay +
      // network) to resolve into the rendered error box before asserting.
      const errorBox = page.locator(".text-red-700, .text-red-600");
      await expect(errorBox.first()).toBeVisible();

      // Generic message — never account-enumerating, never a raw i18n key,
      // never a stringified error object.
      const bodyText = await page.locator("body").innerText();
      expect(bodyText).not.toMatch(/\blogin\.[a-z_]+\b/);
      expect(bodyText).not.toContain("[object Object]");
      expect(bodyText.toLowerCase()).toMatch(/invalid|ልክ አይደለም/);

      // Still on the login page — no session was created.
      await expect(page).toHaveURL(/\/login/);
      const session = await page.evaluate(() => window.localStorage.getItem("smart_demo_session"));
      expect(session).toBeNull();

      expect(consoleErrors).toEqual([]);
    });

    test(`empty password is blocked client-side — no request is sent (${locale})`, async ({ page }) => {
      let authRequestSent = false;
      await page.route("**/api/v1/auth/token", (route) => {
        authRequestSent = true;
        return route.continue();
      });

      await gotoLogin(page, locale);
      await page.fill('input[type="email"]', SA_EMAIL);
      // Leave password empty — the field is `required`, so the browser blocks
      // submission natively and the form handler never runs.
      await page.click('button[type="submit"]');
      await page.waitForTimeout(500);

      expect(authRequestSent).toBe(false);
      await expect(page).toHaveURL(/\/login/);
    });
  });
}

test.describe("E2E TA login", () => {
  test("permanent E2E TA account logs in to its own tenant dashboard", async ({ page }) => {
    const password = e2eTaPasswordOrSkip(test);
    const consoleErrors = collectConsoleErrors(page);

    await gotoLogin(page, "en");
    await page.fill('input[type="email"]', E2E_TA_EMAIL);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');

    await page.waitForURL(/\/[a-z0-9-]+\/dashboard/);
    await expect(page).not.toHaveURL(/\/admin\/dashboard/);

    const session = await page.evaluate(() => {
      const raw = window.localStorage.getItem("smart_demo_session");
      return raw ? (JSON.parse(raw) as { jwtToken?: string; role?: string }) : null;
    });
    expect(session?.jwtToken).toBeTruthy();
    expect(session?.role).toBe("TA");

    expect(consoleErrors).toEqual([]);
  });
});
