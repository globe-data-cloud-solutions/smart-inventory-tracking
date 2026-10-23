/**
 * Playwright — RB-10: offline queue drain and the queue panel on the Inventory page.
 *
 * The session is seeded in localStorage and the offline queue is seeded in
 * IndexedDB ("smart-offline"/"queue"). Every /api/v1 call is intercepted, so no
 * live backend is needed and nothing is written to a real tenant.
 *
 * Covers:
 *   - sync sends only PENDING items, to /api/v1/inventory/sync/batch, in {items}
 *   - SYNCED items are removed; a CONFLICT item stays and shows the server reason
 *   - Retry sends a CONFLICT item again
 *   - Discard needs a second click and removes the item from this device only
 *   - a failed sync (network error) keeps every item PENDING
 *
 * Chromium headless against http://localhost:3000. Run:
 *   npx playwright test tests/rb10-offline-queue.spec.ts --reporter=line --workers=1
 */
import { test, expect, type Page, type ConsoleMessage, type Route } from "@playwright/test";
import { isDevHmrNoise } from "./helpers/console-noise";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const ORG = "zz-rb10-offline";
const PRODUCT_ID = "aaaaaaaa-0000-0000-0000-000000000001";
const WAREHOUSE_ID = "20000000-0000-0000-0000-000000000001";

test.setTimeout(90_000);
test.use({ serviceWorkers: "block" });

interface SeedItem {
  idempotencyKey: string;
  action: string;
  payload: Record<string, unknown>;
  status: "PENDING" | "CONFLICT" | "SYNCED";
  conflictCode?: string;
}

const PENDING_RECEIVE: SeedItem = {
  idempotencyKey: "receive:pending-1",
  action: "inventory:receive",
  status: "PENDING",
  payload: { product_id: PRODUCT_ID, warehouse_id: WAREHOUSE_ID, quantity: "5.0000", idempotency_key: "receive:pending-1" },
};
const CONFLICT_ISSUE: SeedItem = {
  idempotencyKey: "issue:conflict-1",
  action: "inventory:issue",
  status: "CONFLICT",
  conflictCode: "INSUFFICIENT_STOCK",
  payload: { product_id: PRODUCT_ID, warehouse_id: WAREHOUSE_ID, quantity: "2.0000", reason_code: "SALE", idempotency_key: "issue:conflict-1" },
};

function collectConsoleErrors(page: Page): string[] {
  const lines: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    if (isDevHmrNoise(msg.text())) return;
    if (/Failed to load resource/.test(msg.text())) return; // intercepted/gated API calls
    lines.push(msg.text());
  });
  page.on("pageerror", (err) => lines.push(`[pageerror] ${err.message}`));
  return lines;
}

function fulfillJson(route: Route, data: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ success: true, data, request_id: "test", timestamp: new Date().toISOString() }),
  });
}

/** Seed the demo session (a warehouse-level user, so the Receive panel is present). */
async function seedSession(page: Page) {
  await page.addInitScript((org: string) => {
    if (window.location.origin.startsWith("http://localhost:3000") && !window.localStorage.getItem("smart_demo_session")) {
      window.localStorage.setItem(
        "smart_demo_session",
        JSON.stringify({
          id: "u-wm-rb10",
          email: "wm-rb10@example.test",
          name: "RB10 Warehouse",
          role: "WM",
          orgSlug: org,
          tenantId: "10000000-0000-0000-0000-000000000001",
          tenantName: "RB10 Test",
          tenantSlug: org,
          warehouseId: "20000000-0000-0000-0000-000000000001",
        })
      );
    }
  }, ORG);
}

/** Replace the browser's queue with exactly these items. */
async function seedQueue(page: Page, items: SeedItem[]) {
  await page.evaluate(async (rows: SeedItem[]) => {
    await new Promise<void>((resolve, reject) => {
      const open = indexedDB.open("smart-offline", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("queue", { keyPath: "idempotencyKey" });
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        const tx = db.transaction("queue", "readwrite");
        const store = tx.objectStore("queue");
        store.clear();
        for (const r of rows) {
          store.put({ ...r, createdAt: new Date().toISOString(), retries: 0 });
        }
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => reject(tx.error);
      };
    });
  }, items);
}

async function queueKeys(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    return new Promise<string[]>((resolve, reject) => {
      const open = indexedDB.open("smart-offline", 1);
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        const req = db.transaction("queue").objectStore("queue").getAllKeys();
        req.onsuccess = () => { db.close(); resolve(req.result as string[]); };
        req.onerror = () => reject(req.error);
      };
    });
  });
}

