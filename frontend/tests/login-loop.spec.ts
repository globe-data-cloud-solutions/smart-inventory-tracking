/**
 * Playwright E2E — /login must not redirect-loop when localStorage holds an expired
 * session. /login renders PublicContactLink -> useContactInfo, which used to call the
 * public contact endpoint through api.get; the pre-flight expiry branch redirected to
 * /login without clearing the stale token, looping with an ever-nesting `from`.
 *
 *   L1 expired stored session, locale en: stays on /login, session_expired appears at
 *      most once, login form visible, public contact request carries no Authorization.
 *   L2 same under locale am.
 *
 * No writes, no credentials. Chromium headless only, against http://localhost:3000. Run:
 *   cd frontend && npx playwright test tests/login-loop.spec.ts --project=chromium --workers=1
 */
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });

function b64url(obj: unknown): string {
  return Buffer.from(JSON.stringify(obj)).toString("base64url");
}

/** Unsigned JWT whose exp is one hour in the past. */
function expiredJwt(): string {
  const exp = Math.floor(Date.now() / 1000) - 3600;
  return `${b64url({ alg: "none", typ: "JWT" })}.${b64url({ sub: "e2e-expired", exp })}.sig`;
}

function collectErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    if (/Failed to load resource.*4\d\d/.test(msg.text())) return;
    lines.push(msg.text());
  });
  page.on("pageerror", (err) => lines.push(`[pageerror] ${err.message}`));
  return lines;
}

for (const locale of ["en", "am"] as const) {
  test(`login does not loop with an expired stored session (locale ${locale})`, async ({ page }) => {
    const errors = collectErrors(page);
    const contactAuth: Array<string | undefined> = [];
    page.on("request", (req) => {
      if (req.url().includes("/tenants/public/contact")) {
        contactAuth.push(req.headers()["authorization"]);
      }
    });

    const session = {
      orgSlug: "zz-e2e-ta",
      role: "TENANT_ADMIN",
      tenantId: "00000000-0000-0000-0000-000000000001",
      jwtToken: expiredJwt(),
    };
    await page.addInitScript(
      ([loc, sess]) => {
        window.localStorage.setItem("locale", loc);
        window.localStorage.setItem("smart_demo_session", sess);
      },
      [locale, JSON.stringify(session)] as const,
    );

    await page.goto(`${BASE_URL}/login?reason=session_expired`);
    await page.waitForTimeout(3000);

    const url = new URL(page.url());
    expect(url.pathname).toBe("/login");
    const occurrences = (decodeURIComponent(page.url()).match(/session_expired/g) ?? []).length;
    expect(occurrences, `session_expired occurrences in ${page.url()}`).toBeLessThanOrEqual(1);
    await expect(page.locator("form").first()).toBeVisible();
    await expect(page.locator('input[type="password"]').first()).toBeVisible();
    expect(
      contactAuth.filter((a) => !!a),
      "public contact request must not carry Authorization",
    ).toHaveLength(0);

    console.log(`--- ${locale} contact requests: ${contactAuth.length}; final URL: ${page.url()} ---`);
    console.log(`--- ${locale} console errors ---`);
    for (const e of errors) console.log(e);
    console.log(`--- end (${errors.length}) ---`);
  });
}
