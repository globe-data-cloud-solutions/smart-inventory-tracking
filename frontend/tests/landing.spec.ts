/**
 * Playwright E2E — Landing page self sign-up (L1)
 *
 * Run:
 *   npx playwright test tests/landing.spec.ts
 */

import { test, expect } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

async function collectErrors(page: import("@playwright/test").Page): Promise<string[]> {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

test.describe("Landing page (en)", () => {
  test("hero, navbar and get-started render with no raw keys or console errors", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.goto(`${BASE_URL}/`);

    await expect(page.locator("h1")).toContainText("SMART Inventory");
    await expect(page.getByRole("link", { name: "Choose a plan" }).first()).toBeVisible();
    await expect(page.getByText("Start managing your inventory")).toBeVisible();

    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/landing\.[a-z_]+\.[a-z_]+/);

    expect(errors).toEqual([]);
  });

  test("navbar 'Get started' navigates to /signup", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);
    await page.locator("nav a.btn-nav-primary").click();
    await expect(page).toHaveURL(/\/signup$/);
  });

  test("hero 'Choose a plan' navigates to /signup", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);
    await page.getByRole("link", { name: "Choose a plan" }).first().click();
    await expect(page).toHaveURL(/\/signup$/);
  });

  test("get-started CTA navigates to /signup", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);
    await page.locator("#get-started").getByRole("link", { name: "Choose a plan" }).click();
    await expect(page).toHaveURL(/\/signup$/);
  });

  test("'Sign in' navigates to /login", async ({ page }) => {
    await page.goto(`${BASE_URL}/`);
    await page.getByRole("link", { name: "Sign in" }).first().click();
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe("Landing page (am)", () => {
  test("switch to AM changes hero heading with no raw keys", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.goto(`${BASE_URL}/`);

    const enSubtitle = await page.locator("h1 + p").innerText();

    const reloadPromise = page.waitForEvent("load");
    await page.getByRole("button", { name: "AM" }).click();
    await reloadPromise;

    await expect(page.locator("h1 + p")).not.toHaveText(enSubtitle);

    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/landing\.[a-z_]+\.[a-z_]+/);

    expect(errors).toEqual([]);
  });
});

test.describe("Landing page (mobile)", () => {
  test("no horizontal scroll at 375px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE_URL}/`);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(375);
  });

  test("language switcher is visible and AM switch works at 375px", async ({ page }) => {
    const errors = await collectErrors(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE_URL}/`);

    const switcherAm = page.locator("nav").getByRole("button", { name: "AM" });
    await expect(switcherAm).toBeVisible();

    const enSubtitle = await page.locator("h1 + p").innerText();
    const reloadPromise = page.waitForEvent("load");
    await switcherAm.click();
    await reloadPromise;

    await expect(page.locator("h1 + p")).not.toHaveText(enSubtitle);

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(375);

    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/landing\.[a-z_]+\.[a-z_]+/);

    expect(errors).toEqual([]);
  });
});
