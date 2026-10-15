/**
 * SA-only API helpers for specs that need their own probe tenant.
 *
 * Every function here that talks to an SA endpoint needs the SA password, so
 * callers MUST guard with saPassword() first (test.skip(!saPassword(), ...) at
 * the top of the describe, so beforeAll/afterAll are skipped too). saToken()
 * throws if it is ever reached without one — it never makes a request then.
 *
 * Probe tenants are created through the PUBLIC signup API (no SA needed for
 * that call), get a unique `zz-<prefix>-<timestamp>` slug, and are deactivated
 * (soft — never hard-deleted, CLAUDE.md §8) by the spec's afterAll.
 *
 * Email verification: POST /auth/token only returns 403 EMAIL_NOT_VERIFIED
 * when the auth-service runs with EMAIL_VERIFICATION_REQUIRED=true (default
 * false; backend/shared/auth/email_verification.py). There is no clean test
 * route to verify an email (the token is only ever mailed), so when it is on,
 * the probe's TA login is not possible — createProbeTenant() still returns the
 * tenant and the SA-side flows keep working.
 */
import { expect, type APIRequestContext } from "@playwright/test";
import { SA_EMAIL, saPassword } from "./sa-credentials";

const API_BASE = process.env.GATEWAY_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const PROBE_ADMIN_PASSWORD = "Test@2026";

export interface ProbeTenant {
  id: string;
  slug: string;
  adminEmail: string;
  adminPassword: string;
}

export interface CreateProbeOptions {
  /** Slug prefix: the tenant slug is `zz-${prefix}-${timestamp36}`. */
  prefix: string;
  tier: "STARTER" | "GROWTH" | "ENTERPRISE";
  billingPeriod: "MONTHLY" | "ANNUAL";
}

/** Memoised per run — /auth/token shares a per-IP login rate-limit bucket (20/900s). */
let cachedSaToken: string | null = null;

export async function saToken(request: APIRequestContext): Promise<string> {
  if (cachedSaToken) return cachedSaToken;
  const pw = saPassword();
  if (!pw) throw new Error("saToken() called without E2E_SA_PASSWORD — guard the describe with saPassword() first");
  const resp = await request.post(`${API_BASE}/api/v1/auth/token`, { data: { email: SA_EMAIL, password: pw } });
  expect(resp.ok(), `SA token request failed (${resp.status()})`).toBeTruthy();
  const { access_token } = (await resp.json()) as { access_token: string };
  cachedSaToken = access_token;
  return access_token;
}

function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

/** Unique slug for this run; also used by specs that create tenants through the SA wizard. */
export function uniqueSlug(prefix: string): string {
  return `zz-${prefix}-${Date.now().toString(36)}`;
}

/** Creates a probe tenant through POST /api/v1/tenants/public/signup. No SA call. */
export async function createProbeTenant(
  request: APIRequestContext,
  { prefix, tier, billingPeriod }: CreateProbeOptions,
): Promise<ProbeTenant> {
  const slug = uniqueSlug(prefix);
  const adminEmail = `${slug}@probe.local`;

  const pkgResp = await request.get(`${API_BASE}/api/v1/tenants/public/packages`);
  expect(pkgResp.ok(), `public packages request failed (${pkgResp.status()})`).toBeTruthy();
  const { data: pkgs } = (await pkgResp.json()) as { data: { terms_version: string } };

  const resp = await request.post(`${API_BASE}/api/v1/tenants/public/signup`, {
    data: {
      company_name: slug,
      slug,
      organisation_type: "PRODUCER",
      default_locale: "en",
      tier,
      billing_period: billingPeriod,
      admin_full_name: "SA Spec Probe",
      admin_email: adminEmail,
      admin_password: PROBE_ADMIN_PASSWORD,
      accept_terms: true,
      terms_version: pkgs.terms_version,
    },
  });
  expect(resp.status(), `probe signup for ${slug} failed: ${await resp.text()}`).toBe(201);
  const { data } = (await resp.json()) as { data: { tenant_id: string } };
  return { id: data.tenant_id, slug, adminEmail, adminPassword: PROBE_ADMIN_PASSWORD };
}

export async function findTenantBySlug(
  request: APIRequestContext,
  token: string,
  slug: string,
): Promise<{ id: string; slug: string } | null> {
  const resp = await request.get(`${API_BASE}/api/v1/tenants/sa/registry`, { headers: bearer(token) });
  if (!resp.ok()) {
    console.warn(`findTenantBySlug: registry fetch failed (${resp.status()}) for ${slug}`);
    return null;
  }
  const { data } = (await resp.json()) as { data: Array<{ id: string; slug: string }> };
  return data.find((t) => t.slug === slug) ?? null;
}

/** Soft deactivate. 422 (already deactivated) is fine; other failures are warned, never thrown. */
export async function deactivateTenant(request: APIRequestContext, token: string, id: string): Promise<void> {
  const resp = await request.patch(`${API_BASE}/api/v1/tenants/${id}/deactivate`, { headers: bearer(token) });
  if (!resp.ok() && resp.status() !== 422) {
    console.warn(`deactivateTenant: ${id} failed (${resp.status()})`);
  }
}

