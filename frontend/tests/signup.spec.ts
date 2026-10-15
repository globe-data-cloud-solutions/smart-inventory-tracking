/**
 * Playwright E2E — Public sign-up (S7)
 *
 * Prerequisites:
 *   npx playwright install --with-deps
 *   npm run dev  (or the app must be running at BASE_URL)
 *   NEXT_PUBLIC_API_URL must point at a running gateway (sign-up is gateway-only).
 *
 * Every tenant this spec creates uses the zz-s7-e2e-<timestamp> slug/email
 * convention so it can be found and deactivated afterward.
 *
 * Run:
 *   npx playwright test tests/signup.spec.ts
 */

import { test, expect, type APIRequestContext } from "@playwright/test";
import { SA_EMAIL, saPassword } from "./helpers/sa-credentials";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function uniqueHandle(): string {
  return `zz-s7-e2e-${Date.now()}`;
}

// Every slug this spec creates a real tenant for — deactivated in afterAll.
const createdSlugs: string[] = [];

/** SA-only: resolve a tenant's UUID from its slug via the registry, then
 * deactivate it (soft delete — never a hard delete, per CLAUDE.md §8). */
async function deactivateBySlug(request: APIRequestContext, slug: string): Promise<void> {
  const saPw = saPassword();
  if (!saPw) {
    console.warn(`signup.spec cleanup skipped: E2E_SA_PASSWORD not set — could not deactivate ${slug}`);
    return;
  }
  const tokenResp = await request.post(`${API_BASE}/api/v1/auth/token`, {
    data: { email: SA_EMAIL, password: saPw },
  });
  if (!tokenResp.ok()) {
    console.warn(`signup.spec cleanup: SA login failed (${tokenResp.status()}) — could not deactivate ${slug}`);
    return;
  }
  const { access_token } = (await tokenResp.json()) as { access_token: string };
  const authHeaders = { Authorization: `Bearer ${access_token}` };

  const registryResp = await request.get(`${API_BASE}/api/v1/tenants/sa/registry`, { headers: authHeaders });
  if (!registryResp.ok()) {
    console.warn(`signup.spec cleanup: registry fetch failed (${registryResp.status()}) — could not deactivate ${slug}`);
    return;
  }
  const { data: tenants } = (await registryResp.json()) as { data: Array<{ id: string; slug: string }> };
  const tenant = tenants.find((t) => t.slug === slug);
  if (!tenant) {
    console.warn(`signup.spec cleanup: no tenant found for slug ${slug}`);
    return;
  }

  const deactivateResp = await request.patch(`${API_BASE}/api/v1/tenants/${tenant.id}/deactivate`, {
    headers: authHeaders,
  });
  if (!deactivateResp.ok() && deactivateResp.status() !== 422) {
    // 422 ALREADY_DEACTIVATED is fine — idempotent cleanup.
    console.warn(`signup.spec cleanup: deactivate failed for ${slug} (${deactivateResp.status()})`);
  }
}

test.afterAll(async ({ request }) => {
  for (const slug of createdSlugs) {
    await deactivateBySlug(request, slug);
  }
});

test.describe("Public sign-up", () => {
  test("packages render from the API", async ({ page }) => {
    await page.goto(`${BASE_URL}/signup`);
    await expect(page.getByText("Starter", { exact: true })).toBeVisible();
    await expect(page.getByText("Growth", { exact: true })).toBeVisible();
    await expect(page.getByText("Enterprise", { exact: true })).toBeVisible();
    // Monthly is the default period
    await expect(page.getByText(/115\.00\s*ETB/)).toBeVisible();
  });

  test("period toggle changes prices", async ({ page }) => {
    await page.goto(`${BASE_URL}/signup`);
    await expect(page.getByText(/115\.00\s*ETB/)).toBeVisible();
    await page.getByRole("button", { name: "Annual" }).click();
    await expect(page.getByText(/1,150\.00\s*ETB/)).toBeVisible();
  });

  test("required-field errors on step 2", async ({ page }) => {
    await page.goto(`${BASE_URL}/signup`);

    const starterCard = page.getByTestId("package-card-STARTER");
    await starterCard.getByRole("button", { name: "Select" }).click();
    await page.getByRole("button", { name: "Continue" }).click();

    // Submitting step 2 with everything empty should surface validation errors
    // rather than advancing to the summary step.
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Company name is required.")).toBeVisible();
    await expect(page.getByText("Enter a valid email address.")).toBeVisible();
    await expect(page.getByText("You must accept the terms to continue.")).toBeVisible();
  });

  async function fillStep2(
    page: import("@playwright/test").Page,
    handle: string
  ): Promise<string> {
    const email = `${handle}@probe.local`;
    await page.locator('input[name="company_name"]').fill(handle);
    await page.locator('input[name="slug"]').fill(handle);
    await page.locator('input[name="admin_full_name"]').fill("S7 E2E Probe");
    await page.locator('input[name="admin_email"]').fill(email);
    await page.locator('input[name="admin_password"]').fill("Test@2026");
    await page.locator('input[name="admin_password_confirm"]').fill("Test@2026");
    await page.locator('input[name="accept_terms"]').check();
    return email;
  }

  test("successful sign-up shows 'sign in with {email}'", async ({ page }) => {
    const handle = uniqueHandle();
    createdSlugs.push(handle);
    await page.goto(`${BASE_URL}/signup`);

    const starterCard = page.getByTestId("package-card-STARTER");
    await starterCard.getByRole("button", { name: "Select" }).click();
    await page.getByRole("button", { name: "Continue" }).click();

    const email = await fillStep2(page, handle);
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page.getByText("Review your details")).toBeVisible();
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByText("Your account is ready!")).toBeVisible();
    await expect(page.getByText(`Sign in with ${email} to get started.`)).toBeVisible();
  });

  test("duplicate email shows the DUPLICATE_EMAIL message", async ({ page }) => {
    const handle = uniqueHandle();
    createdSlugs.push(handle);
    await page.goto(`${BASE_URL}/signup`);

    const starterCard = page.getByTestId("package-card-STARTER");
    await starterCard.getByRole("button", { name: "Select" }).click();
    await page.getByRole("button", { name: "Continue" }).click();

    const email = await fillStep2(page, handle);
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Your account is ready!")).toBeVisible();

    // Second sign-up with the same email, different company/slug.
    await page.goto(`${BASE_URL}/signup`);
    const starterCard2 = page.getByTestId("package-card-STARTER");
    await starterCard2.getByRole("button", { name: "Select" }).click();
    await page.getByRole("button", { name: "Continue" }).click();

    await page.locator('input[name="company_name"]').fill(`${handle}-dup`);
    await page.locator('input[name="slug"]').fill(`${handle}-dup`);
    await page.locator('input[name="admin_full_name"]').fill("S7 E2E Probe");
    await page.locator('input[name="admin_email"]').fill(email);
    await page.locator('input[name="admin_password"]').fill("Test@2026");
    await page.locator('input[name="admin_password_confirm"]').fill("Test@2026");
    await page.locator('input[name="accept_terms"]').check();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByText("This email address is already in use.")).toBeVisible();
  });
});
