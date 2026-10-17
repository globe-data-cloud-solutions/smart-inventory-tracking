/**
 * Playwright E2E — the service worker is production-only (session 18, prompt D1, part 2).
 *
 * In dev, layout.tsx must unregister every existing registration and delete "smart-*" caches
 * (sw.js caches /_next/static/* cache-first, which pins stale JS because dev chunk names never
 * change). The test plants a worker and a cache first, so it fails if the cleanup is removed.
 *
 * No login, no API traffic. Chromium headless only, service workers ALLOWED (the point).
 *   cd frontend && npx playwright test tests/sw-dev.spec.ts --project=chromium --workers=1
 */
import { test, expect } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

test.use({ serviceWorkers: "allow" });

test("dev: leftover service worker and smart-* caches are cleared on load", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("load");

  // Plant what an older dev session would have left behind.
  await page.evaluate(async () => {
    await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    await caches.open("smart-vtest-static");
    await caches.open("other-cache");
  });
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBeGreaterThan(0);

  await page.reload();
  await page.waitForLoadState("load");

  await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
  // Cache deletion runs after the unregister resolves, so poll for it too.
  await expect.poll(async () => (await page.evaluate(() => caches.keys())).filter((k) => k.startsWith("smart-")),
    { message: "smart-* caches deleted" }).toEqual([]);
  expect(await page.evaluate(() => caches.keys()), "non-smart caches untouched").toContain("other-cache");

  // Cleanup of the unrelated cache we created.
  await page.evaluate(() => caches.delete("other-cache"));
  expect(pageErrors).toEqual([]);
});