/** Answer every other /api/v1 call so the Inventory page renders without a backend. */
async function mockBackground(page: Page) {
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/sync/batch")) return route.fallback();
    if (url.includes("/tenants/me/plan")) {
      return fulfillJson(route, {
        plan_tier: "PRO",
        feature_flags: {},
        max_warehouses: null,
        max_users: null,
        sku_cap: null,
        contract_start: null,
        contract_end: null,
      });
    }
    return fulfillJson(route, []);
  });
}

/** Intercept the batch endpoint. `answer` decides each item's status; null = network failure. */
function interceptSync(page: Page, answer: ((key: string) => string) | null) {
  const bodies: Array<{ items: Array<{ idempotency_key: string; action: string }> }> = [];
  page.route("**/api/v1/inventory/sync/batch", async (route) => {
    const body = route.request().postDataJSON() as typeof bodies[number];
    bodies.push(body);
    if (answer === null) {
      await route.abort("internetdisconnected");
      return;
    }
    const data = body.items.map((it) => {
      const status = answer(it.idempotency_key);
      return status === "CONFLICT"
        ? { idempotency_key: it.idempotency_key, status, code: "INSUFFICIENT_STOCK" }
        : { idempotency_key: it.idempotency_key, status };
    });
    await fulfillJson(route, data);
  });
  return bodies;
}

test.describe("RB-10 offline queue", () => {
  test("sends only PENDING items, removes SYNCED, keeps CONFLICT with its reason", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await seedSession(page);
    await page.goto(`${BASE_URL}/${ORG}/inventory`).catch(() => {});
    await seedQueue(page, [PENDING_RECEIVE, CONFLICT_ISSUE]);
    const bodies = interceptSync(page, (key) => (key === "receive:pending-1" ? "SYNCED" : "CONFLICT"));
    await mockBackground(page);
    await page.reload();

    await expect.poll(() => bodies.length).toBeGreaterThan(0);
    const sent = bodies[0].items.map((i) => i.idempotency_key);
    expect(sent).toEqual(["receive:pending-1"]);

    const panel = page.getByRole("status").filter({ hasText: "waiting to sync" });
    await expect(panel).toContainText("Not enough usable stock");
    await expect(panel).toContainText("1 movement(s) waiting to sync");
    expect(await queueKeys(page)).toEqual(["issue:conflict-1"]);
    expect(errors).toEqual([]);
  });

  test("Retry sends the CONFLICT item again", async ({ page }) => {
    await seedSession(page);
    await page.goto(`${BASE_URL}/${ORG}/inventory`).catch(() => {});
    await seedQueue(page, [CONFLICT_ISSUE]);
    const bodies = interceptSync(page, () => "SYNCED");
    await mockBackground(page);
    await page.reload();
    await page.getByRole("button", { name: "Retry" }).click();

    await expect.poll(() => bodies.length).toBeGreaterThan(0);
    expect(bodies[bodies.length - 1].items.map((i) => i.idempotency_key)).toEqual(["issue:conflict-1"]);
    await expect(page.getByRole("status").filter({ hasText: "waiting to sync" })).toHaveCount(0);
  });

  test("Discard needs a second click and removes the item from this device", async ({ page }) => {
    await seedSession(page);
    await page.goto(`${BASE_URL}/${ORG}/inventory`).catch(() => {});
    await seedQueue(page, [CONFLICT_ISSUE]);
    interceptSync(page, () => "CONFLICT");
    await mockBackground(page);
    await page.reload();

    await page.getByRole("button", { name: "Discard", exact: true }).click();
    await expect(page.getByRole("button", { name: "Confirm discard" })).toBeVisible();
    expect(await queueKeys(page)).toEqual(["issue:conflict-1"]);

    await page.getByRole("button", { name: "Confirm discard" }).click();
    await expect.poll(() => queueKeys(page)).toEqual([]);
  });

  test("a failed sync keeps every item PENDING", async ({ page }) => {
    await seedSession(page);
    await page.goto(`${BASE_URL}/${ORG}/inventory`).catch(() => {});
    await seedQueue(page, [PENDING_RECEIVE]);
    const bodies = interceptSync(page, null);
    await mockBackground(page);
    await page.reload();

    await expect.poll(() => bodies.length).toBeGreaterThan(0);
    expect(await queueKeys(page)).toEqual(["receive:pending-1"]);
    await expect(page.getByRole("status").filter({ hasText: "waiting to sync" })).toContainText("1 movement(s)");
  });
});
