## 10. Frontend — TypeScript + Tailwind + PWA

### TypeScript — strict mode mandatory

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noUncheckedIndexedAccess": true
  }
}
```

### Tailwind — always use `cva` for component variants, never inline styles

```typescript
// frontend/src/components/ui/Button.tsx
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:opacity-50',
  {
    variants: {
      variant: {
        default:     'bg-blue-600 text-white hover:bg-blue-700',
        destructive: 'bg-red-500 text-white hover:bg-red-600',
        outline:     'border border-gray-300 bg-white hover:bg-gray-50',
        ghost:       'hover:bg-gray-100 text-gray-700',
      },
      size: { sm: 'h-8 px-3 text-xs', md: 'h-10 px-4', lg: 'h-12 px-6 text-base' },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  }
);
```

### PWA — service worker and offline queue

```typescript
// frontend/public/sw.js
// Responsibilities:
// 1. Cache app shell (HTML, CSS, JS bundles) for offline access
// 2. Cache language pack JSON files from S3
// 3. Queue failed POST/PATCH requests in IndexedDB for later sync

const CACHE = 'smart-v4';
const SHELL  = ['/', '/inventory', '/products', '/reports'];
const LOCALES= ['/api/locales/en', '/api/locales/am', '/api/locales/or'];

self.addEventListener('install', e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([...SHELL, ...LOCALES])))
);
```

```typescript
// frontend/src/store/offlineQueue.ts
import { openDB } from 'idb';

export async function enqueueOfflineTransaction(tx: OfflineTransaction) {
  const db = await openDB('smart-offline', 1, {
    upgrade(db) { db.createObjectStore('queue', { keyPath: 'idempotencyKey' }); }
  });
  await db.put('queue', { ...tx, status: 'PENDING', createdAt: new Date().toISOString() });
}
```

### Form factors and OS targets

| Form factor | OS / Browser | Primary users |
|---|---|---|
| Mobile phone | Android 10+ Chrome, iOS 15+ Safari | Warehouse staff, field agents |
| Tablet | Android 10+ Chrome, iPadOS 15+ Safari | Warehouse Managers (scan + dashboard) |
| Desktop | Windows 10/11, macOS, Linux (Chrome, Firefox, Edge, Safari) | NM, RM, TA, Finance, Auditor |

Single PWA serves all three. Tailwind breakpoints: `sm:` = mobile, `md:` = tablet, `lg:` = desktop.

### Permission hook — display only, never a security gate

```typescript
// WARNING: controls UI visibility only. Backend enforces all permissions independently.
export function usePermission(actionId: string): boolean {
  const { user } = useAuth();
  if (!user) return false;
  return (ROLE_PERMISSIONS[user.role] ?? []).includes(actionId);
}
```


## 11. Barcode Scanning

```typescript
// frontend/src/lib/scanner.ts
import { BrowserMultiFormatReader, NotFoundException } from '@zxing/browser';

export class BarcodeScanner {
  private reader = new BrowserMultiFormatReader();
  private stream: MediaStream | null = null;

  async start(videoEl: HTMLVideoElement, onResult: (code: string) => void): Promise<void> {
    // HTTPS is required — iOS Safari blocks camera access on HTTP
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }  // rear camera
    });
    await this.reader.decodeFromStream(this.stream, videoEl, (result, error) => {
      if (result) onResult(result.getText());
      if (error && !(error instanceof NotFoundException)) console.error(error);
    });
  }

  stop(): void {
    this.stream?.getTracks().forEach(t => t.stop());
    this.reader.reset();
  }
}
// Supported: Code128, Code39, EAN-13, EAN-8, QR Code, DataMatrix
// Target: < 1 second P90 scan recognition on mid-range Android
// Phase 3 option: Flutter native app with MLKit for high-volume Retailer scanning hardware
```


## 12. Localization — English, Amharic, Oromifa

> **Status (2026-10):** Phase 1 ships **English + Amharic**. Oromifa is **deferred**, not
> offered to users in Phase 1 (STOCKBALANCE.md §8): `or.json` keeps the ~550 draft Oromo
> values already in it unchanged until a native-speaker review is staffed; every NEW key is
> added with the ENGLISH value so the file stays complete (Review Backlog RB-6).

### Three supported languages from Phase 1

| Code | Language | Notes |
|---|---|---|
| `en` | English | Default — loaded when no preference is set |
| `am` | Amharic (አማርኛ) | Required from Phase 1 |
| `or` | Oromifa (Afaan Oromoo) | Deferred — scaffold only |

### Language selection priority

1. User preference (`users.locale` column)
2. Tenant default (`tenants.default_locale` column)
3. System default: `en`

### i18n loader

```typescript
// frontend/src/lib/i18n.ts
type Locale = 'en' | 'am' | 'or';
let translations: Record<string, unknown> = {};

