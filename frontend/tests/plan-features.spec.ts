/**
 * Playwright E2E — plan-gated UI (feature-not-in-plan upgrade message,
 * Branding tab gating by CUSTOM_BRANDING, scheduled-downgrade notice + SA
 * controls). See CLAUDE.md §29 "Frontend verification" and §15 S13.
 *
 * zz-e2e-ta (STARTER, CUSTOM_BRANDING off) is the permanent TA probe — never
 * mutated here, only read and gated against. A fresh zz-f1-<timestamp>
 * tenant is created via public signup for the scheduled-downgrade case and
 * deactivated in afterAll (never hard-deleted, per CLAUDE.md §8).
 *
 * Chromium headless only, against http://localhost:3000. Run:
 *   npx playwright test tests/plan-features.spec.ts tests/auth-login.spec.ts --workers=1
 */
import { test, expect, type Page, type ConsoleMessage, type APIRequestContext } from "@playwright/test";
import { E2E_TA_EMAIL, E2E_TA_SLUG, e2eTaPasswordOrSkip } from "./helpers/e2e-ta";
import { SA_EMAIL, saPassword, saPasswordOrSkip } from "./helpers/sa-credentials";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

test.setTimeout(60_000);

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

// Memoized per email+password — /auth/token shares a per-IP "login" rate-limit
// bucket (20/900s, backend/shared/cache/rate_limit.py) with every UI login in
// this file, so re-fetching per call/test burns through it fast on reruns.
const _tokenCache = new Map<string, string>();
async function apiToken(request: APIRequestContext, email: string, password: string): Promise<string> {
  const cacheKey = `${email}:${password}`;
  const cached = _tokenCache.get(cacheKey);
  if (cached) return cached;
  const resp = await request.post(`${API_BASE}/api/v1/auth/token`, { data: { email, password } });
  expect(resp.ok(), `token request for ${email} failed (${resp.status()})`).toBeTruthy();
  const { access_token } = (await resp.json()) as { access_token: string };
  _tokenCache.set(cacheKey, access_token);
  return access_token;
}

