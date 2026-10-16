/**
 * Playwright E2E — P7b: a hard page load with a stored non-English locale renders
 * in that locale on first paint (Providers gates rendering until the locale pack
 * has loaded). Expected strings are read from locales/am.json and en.json.
 *
 *   H1 Login page, localStorage locale="am", hard load: labels are the am.json
 *      value and the English value is not visible.
 *   H2 zz-e2e-ta TA, locale="am", hard load of tenant-admin: the Contact tab label
 *      is the am.json value, not the English one.
 *
 * No writes. Chromium headless only, against http://localhost:3000. Run:
 *   set -a; source .env; set +a
 *   cd frontend && npx playwright test tests/locale-hard-load.spec.ts --project=chromium --workers=1
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });

function loadPack(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  return JSON.parse(raw);
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

test.describe("hard load with stored locale=am", () => {
  test("H1 login page labels are Amharic on first paint", async ({ page }) => {
    const errors = collectErrors(page);
    const en = loadPack("en");
    const am = loadPack("am");
    expect(am.login.email_label, "fixture: am differs from en").not.toBe(en.login.email_label);

    await page.addInitScript(() => window.localStorage.setItem("locale", "am"));
    await page.goto(`${BASE_URL}/login`);

    await expect(page.getByText(am.login.email_label as string, { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(am.login.password_label as string, { exact: true })).toBeVisible();
    await expect(page.getByText(en.login.email_label as string, { exact: true })).toHaveCount(0);
    await expect(page.getByText(en.login.password_label as string, { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.lang)).toBe("am");

    console.log("--- H1 console errors ---");
    for (const e of errors) console.log(e);
    expect(errors, "zero console errors").toHaveLength(0);
  });

  test("H2 TA settings tab label is Amharic on first paint", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const errors = collectErrors(page);
    const en = loadPack("en");
    const am = loadPack("am");
    const amTab = am.tenant_admin.tabs.contact as string;
    const enTab = en.tenant_admin.tabs.contact as string;
    expect(amTab, "fixture: am differs from en").not.toBe(enTab);

    await page.addInitScript(() => window.localStorage.setItem("locale", "am"));
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[type="email"]', E2E_TA_EMAIL);
    await page.fill('input[type="password"]', taPassword);
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/(admin|[a-z0-9-]+)\/dashboard/);

    // Hard load (full navigation), not a client-side route change.
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/tenant-admin`);

    const tabBar = page.locator("div.overflow-x-auto");
    await expect(tabBar.getByRole("button", { name: new RegExp(`^👥${amTab}$`) })).toBeVisible({ timeout: 10_000 });
    await expect(tabBar.getByRole("button", { name: new RegExp(`^👥${enTab}$`) })).toHaveCount(0);

    console.log("--- H2 console errors ---");
    for (const e of errors) console.log(e);
    expect(errors, "zero console errors").toHaveLength(0);
  });
});
