/**
 * Permanent E2E TA test account (CLAUDE.md §29) — created once via public
 * sign-up as tenant slug "zz-e2e-ta" (STARTER, MONTHLY). Unlike every other
 * z-prefixed probe tenant, this one stays ACTIVE so tests always have a known
 * TA login available.
 *
 * The email is safe to commit. The password is NEVER committed — it is read
 * only from the E2E_TA_PASSWORD environment variable. Tests that need a TA
 * session must call e2eTaPasswordOrSkip(test) and skip cleanly when it is
 * unset, rather than failing or embedding a credential.
 */
export const E2E_TA_EMAIL = "e2e-ta@probe.local";
export const E2E_TA_SLUG = "zz-e2e-ta";

/** Returns the TA password from env, or undefined if not set. */
export function e2eTaPassword(): string | undefined {
  return process.env.E2E_TA_PASSWORD;
}

/** The only part of Playwright's `test` this helper needs — avoids importing
 * TestType<any, any> (and the eslint-disable that required). */
interface Skippable {
  skip(condition: boolean, description: string): void;
}

/**
 * Call at the top of a test body that needs a real TA login. Skips the test
 * with a clear message when E2E_TA_PASSWORD is not set in the environment.
 */
export function e2eTaPasswordOrSkip(test: Skippable): string {
  const pw = e2eTaPassword();
  test.skip(!pw, "E2E_TA_PASSWORD not set — skipping test that requires a real TA login");
  return pw as string;
}