async function resolveTenantId(request: APIRequestContext, slugOrId: string, token: string): Promise<string> {
  const resp = await request.get(`${API_BASE}/api/v1/tenants/${slugOrId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(resp.ok(), `tenant lookup for ${slugOrId} failed (${resp.status()})`).toBeTruthy();
  const { data } = (await resp.json()) as { data: { id: string; logo_url: string | null; banner_url: string | null } };
  return data.id;
}

/** SA-only: resolve a tenant's UUID from its slug via the registry, then
 * deactivate it (soft delete — never a hard delete, per CLAUDE.md §8).
 * Mirrors signup.spec.ts's deactivateBySlug — duplicated here rather than
 * exported since that helper is local to that file. */
async function deactivateBySlug(request: APIRequestContext, slug: string): Promise<void> {
  const saPw = saPassword();
  if (!saPw) {
    console.warn(`plan-features.spec cleanup skipped: E2E_SA_PASSWORD not set — could not deactivate ${slug}`);
    return;
  }
  const token = await apiToken(request, SA_EMAIL, saPw);
  const authHeaders = { Authorization: `Bearer ${token}` };
  const registryResp = await request.get(`${API_BASE}/api/v1/tenants/sa/registry`, { headers: authHeaders });
  if (!registryResp.ok()) {
    console.warn(`plan-features.spec cleanup: registry fetch failed (${registryResp.status()}) — could not deactivate ${slug}`);
    return;
  }
  const { data: tenants } = (await registryResp.json()) as { data: Array<{ id: string; slug: string }> };
  const tenant = tenants.find((t) => t.slug === slug);
  if (!tenant) {
    console.warn(`plan-features.spec cleanup: no tenant found for slug ${slug}`);
    return;
  }
  const deactivateResp = await request.patch(`${API_BASE}/api/v1/tenants/${tenant.id}/deactivate`, { headers: authHeaders });
  if (!deactivateResp.ok() && deactivateResp.status() !== 422) {
    console.warn(`plan-features.spec cleanup: deactivate failed for ${slug} (${deactivateResp.status()})`);
  }
}

const createdSlugs: string[] = [];
test.afterAll(async ({ request }) => {
  for (const slug of createdSlugs) await deactivateBySlug(request, slug);
});

// ── Branding tab gating (TA, CUSTOM_BRANDING off on STARTER) ─────────────────
for (const locale of ["en", "am"] as const) {
  test.describe(`Branding tab gating — TA zz-e2e-ta (${locale})`, () => {
    test(`form is disabled with the upgrade message, existing branding still shown (${locale})`, async ({ page }) => {
      const taPassword = e2eTaPasswordOrSkip(test);
      const consoleErrors = collectConsoleErrors(page);

      await page.addInitScript((loc) => window.localStorage.setItem("locale", loc), locale);
      await login(page, E2E_TA_EMAIL, taPassword);
      await page.goto(`${BASE_URL}/${E2E_TA_SLUG}/settings/org-setup`);
      await page.getByRole("button", { name: /Branding|ብራንዲንግ/i }).click();
      await page.waitForLoadState("networkidle");

      // Upgrade message shown, never a raw key or [object Object].
      const upgradeBox = page.getByText(/not available on your current plan|ባህሪ.*አይገኝም/i);
      await expect(upgradeBox).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText("plan.feature_not_in_plan")).toHaveCount(0);
      await expect(page.getByText("[object Object]")).toHaveCount(0);

      // File inputs disabled — no way to start an upload.
      const fileInputs = page.locator('input[type="file"]');
      await expect(fileInputs).toHaveCount(2);
      for (let i = 0; i < 2; i++) {
        await expect(fileInputs.nth(i)).toBeDisabled();
      }

      console.log(`--- branding gating (${locale}) console errors ---`);
      for (const e of consoleErrors) console.log(e);
      expect(consoleErrors, `zero console errors on the gated branding tab (${locale})`).toHaveLength(0);
    });
  });
}

// ── Direct branding PATCH — TA 402, SA not-402 ────────────────────────────────
test.describe("Branding PATCH — plan gate", () => {
  test("TA on zz-e2e-ta gets 402 FEATURE_NOT_IN_PLAN, no raw JSON leak", async ({ request }) => {
    const taPassword = e2eTaPasswordOrSkip(test);
    const taToken = await apiToken(request, E2E_TA_EMAIL, taPassword);
    const tenantId = await resolveTenantId(request, E2E_TA_SLUG, taToken);

    const resp = await request.patch(`${API_BASE}/api/v1/tenants/${tenantId}/branding`, {
      headers: { Authorization: `Bearer ${taToken}` },
      data: {},
    });
    expect(resp.status()).toBe(402);
    const body = (await resp.json()) as { detail: { code: string; feature: string; upgrade_to: string | null } };
    expect(body.detail.code).toBe("FEATURE_NOT_IN_PLAN");
    expect(body.detail.feature).toBe("CUSTOM_BRANDING");
    expect(body.detail.upgrade_to).toBe("GROWTH");
  });

  test("SA on zz-e2e-ta is not gated (bypasses plan checks)", async ({ request }) => {
    const saPw = saPasswordOrSkip(test);
    const saToken = await apiToken(request, SA_EMAIL, saPw);
    const tenantId = await resolveTenantId(request, E2E_TA_SLUG, saToken);

    // Read current values first and send them back unchanged — this is a
    // gate-bypass probe, not a data change on the permanent TA tenant.
    const getResp = await request.get(`${API_BASE}/api/v1/tenants/${tenantId}`, {
      headers: { Authorization: `Bearer ${saToken}` },
    });
    const { data: current } = (await getResp.json()) as { data: { logo_url: string | null; banner_url: string | null } };

    const resp = await request.patch(`${API_BASE}/api/v1/tenants/${tenantId}/branding`, {
      headers: { Authorization: `Bearer ${saToken}` },
      data: { logo_url: current.logo_url, banner_url: current.banner_url },
    });
    expect(resp.status()).not.toBe(402);
    expect(resp.ok()).toBeTruthy();
  });
});

// ── Scheduled downgrade — never-paid tenant downgrades IMMEDIATE, not SCHEDULED ──
test.describe("Scheduled downgrade — SA plan controls", () => {
  test("never-paid probe tenant: downgrade is IMMEDIATE, no scheduled notice", async ({ page, request }) => {
    const saPw = saPasswordOrSkip(test);
    const slug = `zz-f1-${Date.now()}`;
    createdSlugs.push(slug);

    await page.goto(`${BASE_URL}/signup`);
    await page.getByTestId("package-card-GROWTH").getByRole("button", { name: "Select" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.locator('input[name="company_name"]').fill(slug);
    await page.locator('input[name="slug"]').fill(slug);
    await page.locator('input[name="admin_full_name"]').fill("F1 E2E Probe");
    await page.locator('input[name="admin_email"]').fill(`${slug}@probe.local`);
    await page.locator('input[name="admin_password"]').fill("Test@2026");
    await page.locator('input[name="admin_password_confirm"]').fill("Test@2026");
    await page.locator('input[name="accept_terms"]').check();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Your account is ready!")).toBeVisible();

    const saToken = await apiToken(request, SA_EMAIL, saPw);
    const tenantId = await resolveTenantId(request, slug, saToken);

    const patchResp = await request.patch(`${API_BASE}/api/v1/tenants/${tenantId}/plan`, {
      headers: { Authorization: `Bearer ${saToken}` },
      data: { plan_tier: "STARTER", effective: "RENEWAL" },
    });
    expect(patchResp.ok()).toBeTruthy();
    const { data } = (await patchResp.json()) as { data: { mode: string; scheduled_tier: string | null } };
    expect(data.mode, "never-paid downgrade must be IMMEDIATE by design (proration._never_paid)").toBe("IMMEDIATE");
    expect(data.scheduled_tier).toBeNull();

    // UI: SA's tenant Plan tab shows no scheduled-downgrade notice.
    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${tenantId}`);
    await page.getByRole("button", { name: /Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/scheduled to downgrade/i)).toHaveCount(0);
  });

  test("paid subscription: downgrade is SCHEDULED, SA can cancel it", async ({ page, request }) => {
    const saPw = saPasswordOrSkip(test);
    const slug = `zz-f1-${Date.now()}-paid`;
    createdSlugs.push(slug);

    await page.goto(`${BASE_URL}/signup`);
    await page.getByTestId("package-card-GROWTH").getByRole("button", { name: "Select" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.locator('input[name="company_name"]').fill(slug);
    await page.locator('input[name="slug"]').fill(slug);
    await page.locator('input[name="admin_full_name"]').fill("F1 Paid Probe");
    await page.locator('input[name="admin_email"]').fill(`${slug}@probe.local`);
    await page.locator('input[name="admin_password"]').fill("Test@2026");
    await page.locator('input[name="admin_password_confirm"]').fill("Test@2026");
    await page.locator('input[name="accept_terms"]').check();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Your account is ready!")).toBeVisible();

    const saToken = await apiToken(request, SA_EMAIL, saPw);
    const authHeaders = { Authorization: `Bearer ${saToken}` };
    const tenantId = await resolveTenantId(request, slug, saToken);

    // Raise the first PERIOD invoice and mark it paid — flips the subscription
    // out of PENDING_PAYMENT so proration._never_paid() is False, which is the
    // precondition for a downgrade to SCHEDULE instead of apply IMMEDIATE.
    const invoiceResp = await request.post(`${API_BASE}/api/v1/tenants/${tenantId}/invoices`, {
      headers: authHeaders, data: {},
    });
    if (!invoiceResp.ok()) {
      console.warn(`paid-subscription downgrade test: could not raise an invoice (${invoiceResp.status()}) — skipping`);
      test.skip(true, "could not raise the initial invoice for the paid-downgrade case");
      return;
    }
    const { data: invoice } = (await invoiceResp.json()) as { data: { payment_id: string } };
    const markPaidResp = await request.post(
      `${API_BASE}/api/v1/tenants/${tenantId}/payments/${invoice.payment_id}/mark-paid`,
      { headers: authHeaders, data: {} },
    );
    if (!markPaidResp.ok()) {
      console.warn(`paid-subscription downgrade test: mark-paid failed (${markPaidResp.status()}) — skipping`);
      test.skip(true, "could not mark the initial invoice paid for the paid-downgrade case");
      return;
    }

    const patchResp = await request.patch(`${API_BASE}/api/v1/tenants/${tenantId}/plan`, {
      headers: authHeaders, data: { plan_tier: "STARTER", effective: "RENEWAL" },
    });
    expect(patchResp.ok()).toBeTruthy();
    const { data } = (await patchResp.json()) as { data: { mode: string; scheduled_tier: string | null } };
    expect(data.mode).toBe("SCHEDULED");
    expect(data.scheduled_tier).toBe("STARTER");

    // UI: SA sees the notice + Cancel button; cancelling makes it disappear.
    await login(page, SA_EMAIL, saPw);
    await page.goto(`${BASE_URL}/admin/settings/tenants/${tenantId}`);
    await page.getByRole("button", { name: /Plan$/i }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/scheduled to downgrade to STARTER/i)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: /Cancel scheduled downgrade/i }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/scheduled to downgrade/i)).toHaveCount(0);
  });
});
