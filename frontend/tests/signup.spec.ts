/**
 * Playwright E2E — Public sign-up (S7)
 *
 * Fully stubbed: GET /api/v1/tenants/public/packages and
 * POST /api/v1/tenants/public/signup are intercepted and fulfilled in this
 * spec, so no real tenant is ever created and no cleanup (or SA account) is
 * needed. Fixture shapes mirror frontend/src/lib/billing-types.ts
 * (PackagesListOut) and the SignupOut model in
 * backend/services/tenant-service/routers/public_signup.py.
 *
 * Prerequisites:
 *   npx playwright install --with-deps
 *   npm run dev  (or the app must be running at BASE_URL)
 *   NEXT_PUBLIC_API_URL must be set (the sign-up page is gateway-only); no
 *   backend call actually reaches the gateway.
 *
 * Run:
 *   npx playwright test tests/signup.spec.ts
 */

import { test, expect, type Page, type Route } from "@playwright/test";
import type { PackagesListOut, PriceOut } from "../src/lib/billing-types";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

const PACKAGES_PATH = "**/api/v1/tenants/public/packages";
const SIGNUP_PATH = "**/api/v1/tenants/public/signup";
const PUBLIC_CONTACT_PATH = "**/api/v1/tenants/public/contact";

// Block the service worker so every page.route() intercept below is
// guaranteed to catch the request instead of falling through to the real
// backend — critical since SIGNUP_PATH is a POST that creates data.
test.use({ serviceWorkers: "block" });

const TERMS_VERSION = "2026-01";

function price(subtotal: string, vatAmount: string, total: string): PriceOut {
  return { subtotal, vat_rate: "0.15", vat_amount: vatAmount, total, currency: "ETB" };
}

// Totals are deliberately not the live catalog's: the price assertions below
// use these fixture values. Starter 345.00 / 3,450.00, Growth 690.00 /
// 6,900.00, Enterprise 1,380.00 / 13,800.00 (monthly / annual, incl. 15% VAT).
const PACKAGES_FIXTURE: PackagesListOut = {
  terms_version: TERMS_VERSION,
  packages: [
    {
      tier: "STARTER",
      display_name: "Starter",
      max_warehouses: 2,
      max_users: 10,
      sku_cap: 500,
      feature_flags: { CORE_INVENTORY: true },
      prices: {
        MONTHLY: price("300.00", "45.00", "345.00"),
        ANNUAL: price("3000.00", "450.00", "3450.00"),
      },
    },
    {
      tier: "GROWTH",
      display_name: "Growth",
      max_warehouses: 10,
      max_users: 50,
      sku_cap: 5000,
      feature_flags: { CORE_INVENTORY: true, TRANSFERS_PULL_PUSH: true, LOT_TRACEABILITY: true },
      prices: {
        MONTHLY: price("600.00", "90.00", "690.00"),
        ANNUAL: price("6000.00", "900.00", "6900.00"),
      },
    },
    {
      tier: "ENTERPRISE",
      display_name: "Enterprise",
      max_warehouses: null,
      max_users: null,
      sku_cap: null,
      feature_flags: { CORE_INVENTORY: true, TRANSFERS_PULL_PUSH: true, AI_ANALYTICS: true, API_ACCESS: true },
      prices: {
        MONTHLY: price("1200.00", "180.00", "1380.00"),
        ANNUAL: price("12000.00", "1800.00", "13800.00"),
      },
    },
  ],
};

const UNCONFIGURED_CONTACT = {
  configured: false,
  support_email: null,
  phone: null,
  whatsapp: null,
  address: { en: null, am: null },
  hours: { en: null, am: null },
  note: { en: null, am: null },
  updated_at: "2026-01-01T00:00:00Z",
};

