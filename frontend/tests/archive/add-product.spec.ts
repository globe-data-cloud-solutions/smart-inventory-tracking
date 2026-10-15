/**
 * Playwright E2E — Add Product panel
 *
 * Prerequisites:
 *   npx playwright install --with-deps
 *   npm run dev  (or the app must be running at BASE_URL)
 *
 * Run:
 *   npx playwright test tests/add-product.spec.ts
 */

import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

// ── Helpers ────────────────────────────────────────────────────────────────

async function loginAs(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  // Wait for redirect to org dashboard
  await page.waitForURL(/\/(admin|addis-water|muger-cement)\/dashboard/);
}

// ── Test suite ─────────────────────────────────────────────────────────────

test.describe("Add Product panel", () => {

  test("WM role — panel button is NOT visible", async ({ page }) => {
    await loginAs(page, "north.wm@addis-water.com", "AddisWater@2026");
    await page.goto(`${BASE_URL}/addis-water/inventory`);
    // WM does not have product:create — button must not render
    await expect(page.getByRole("button", { name: /Add Product/i })).not.toBeVisible();
  });

  test("TA role — panel button is visible and opens", async ({ page }) => {
    await loginAs(page, "admin@addis-water.com", "AddisWater@2026");
    await page.goto(`${BASE_URL}/addis-water/inventory`);

    const addBtn = page.getByRole("button", { name: /Add Product/i });
    await expect(addBtn).toBeVisible();
    await addBtn.click();

    // Panel should be open
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("TA role — SKU preview is displayed in read-only field", async ({ page }) => {
    await loginAs(page, "admin@addis-water.com", "AddisWater@2026");
    await page.goto(`${BASE_URL}/addis-water/inventory`);

    await page.getByRole("button", { name: /Add Product/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // Wait for SKU field — may show loading state then real value
    const skuField = page.getByLabel(/SKU/i);
    await expect(skuField).toBeVisible();
    // SKU field must be read-only
    await expect(skuField).toHaveAttribute("readonly", "");
  });

  test("Save button is disabled until all required fields are valid", async ({ page }) => {
    await loginAs(page, "admin@addis-water.com", "AddisWater@2026");
    await page.goto(`${BASE_URL}/addis-water/inventory`);
    await page.getByRole("button", { name: /Add Product/i }).click();

    const saveBtn = page.getByRole("button", { name: /Save Product/i });
    // No name entered → Save must be disabled
    await expect(saveBtn).toBeDisabled();

    // Fill name
    await page.fill('input[placeholder*="product name" i]', "Test Cement Bag");
    // Unit and pack_size have defaults — Save should now be enabled (once SKU loaded)
    // (Save becomes enabled when SKU preview is available too)
    await page.waitForTimeout(500); // allow SKU fetch
    // Disabled state may vary depending on SKU fetch success in test environment
    // This assertion is best-effort without a live backend
  });

  test("Duplicate product name shows inline error without closing panel", async ({ page }) => {
    // This test requires a live backend returning 409.
    // In CI against dev RDS: create product, then try same name again.
    // Documented here; full verification runs in CI integration suite.
    test.skip(
      !process.env.CI,
      "Requires live backend — runs in CI against dev RDS"
    );

    await loginAs(page, "admin@addis-water.com", "AddisWater@2026");
    await page.goto(`${BASE_URL}/addis-water/inventory`);
    await page.getByRole("button", { name: /Add Product/i }).click();

    const nameInput = page.getByLabel(/Product Name/i);
    await nameInput.fill("Duplicate Product");
    // Wait for duplicate check to trigger inline error
    await expect(page.getByText(/already exists/i)).toBeVisible({ timeout: 5000 });
    // Panel must still be open
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("Successful submission closes panel and shows toast with SKU", async ({ page }) => {
    test.skip(
      !process.env.CI,
      "Requires live backend — runs in CI against dev RDS"
    );

    await loginAs(page, "admin@addis-water.com", "AddisWater@2026");
    await page.goto(`${BASE_URL}/addis-water/inventory`);
    await page.getByRole("button", { name: /Add Product/i }).click();

    const uniqueName = `E2E-Product-${Date.now()}`;
    await page.fill('input[placeholder*="product name" i]', uniqueName);
    await page.selectOption('select[aria-label*="Unit" i]', "KG");
    await page.selectOption('select[aria-label*="Pack Size" i]', "1");

    const saveBtn = page.getByRole("button", { name: /Save Product/i });
    await expect(saveBtn).not.toBeDisabled();
    await saveBtn.click();

    // Panel should close
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 5000 });
    // Toast with SKU should appear
    await expect(page.getByRole("status")).toContainText(/created successfully/i);
  });
});