/** Deactivates a tenant found by slug (e.g. one created through the SA wizard). */
export async function deactivateTenantBySlug(request: APIRequestContext, token: string, slug: string): Promise<void> {
  const tenant = await findTenantBySlug(request, token, slug);
  if (!tenant) {
    console.warn(`deactivateTenantBySlug: no tenant found for slug ${slug}`);
    return;
  }
  await deactivateTenant(request, token, tenant.id);
}

/** SA: sets contract dates (ISO YYYY-MM-DD) with the mandatory audit note. */
export async function setContractDates(
  request: APIRequestContext,
  token: string,
  tenantId: string,
  contractStart: string,
  contractEnd: string,
): Promise<void> {
  const resp = await request.patch(`${API_BASE}/api/v1/tenants/${tenantId}/contract`, {
    headers: bearer(token),
    data: { contract_start: contractStart, contract_end: contractEnd, note: "e2e probe contract dates" },
  });
  expect(resp.ok(), `setContractDates failed (${resp.status()}): ${await resp.text()}`).toBeTruthy();
}

/**
 * SA: raises the first PERIOD invoice and marks it paid — flips the
 * subscription out of PENDING_PAYMENT so proration._never_paid() is False,
 * the precondition for an ANNUAL upgrade to raise a PRORATION invoice
 * (same setup as plan-features.spec.ts's paid-subscription case).
 */
export async function createPaidSubscriptionInvoice(
  request: APIRequestContext,
  token: string,
  tenantId: string,
): Promise<void> {
  const invoiceResp = await request.post(`${API_BASE}/api/v1/tenants/${tenantId}/invoices`, {
    headers: bearer(token), data: {},
  });
  expect(invoiceResp.ok(), `raise invoice failed (${invoiceResp.status()}): ${await invoiceResp.text()}`).toBeTruthy();
  const { data: invoice } = (await invoiceResp.json()) as { data: { payment_id: string } };
  const paidResp = await request.post(
    `${API_BASE}/api/v1/tenants/${tenantId}/payments/${invoice.payment_id}/mark-paid`,
    { headers: bearer(token), data: {} },
  );
  expect(paidResp.ok(), `mark-paid failed (${paidResp.status()}): ${await paidResp.text()}`).toBeTruthy();
}

export interface PickedAddon {
  code: string;
  displayName: string;
  /** Current (effective now) price for the requested billing period, as the API returns it. */
  amount: string;
}

export interface PickAddonOptions {
  /** Tiers whose package must NOT include the add-on (flag false/absent in every one). */
  excludeTiers: string[];
  billingPeriod: "MONTHLY" | "ANNUAL";
}

/**
 * SA: first ACTIVE add-on whose feature flag is not true in any excluded tier
 * AND that has a current (effective now) price for billingPeriod. Tier flags and
 * add-on prices are SA-editable platform config, so specs must not hard-code one.
 * GET /platform/tier-config (tenants.py:448) + GET /platform/addons (tenants.py:976).
 */
export async function pickTestAddon(
  request: APIRequestContext,
  token: string,
  { excludeTiers, billingPeriod }: PickAddonOptions,
): Promise<PickedAddon> {
  const tierResp = await request.get(`${API_BASE}/api/v1/tenants/platform/tier-config`, { headers: bearer(token) });
  expect(tierResp.ok(), `tier-config request failed (${tierResp.status()})`).toBeTruthy();
  const { data: tiers } = (await tierResp.json()) as {
    data: Array<{ tier: string; feature_flags: Record<string, boolean> }>;
  };
  const excluded = tiers.filter((t) => excludeTiers.includes(t.tier));
  const missing = excludeTiers.filter((t) => !excluded.some((e) => e.tier === t));
  if (missing.length) throw new Error(`pickTestAddon: tier(s) ${missing.join(", ")} not found in platform tier-config`);

  const addonResp = await request.get(`${API_BASE}/api/v1/tenants/platform/addons`, { headers: bearer(token) });
  expect(addonResp.ok(), `add-on catalog request failed (${addonResp.status()})`).toBeTruthy();
  const { data: addons } = (await addonResp.json()) as {
    data: Array<{
      code: string; display_name: string; is_active: boolean;
      prices: Array<{ billing_period: string; current: { amount: string } | null }>;
    }>;
  };

  const found = addons.find((a) =>
    a.is_active
    && excluded.every((t) => t.feature_flags[a.code] !== true)
    && a.prices.some((p) => p.billing_period === billingPeriod && p.current !== null),
  );
  if (!found) {
    const checked = addons
      .map((a) => `${a.code}(active=${a.is_active}, in=[${excluded.filter((t) => t.feature_flags[a.code] === true).map((t) => t.tier).join(",")}], ${billingPeriod} price=${a.prices.find((p) => p.billing_period === billingPeriod)?.current ? "yes" : "no"})`)
      .join("; ");
    throw new Error(
      `pickTestAddon: no ACTIVE add-on outside [${excludeTiers.join(", ")}] with a current ${billingPeriod} price. Checked: ${checked}`,
    );
  }
  const price = found.prices.find((p) => p.billing_period === billingPeriod)!.current!;
  return { code: found.code, displayName: found.display_name, amount: price.amount };
}