export async function loadLocale(locale: Locale): Promise<void> {
  // Language packs served from S3 via CDN, cached by service worker
  const res = await fetch(`/api/locales/${locale}`);
  translations = await res.json();
}

export function t(key: string): string {
  // Dot-notation: 'nav.inventory', 'alerts.low_stock'
  return key.split('.').reduce(
    (obj: unknown, k) => (obj as Record<string, unknown>)?.[k],
    translations
  ) as string ?? key;
}
```

### Language pack rules

- JSON files stored in S3: `s3://smart-attachments/locales/{en|am|or}.json`
- Loaded at app startup and cached by the service worker
- Adding a new language = upload a new JSON file to S3 + add enum value via Alembic migration
- No rebuild or redeployment required
- **Oromifa pack must be reviewed by a native Afaan Oromoo-speaking domain expert before Phase 1 go-live**

### Which languages users can pick (`ENABLED_LOCALES`)

A language pack being loadable is not the same as a language being offered. Every picker
(header `LangSwitcher`, `AuthLangSwitcher`, signup's `default_locale` select + its zod enum,
the onboarding wizard's locale step, `ProfileTab`'s tenant-admin locale select, and the landing
page's language line) reads the enabled set from `frontend/src/lib/locales-config.ts`:

- `ALL_LOCALES` — the full `en`/`am`/`or` list with endonym labels.
- `ENABLED_LOCALES` — parsed from `NEXT_PUBLIC_ENABLED_LOCALES` (comma list, build-time env
  var), default `"en,am"`. Unknown codes are ignored; `en` is always included.
- `isEnabledLocale(code)` / `resolveLocale(code)` — fall back to `en` for a disabled or
  unknown code, used wherever a stored `locale`/`default_locale` value is read back.

Turning Oromo on is a two-step, deliberate change, not a code change: finish translating
`or.json` (RB-6), then set `NEXT_PUBLIC_ENABLED_LOCALES=en,am,or` and redeploy the frontend —
the var is read at build time, so an env change alone does not take effect without a rebuild.
`/api/locales/[locale]` keeps serving all three packs regardless of `ENABLED_LOCALES`, so a
disabled locale stays loadable for review/testing even while hidden from end users.


## 27. UI/UX Rules

These rules were derived from bugs discovered during Session 5 manual testing (2026-05-23).
Each rule is backed by a regression test. PRs that violate these rules do not merge.

```
NEVER remove a product from the Inventory page because its On Hand balance is zero.
  A product that has ever had stock at a warehouse must remain visible with an
  "Out of Stock" badge (red) and be sorted to the bottom of the list.
  Filtering or hiding zero-balance products causes operators to lose track of
  stockouts and prevents replenishment. The filter condition is: show the product
  if (warehouseId in product.stock) OR getOnHand(...) > 0 OR any pending transfers
  or adjustments exist for this product at this warehouse.
  Regression test: test_zero_stock_product_remains_in_inventory

NEVER display a warehouse dropdown on the Receive Stock or Issue Stock forms.
  Both panels must auto-populate the warehouse from the authenticated user's JWT
  session (getSession().warehouseId) and display it as a read-only field.
  Allowing operators to select an arbitrary warehouse lets them record transactions
  against a facility they are not assigned to, bypassing warehouse-scope ABAC.
  The warehouse_id in the request body must always equal the user's JWT warehouseId.
  Regression tests: test_receive_stock_warehouse_from_jwt_not_input,
                    test_issue_stock_warehouse_from_jwt_not_input

NEVER put a direct Issue Stock transaction in the Reserved column.
  ISSUE is a direct On Hand deduction with no approval or reservation step.
  An ISSUE transaction writes a single ledger entry with transaction_type="ISSUE"
  and a negative quantity. It must never create a RESERVE transaction, a DRAFT
  transfer_orders row, or an adjustment_orders row. The Reserved column shows only
  outbound transfers in DRAFT/PENDING_x status. On Hand must decrease immediately
  when an ISSUE is posted; Reserved must not change.
  Regression tests: test_issue_stock_quantity_is_negative_deduction,
                    test_issue_stock_does_not_call_reserve_transaction

NEVER show the same action buttons to source and destination warehouse managers.
  At each transfer status, only the party responsible for the next action sees an
  active button. Source WM sees Dispatch at APPROVED; destination WM sees Receive
  at IN_TRANSIT. Showing both buttons to both parties causes confusion and allows
  the wrong party to advance a transfer they do not own.
  Use user.warehouse_id compared against transfer.from_warehouse_id (source actions)
  or transfer.to_warehouse_id (destination actions) to determine button visibility.
  The backend dispatch_transfer() and receive_transfer() enforce this as ABAC
  (HTTP 403 for the wrong warehouse) — the frontend must mirror this logic visually.
  Regression test: test_source_wm_sees_issue_button_at_approved

NEVER calculate the Products page stock total with a per-warehouse filter.
  The Products page shows the tenant-wide On Hand total for each product (sum across
  all warehouses the product is stocked in). It must not filter by the viewing user's
  warehouse_id. Filtering by warehouse means different users see different totals for
  the same product — a WH-A user sees 100 while a WH-B user sees 200 when the true
  tenant total is 300. Per-warehouse views belong on the Inventory page, not the
  Products page.
  Regression test: test_products_page_shows_same_total_all_wh_users

NEVER compare warehouse UUIDs without .toLowerCase() on both sides.
  JWT warehouseId claims and DB from_warehouse_id / to_warehouse_id values may
  differ in casing depending on how the JWT was issued vs how PostgreSQL serialises
  UUIDs. Strict equality (===) silently fails the comparison and hides action
  buttons (e.g. Issue, Dispatch, Receive) from the correct warehouse manager.
  Always normalise both operands: uWH === fromWH?.toLowerCase() where
  uWH = userWH?.toLowerCase(). This applies everywhere a facility-scoped identity
  check is performed in the frontend — getAvailableActions(), scopeTransfers(),
  ABAC attribute checks, and any new warehouse-scoped conditional.
  Root cause: BUG_REPORT.md §15 Bug 4 — isSrcWM UUID case mismatch.

NEVER leave a state machine missing transitions that the UI exposes as buttons.
  Every action button shown by getAvailableActions() must have a corresponding
  entry in the backend state machine (PULL_TRANSITIONS, PUSH_TRANSITIONS,
  SISTER_TRANSITIONS, ADJUSTMENT_TRANSITIONS). A button whose target status is
  absent from the machine always returns HTTP 422 INVALID_STATE_TRANSITION.
  This produces a spurious "Invalid transition" toast that masks unrelated errors
  and causes intermittent first-click failures when a concurrent session triggered
  the missing transition just before the current click.
  Specifically: REJECTED must be present in PENDING_REVIEW and PENDING_APPROVAL
  for all transfer types where the UI shows a Reject button (PULL, PUSH, SISTER).
  When adding new action buttons, update both getAvailableActions() in
  transfers/page.tsx AND the corresponding machine dict in state_machine.py
  in the same PR.
  Root cause: BUG_REPORT.md §15 Bug 3 — missing REJECTED in state machines.

NEVER render a raw i18n key as visible JSX text.
  Every string the user sees must be wrapped in t('key.name').
  If the key is missing from locales/en.json — add it first, then use t().
  After adding a key to en.json, run:
    python3 -c "..." to sync the same key to am.json and or.json.
  Prevention: bash scripts/check_i18n.sh must pass before git commit.

NEVER leave hardcoded English text in JSX, in placeholder/title/aria-label/alt
  attributes, or in a string passed directly to setError/setErr/setMsg/
  setMessage/setSaveError/setFormError/alert/confirm or as message: in
  notify({...}).
  Enforcement: scripts/check_hardcoded_jsx.py, wired into check_i18n.sh as an
  ERROR check (ships in session 19, P5).
  Genuinely untranslatable text (brand names like "SMART", example codes like
  "BRD-001" or "LOT-2026-001", currency codes like "ETB"/"USD"/"EUR",
  backend enum/status-machine codes like "PENDING_APPROVAL") gets an
  `i18n-ignore: <reason>` marker in a comment on the same line or the line
  directly above the hit — a plain `// i18n-ignore: ...` comment inside a JSX
  attribute list, or a `{/* i18n-ignore: ... */}` comment as a JSX child
  sibling for text content.
  A whole file goes on scripts/i18n_hardcoded_allowlist.txt (one line,
  `path  # reason`) only for demo-only or SA-internal debug files — keep that
  list as short as possible; prefer per-line markers everywhere else.

NEVER render a UUID directly in JSX text content.
  Warehouse/node IDs → resolve to name via API or ?? t('common.unknown')
  Tenant/org IDs → use useTenantName(org) hook
  User IDs → resolve to user.name before rendering
  Product IDs → resolve to product.name or SKU before rendering
  Fallback pattern: {value ?? t('common.unknown')} — never {value ?? rawId}

NEVER commit frontend changes without running both:
  npx tsc --noEmit          → must show 0 errors
  bash scripts/check_i18n.sh → must show PASS
```

