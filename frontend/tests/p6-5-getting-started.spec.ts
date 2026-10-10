/**
 * Playwright E2E — P6.5: public Getting Started page, landing/signup/login
 * links, Help manifest entry, and sign-up help text (CLAUDE.md §29).
 *
 * No session anywhere in this file except the one TA login needed to check
 * the in-app Help page listing. No form is ever submitted against the live
 * backend. No SA credentials.
 *
 * Chromium headless only, against http://localhost:3000. Run (foreground):
 *   npx playwright test tests/p6-5-getting-started.spec.ts --reporter=line
 */
import fs from "fs";
import path from "path";
import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.setTimeout(60_000);
test.use({ serviceWorkers: "block" });

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (/Failed to load resource.*40[0-9]/.test(msg.text())) return;
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

function localeStrings(locale: "en" | "am") {
  const raw = fs.readFileSync(path.join(__dirname, "..", "..", "locales", `${locale}.json`), "utf-8");
  const d = JSON.parse(raw);
  return {
    pageTitle: d.getting_started.title as string,
    printBtn: d.getting_started.print_btn as string,
    createAccountCta: d.getting_started.cta_create_account as string,
    helpDocTitle: d.help.doc.getting_started.title as string,
    navLink: d.landing.nav.getting_started as string,
    heroLink: d.landing.hero.cta_getting_started as string,
    loginLink: d.login.getting_started_link as string,
    signupNote: d.signup.getting_started_note as string,
    billingHint: d.signup.billing_period_hint as string,
    packageHint: d.signup.package_hint as string,
    orgTypeHint: d.signup.org_type_hint as string,
    slugPermanentHint: d.signup.slug_permanent_hint as string,
    languageHint: d.signup.language_hint as string,
  };
}

// ── /getting-started: loads with no session, sections render, CTA -> /signup ──
for (const locale of ["en", "am"] as const) {
  test.describe(`Public Getting Started page (${locale})`, () => {
    test(`loads without a session, renders sections, CTA goes to /signup (${locale})`, async ({ page }) => {
      const strings = localeStrings(locale);
      const consoleErrors = collectConsoleErrors(page);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await page.goto(`${BASE_URL}/getting-started`);
      await page.waitForLoadState("networkidle");

      // The document's own h1 and section headings are sourced from the .md
      // file (English-only content, same in every UI locale) — deterministic
      // regardless of locale-load timing, unlike the page chrome's t()-driven
      // title/buttons (lib/i18n.ts's module-level `translations` only updates
      // async; a page with little reactive state after mount, like this one,
      // can still be showing the English fallback by the time this runs).
      await expect(page.getByRole("heading", { name: "SMART Inventory — Getting Started", level: 1 })).toBeVisible({ timeout: 10_000 });
      await expect(page.getByRole("heading", { name: "Before You Begin" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Choices you make at sign-up" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "What happens after you submit" })).toBeVisible();

      // Page-chrome strings: accept either language since the locale may not
      // have finished loading yet (see note above) — the point of this
      // assertion is that the controls render and work, in either language.
      const printBtnRe = new RegExp(`${strings.printBtn}|Printable checklist`);
      await expect(page.getByRole("button", { name: printBtnRe })).toBeVisible();

      const ctaRe = new RegExp(`${strings.createAccountCta}|Create an account`);
      const cta = page.getByRole("link", { name: ctaRe });
      await expect(cta).toBeVisible();
      await cta.click();
      await page.waitForURL(/\/signup/);

      console.log(`--- /getting-started (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors (${locale})`).toHaveLength(0);
    });
  });
}

// ── Mobile width: no horizontal scroll on /getting-started ────────────────
test.describe("Mobile viewport", () => {
  test("375px wide: no horizontal scroll on /getting-started", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(`${BASE_URL}/getting-started`);
    await page.waitForLoadState("networkidle");

    const hasHorizontalScroll = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
    );
    expect(hasHorizontalScroll, "no horizontal scroll at 375px").toBe(false);
  });
});

// ── Landing / signup / login links ─────────────────────────────────────────
test.describe("Links from landing, signup, login", () => {
  test("landing page has a nav link and a hero secondary link", async ({ page }) => {
    const strings = localeStrings("en");
    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState("networkidle");

    await expect(page.locator("nav a.nav-link", { hasText: strings.navLink })).toHaveAttribute("href", "/getting-started");
    await expect(page.locator("a.btn-hero-outline", { hasText: strings.heroLink })).toHaveAttribute("href", "/getting-started");
  });

  test("login page footer has a Getting started link", async ({ page }) => {
    const strings = localeStrings("en");
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("link", { name: strings.loginLink })).toHaveAttribute("href", "/getting-started");
  });

  test("signup page shows the top note and the 5 field help texts", async ({ page }) => {
    const strings = localeStrings("en");
    const consoleErrors = collectConsoleErrors(page);

    await page.goto(`${BASE_URL}/signup`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("link", { name: strings.signupNote })).toHaveAttribute("href", "/getting-started");

    // Step 1 help texts (billing period, package) — visible once the
    // package catalog has loaded.
    await expect(page.getByText(strings.billingHint)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(strings.packageHint)).toBeVisible();

    // Advance to step 2 (client-side only — selecting a tier and clicking
    // Continue never submits the sign-up form) to check the remaining
    // three help texts.
    const starterCard = page.locator('[data-testid="package-card-STARTER"]');
    if (await starterCard.isVisible().catch(() => false)) {
      await starterCard.getByRole("button", { name: /Select/i }).click();
      await page.getByRole("button", { name: "Continue" }).click();

      await expect(page.getByText(strings.orgTypeHint)).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(strings.slugPermanentHint)).toBeVisible();
      await expect(page.getByText(strings.languageHint)).toBeVisible();
    } else {
      test.skip(true, "package catalog did not load (gateway mode required) — step 2 help texts not checked");
    }

    console.log("--- /signup help text console errors ---");
    for (const e of consoleErrors) console.log(e);
    expect(consoleErrors, "zero console errors").toHaveLength(0);
  });
});

// ── In-app Help page lists Getting Started (TA) ─────────────────────────────
test.describe("Help page manifest entry", () => {
  test("Help page lists Getting Started for a TA", async ({ page }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const strings = localeStrings("en");

    await login(page, E2E_TA_EMAIL, taPassword);
    await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/help`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(strings.helpDocTitle).first()).toBeVisible({ timeout: 10_000 });
  });
});