function envelope(data: unknown) {
  return {
    success: true,
    data,
    request_id: "test-request-id",
    timestamp: new Date().toISOString(),
  };
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

type SignupRequestBody = Record<string, unknown>;

/**
 * Stub the three public endpoints the sign-up page touches. Returns the list
 * of POST bodies the page sent to /public/signup. A second submission with an
 * admin_email already seen in this test gets the real DUPLICATE_EMAIL error
 * (HTTP 409, FastAPI HTTPException body {"detail": {code, message}} — see
 * _duplicate_email_http_exception in tenant-service routers/tenants.py).
 */
async function stubSignupApi(page: Page): Promise<SignupRequestBody[]> {
  const posts: SignupRequestBody[] = [];
  const seenEmails = new Set<string>();

  await page.route(PUBLIC_CONTACT_PATH, (route) => fulfillJson(route, 200, envelope(UNCONFIGURED_CONTACT)));
  await page.route(PACKAGES_PATH, (route) => fulfillJson(route, 200, envelope(PACKAGES_FIXTURE)));
  await page.route(SIGNUP_PATH, (route) => {
    const body = route.request().postDataJSON() as SignupRequestBody;
    posts.push(body);
    const email = String(body.admin_email).toLowerCase();
    if (seenEmails.has(email)) {
      return fulfillJson(route, 409, {
        detail: { code: "DUPLICATE_EMAIL", message: "This email address is already in use." },
      });
    }
    seenEmails.add(email);
    const chosen = PACKAGES_FIXTURE.packages.find((p) => p.tier === body.tier)!;
    const period = body.billing_period as "MONTHLY" | "ANNUAL";
    return fulfillJson(
      route,
      201,
      envelope({
        tenant_id: "00000000-0000-4000-8000-000000000001",
        slug: String(body.slug),
        company_name: String(body.company_name),
        admin_email: String(body.admin_email),
        tier: String(body.tier),
        billing_period: period,
        subscription_status: "ACTIVE",
        contract_start: "2026-01-01",
        contract_end: period === "ANNUAL" ? "2026-12-31" : "2026-01-31",
        price: chosen.prices[period],
        email_verification_required: true,
        next_step: "SIGN_IN",
      }),
    );
  });
  return posts;
}

async function chooseStarterAndContinue(page: Page) {
  await page.goto(`${BASE_URL}/signup`);
  const starterCard = page.getByTestId("package-card-STARTER");
  await starterCard.getByRole("button", { name: "Select" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
}

async function fillStep2(page: Page, handle: string, email = `${handle}@probe.local`): Promise<string> {
  await page.locator('input[name="company_name"]').fill(handle);
  await page.locator('input[name="slug"]').fill(handle);
  await page.locator('input[name="admin_full_name"]').fill("S7 E2E Probe");
  await page.locator('input[name="admin_email"]').fill(email);
  await page.locator('input[name="admin_password"]').fill("Test@2026");
  await page.locator('input[name="admin_password_confirm"]').fill("Test@2026");
  await page.locator('input[name="accept_terms"]').check();
  return email;
}

test.describe("Public sign-up", () => {
  test("packages render from the API", async ({ page }) => {
    await stubSignupApi(page);
    await page.goto(`${BASE_URL}/signup`);
    await expect(page.getByText("Starter", { exact: true })).toBeVisible();
    await expect(page.getByText("Growth", { exact: true })).toBeVisible();
    await expect(page.getByText("Enterprise", { exact: true })).toBeVisible();
    // Monthly is the default period; prices come from the fixture.
    await expect(page.getByTestId("package-card-STARTER").getByText(/345\.00\s*ETB/)).toBeVisible();
    await expect(page.getByTestId("package-card-GROWTH").getByText(/690\.00\s*ETB/)).toBeVisible();
    await expect(page.getByTestId("package-card-ENTERPRISE").getByText(/1,380\.00\s*ETB/)).toBeVisible();
  });

  test("period toggle changes prices", async ({ page }) => {
    await stubSignupApi(page);
    await page.goto(`${BASE_URL}/signup`);
    const starterCard = page.getByTestId("package-card-STARTER");
    await expect(starterCard.getByText(/345\.00\s*ETB/)).toBeVisible();
    await page.getByRole("button", { name: "Annual" }).click();
    await expect(starterCard.getByText(/3,450\.00\s*ETB/)).toBeVisible();
  });

  test("required-field errors on step 2", async ({ page }) => {
    await stubSignupApi(page);
    await chooseStarterAndContinue(page);

    // Submitting step 2 with everything empty should surface validation errors
    // rather than advancing to the summary step.
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Company name is required.")).toBeVisible();
    await expect(page.getByText("Enter a valid email address.")).toBeVisible();
    await expect(page.getByText("You must accept the terms to continue.")).toBeVisible();
  });

  test("successful sign-up shows 'sign in with {email}' and posts the filled values", async ({ page }) => {
    const posts = await stubSignupApi(page);
    const handle = "zz-s7-stub-ok";
    await chooseStarterAndContinue(page);

    const email = await fillStep2(page, handle);
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page.getByText("Review your details")).toBeVisible();
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByText("Your account is ready!")).toBeVisible();
    await expect(page.getByText(`Sign in with ${email} to get started.`)).toBeVisible();

    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({
      company_name: handle,
      slug: handle,
      admin_full_name: "S7 E2E Probe",
      admin_email: email,
      tier: "STARTER",
      billing_period: "MONTHLY",
      accept_terms: true,
      terms_version: TERMS_VERSION,
    });
  });

  test("duplicate email shows the DUPLICATE_EMAIL message", async ({ page }) => {
    const posts = await stubSignupApi(page);
    const handle = "zz-s7-stub-dup";
    await chooseStarterAndContinue(page);

    const email = await fillStep2(page, handle);
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Your account is ready!")).toBeVisible();

    // Second sign-up with the same email, different company/slug.
    await chooseStarterAndContinue(page);
    await fillStep2(page, `${handle}-2`, email);
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByText("This email address is already in use.")).toBeVisible();
    expect(posts).toHaveLength(2);
  });
});
