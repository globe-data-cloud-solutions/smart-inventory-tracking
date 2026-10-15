/**
 * SA (System Administrator) login for E2E specs — the single place the SA
 * email lives so no spec defines its own copy.
 *
 * The SA password is NEVER committed. Alex sets E2E_SA_PASSWORD in his own
 * terminal only when he runs the SA tests by hand; it is never put in .env,
 * and Claude Code never sets it. Tests that need an SA login must call
 * saPasswordOrSkip(test) as their first statement and skip cleanly when it is
 * unset; helpers that make SA requests must check saPassword() and make no
 * request when it is undefined.
 */
export const SA_EMAIL = "smartadmin@smart-inventory.com";

/** Returns the SA password from env, or undefined if not set. */
export function saPassword(): string | undefined {
  return process.env.E2E_SA_PASSWORD;
}

/** The only part of Playwright's `test` this helper needs. */
interface Skippable {
  skip(condition: boolean, description: string): void;
}

/**
 * Call as the FIRST statement of a test body that needs an SA login. Skips the
 * test when E2E_SA_PASSWORD is not set in the environment.
 */
export function saPasswordOrSkip(test: Skippable): string {
  const pw = saPassword();
  test.skip(!pw, "E2E_SA_PASSWORD not set — SA tests are run by Alex only, by hand");
  return pw as string;
}
