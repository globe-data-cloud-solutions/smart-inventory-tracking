## 15. Tenant Profile & Onboarding Wizard

### Package Catalog is the Single Source of Plan Limits and Flags

> **Status (2026-10):** no frontend screen calls `POST /tenants/{id}/wizard`; tenants are
> created via `POST /tenants/` (SA). Since migration 070, the package catalog lives in
> `platform_tier_config` (limits, sku_cap, feature_flags), prices in append-only
> `package_prices`, and every SA change to either in append-only `platform_config_log`.

- **`backend/shared/plans/catalog.py`** is the only place plan defaults are read or written:
  `get_package()` / `list_packages()` read `platform_tier_config`; `apply_package_to_tenant()`
  sets a tenant's `plan_tier`, `max_warehouses`, `max_users`, `sku_cap` from the package and
  **replaces** `feature_flags` with the package's full flag set (an explicit override wins only
  for a field the caller actually sent). `get_tenant_entitlements()` reads a tenant's current
  effective values. No tier defaults are hardcoded anywhere else in the backend or frontend.
- Tenant create (`POST /tenants/`), SA plan change (`PATCH /{tenant_id}/plan`), and profile plan
  change (`PATCH /{tenant_id}/profile`) all call `apply_package_to_tenant()` — never set
  `max_warehouses`/`max_users`/`sku_cap`/`feature_flags` directly.
- `organisation_type` changes (profile edit or wizard) reset `approval_thresholds` only — they
  never touch `feature_flags`, which are owned by the plan/package.
- All plan enforcement (`check_plan`, `check_plan_create_user`, `check_plan_create_warehouse` in
  `shared/permissions/plan_middleware.py`) reads a tenant's effective values via
  `get_tenant_entitlements()`, never the package catalog directly and never a hardcoded table.
- **SKU cap applies to every organisation_type** — the product-service create-product check is no
  longer PRODUCER-only; it fires whenever `tenant.sku_cap` is set, regardless of org type.
- The onboarding wizard (`POST /tenants/{tenant_id}/wizard`, currently uncalled by any frontend
  screen) sets `organisation_type`, `approval_thresholds`, and `default_locale` only — no plan
  tier, no feature flags. Those are set once at tenant creation via `apply_package_to_tenant()`.

### Feature Flag Enforcement

Feature flags are checked at the API layer by `check_plan()` in `shared/permissions/plan_middleware.py`.
Actions are mapped to required flags: Sister transfers → `TRANSFERS_SISTER`, lot/batch operations → `LOT_TRACEABILITY`, etc.
Raises HTTP 402 with upgrade path when a feature is disabled (flag=False) for non-SA/non-TA users.

> **Known gap (2026-10):** `check_plan()` feature-flag enforcement is currently wired only for
> sister transfers (`inventory-service/routers/transfer.py`). Other flagged features
> (`LOGISTICS`, `AUDIT_EXPORT`, `CUSTOM_BRANDING`, `AI_ANALYTICS`, `API_ACCESS`,
> `LOT_TRACEABILITY`) are not yet gated server-side anywhere a route handles them.

### Plan Cap Enforcement

- **`check_plan_create_warehouse()`** — enforces `max_warehouses` cap when creating org nodes. One L1 (root) node is always free; all other active nodes count toward the limit.
- **`check_plan_create_user()`** — enforces `max_users` cap when creating users. The TA (Tenant Admin) account is always free; all other active users count toward the limit.

Both raise HTTP 402 when the cap is reached and include an `upgrade_to` hint in the error response.

### Self Sign-Up (S4)

Four public, unauthenticated paths exist — exact-match entries in api-gateway's
`UNAUTHENTICATED_PATHS` and allowlisted by name in `scripts/ci_drift_check.py`:

```
GET  /api/v1/tenants/public/packages          tenant-service — public package list + current prices
POST /api/v1/tenants/public/signup            tenant-service — self sign-up
POST /api/v1/auth/verify-email                auth-service   — consume a verification token
POST /api/v1/auth/resend-verification         auth-service   — always 202 (no account enumeration)
```

`POST /public/signup` runs as ONE DB transaction, `set_rls_context()` called
first, in this order: (1) INSERT tenants (`signup_source='SELF_SIGNUP'`),
(2) `apply_package_to_tenant()`, (3) INSERT the TA user
(`is_account_owner=true`), (4) INSERT the primary `tenant_contacts` row,
(5) `start_subscription(..., status="PENDING_PAYMENT")`, (6) INSERT
`terms_acceptances`, (7) INSERT `tenant_activity_log`, (8)
`issue_verification_token()`. The verification email is sent only AFTER
commit — a send failure never rolls back or fails the sign-up.

A `PENDING_PAYMENT` subscription means the tenant is fully usable immediately;
there is no payment enforcement anywhere yet — that arrives once a real
payment provider is connected (see §15 package catalog). `start_subscription()`
(`shared/billing/subscriptions.py`) is the ONLY writer of new `subscriptions`
rows and of a tenant's `contract_start`/`contract_end` (and only when those
are still unset — it never overwrites dates an SA already set by hand). All
prices include 15% VAT via `vat_breakdown()`.

Env flags (local `.env`, never committed):

```
EMAIL_DELIVERY_MODE=log           # default: "log" only when ENVIRONMENT=local, else "disabled" (raises
                                   # NotImplementedError until SES is wired up) — an explicit value always wins
EMAIL_VERIFICATION_REQUIRED=false # /token's EMAIL_NOT_VERIFIED gate is off until SES is live
APP_BASE_URL=http://localhost:3000
TERMS_VERSION=2026-10
TRUSTED_PROXY_HOPS=0               # set to 1 once behind the ALB — see §6 env var reference
STUB_WEBHOOK_SECRET=               # HMAC secret for the STUB payment provider's webhook (§15 Billing)
```

> **Known gap (2026-10):** on AWS, sign-in goes through Cognito, which has no
> user for a self-signed-up TA — only a `users` row exists locally. Local dev
> bypasses this via `dev_email`/`dev_password` on `/token`. This must be
> resolved alongside the Cognito/SES work (CLAUDE.md §2) before self sign-up
> can go live outside local dev.

**Frontend (S7):** `frontend/src/app/(auth)/signup/page.tsx` — a three-step
page (package selection with monthly/annual toggle → company/admin details
form → summary) that calls only the four public endpoints above, finishing
with a "sign in with {email}" confirmation and no auto-login.
`frontend/src/app/(auth)/verify-email/page.tsx` consumes `?token=` once
(guarded against React Strict Mode's double effect invocation) and shows
verified / invalid-or-expired (with a resend form) states. `frontend/src/app/
(auth)/login/page.tsx` links to `/signup`, prefills `?email=`, and shows a
resend form on `EMAIL_NOT_VERIFIED` (403). Both new pages require gateway
mode (`NEXT_PUBLIC_API_URL` set) — without it they show
`t("signup.unavailable")` rather than falling back to mock data.
`/verify-email` and `/resend-verification` return a raw JSON body, not the
`{success,data,...}` envelope every other endpoint uses — the frontend calls
them via `rawPost()` in `lib/api.ts`, never the enveloped `api.post()`.

> **Known gaps (2026-10):** no Terms of Service page exists yet — the signup
> checkbox links nowhere, only an i18n key placeholder; the TA Plan tab's
> "How to pay" instructions for a MANUAL invoice are generic placeholder text
> with no real bank details (`billing.manual_instructions`); and the
> Cognito/SES gap noted above still blocks self sign-up outside local dev.

### Billing (S5) — invoices, payments, providers

Schema (migration 071): `subscriptions` (one live row per tenant — `status IN
('ACTIVE','PENDING_PAYMENT','PAST_DUE')`), `payments`, append-only
`payment_line_items`. `backend/shared/billing/payments.py` is the only writer
of payment state transitions; `backend/shared/billing/providers/` is the
provider registry.

- **Invoice pricing** (`next_invoice_period()` / `create_invoice()`): a
  subscription's **first** invoice (still `PENDING_PAYMENT`, no `PAID`
  payment yet) bills the current period at the subscription's own **price
  snapshot**. Every invoice after that is a **renewal** — `start =
  current_period_end`, priced at the **current** package price at invoice
  time. A price change therefore applies at the next renewal, never
  retroactively. One `PENDING` payment per subscription at a time
  (`INVOICE_ALREADY_PENDING`, HTTP 409).
- **`mark_paid()`** is idempotent (a second call returns `already_paid:
  true` and touches nothing else), activates the subscription onto the
  paid period/price, and extends `tenants.contract_end` via
  `GREATEST(COALESCE(contract_end, …), …)` — it only ever moves forward,
  never backwards, and `contract_start` is set only if still unset.
  **Paying extends the contract; nothing is enforced on non-payment yet** —
  there is no suspension/dunning logic in this phase.
- **Providers** (`backend/shared/billing/providers/`): `MANUAL` (SA marks a
  payment paid by hand; no webhook) and `STUB` (a fake gateway for testing
  the webhook path — HMAC-SHA256 over `STUB_WEBHOOK_SECRET`, header
  `X-Stub-Signature`; missing secret or bad signature always rejects, never
  falls back to trusting an unsigned body). `get_provider(name)` is the slot
  a real gateway (Chapa, Telebirr, …) plugs into later — implement
  `PaymentProvider.checkout()` / `.parse_webhook()` and register it; nothing
  else changes.
- **Public webhook**: `POST /api/v1/tenants/public/payments/webhook/stub` —
  no SMART JWT (allowlisted in api-gateway's `UNAUTHENTICATED_PATHS` and in
  `scripts/ci_drift_check.py`); the HMAC signature **is** the auth check.
  Rate-limited 120/60s per IP. Idempotent on replay (`mark_paid()`'s own
  idempotency + `uq_payments_provider_reference`).
- **Plan change — entitlements now, billing months later (S11 supersedes the
  original S5 "no proration" rule for this one case)**: `PATCH /{tenant_id}/plan`
  (SA) and the TA profile plan change both call `apply_plan_change_with_proration()`
  (`shared/billing/proration.py`) in the same transaction as
  `apply_package_to_tenant()` — the live subscription's `tier`/`price_id`/`amount`
  update **immediately** (entitlements change now), `current_period_start`/`end`
  and contract dates are **untouched**; the new price is charged starting from
  the next invoice. No live subscription → left as-is, a warning is logged, one
  is never created here. **On top of that**, an ANNUAL subscription that has
  already been paid at least once, upgrading (new tier's current annual price >
  the old price snapshot), also raises a second, automatic PENDING invoice —
  `payments.invoice_kind = 'PRORATION'` — in the SAME transaction:
  - Billing months, not calendar days: the current period is split into
    +1-month steps from `current_period_start` (`remaining_billing_months()`,
    absolute-from-start so a day-29/30/31 start never drifts — see the
    function's own docstring). The partial billing month the change falls in
    is FREE (on the boundary day itself, the NEW month starting there is the
    free one). Whole remaining months are charged at the annual rate:
    `(new_annual_price − old_annual_snapshot) × remaining_months / 12` for an
    upgrade, `addon_annual_price × remaining_months / 12` for a PURCHASED
    add-on grant (`apply_addon_grant_with_proration()`), VAT on top
    (`prorate()` + `vat_breakdown()`).
  - MONTHLY subscriptions, downgrades/same-or-lower price, OVERRIDE add-ons,
    and a subscription that has never been paid (still `PENDING_PAYMENT`, no
    PAID payment) never raise a PRORATION invoice — **a downgrade gives no
    credit or refund for the unused part of the old tier**, by design.
  - **Blocked (409 `INVOICE_PENDING_SETTLE_FIRST`)**: an upgrade or a
    PURCHASED add-on grant is refused — no write at all — while a PENDING
    `invoice_kind='PERIOD'` invoice exists for the subscription
    (`check_not_blocked_by_pending_period_invoice()`); a PENDING PRORATION
    invoice never blocks anything, in either direction (`create_invoice()`'s
    own `INVOICE_ALREADY_PENDING` check is scoped to `invoice_kind='PERIOD'`).
  - **Paying or cancelling a PRORATION invoice changes nothing else** —
    `mark_paid()` flips only status/paid_at/provider for one and returns
    immediately, before touching the subscription, the contract, or
    `tenant_addons` (rule 8); cancelling (SA, note required) leaves the
    tier/add-on change in place.
  - **Previews** (no writes): `GET /{tenant_id}/proration-preview?tier=|addon=`
    (SA, `tenant:manage` + inline SA check) and
    `GET /me/proration-preview?tier=|addon=` (TA, `billing:view_own`) —
    exactly one of `tier`/`addon` — return `{remaining_months, free_until,
    period_end, old_amount, new_amount, subtotal, vat, total, currency,
    will_invoice, blocked_code}`, driving the SA/TA confirm dialogs.
  - Migration 073 adds `payments.invoice_kind` (`'PERIOD'` default,
    backfilled; `'PRORATION'` new). Its downgrade refuses while any
    `PRORATION` row exists (payments is never deleted).

  > **Known gap (2026-10):** a downgrade takes effect immediately (new,
  > lower entitlements right away) with no credit or refund for the unused
  > part of the current billing period — there is no "schedule this
  > downgrade for the next renewal" option yet. Future work, not S11 scope.
- **Permissions**: `billing:view` (SA, platform-wide read), `billing:manage`
  (SA, invoice/payment writes, audit-required), `billing:view_own` (TA,
  its own tenant, read-only). Endpoints: SA
  `GET/POST /{tenant_id}/subscription|invoices|payments/{id}/mark-paid|cancel`;
  TA `GET /me/subscription`, `GET /me/invoices/{payment_id}/checkout`.

### Plans & Pricing (S6) — SA package editing, price history, config log

Endpoints live in `backend/services/tenant-service/routers/tenants.py`, grouped
with the existing `/platform/tier-config` routes (fixed paths, declared above any
`/{tenant_id}` route). No new permissions — all reuse `PLATFORM_TIER_CONFIG_VIEW`
/ `PLATFORM_TIER_CONFIG_EDIT` (SA only, inline role check matches the existing
tier-config routes).

- **`PATCH /platform/tier-config`** — partial update. Each entry in `tiers[]`
  changes ONLY the fields present in that entry's JSON body
  (`model_fields_set`); an omitted field on an existing tier is left untouched.
  This is why the legacy dashboard modal body (`{tier, max_warehouses,
  max_users}`, no `reason`) still works unchanged — `reason` defaults to `"SA
  tier-config edit"` when not supplied. Editable fields: `max_warehouses`,
  `max_users`, `display_name` (1-60 chars), `sku_cap` (int ≥ 1 or `null` =
  unlimited), `is_public`, `sort_order`, `feature_flags` (full replace, not a
  merge — every key must be one of `KNOWN_FEATURE_FLAGS` in
  `backend/shared/plans/catalog.py`, the single source of valid flag codes;
  an unknown key is 422 `UNKNOWN_FEATURE_FLAG`). At least one tier must remain
  `is_public=true` across the whole catalog after the request, checked BEFORE
  any write, or 422 `NO_PUBLIC_PACKAGE`. Every field that actually changes value
  is logged to `platform_config_log`, one row per field, under the request's
  `reason`. **Changes apply to new tenant creation and future plan changes
  only — existing tenants' effective limits/flags (stored per-tenant on
  `tenants`) are never retroactively changed.**
- **`GET /platform/packages/prices[?tier=]`** — per tier + `billing_period`:
  `current` (the same row `get_current_price()` would pick, with its VAT
  breakdown), `scheduled` (`effective_from` in the future), and `history`
  (every row, newest first).
- **`POST /platform/packages/{tier}/prices`** — posts a new, append-only
  `package_prices` row. `reason` is required (non-empty after trim).
  `effective_from` defaults to now and must not be more than 5 minutes in the
  past (422 `EFFECTIVE_FROM_IN_PAST`), guarding against silently back-dating a
  price. **To correct a wrong scheduled price**, post a new row with the SAME
  `effective_from` — `get_current_price()`'s tie-break is `ORDER BY
  effective_from DESC, created_at DESC` (CLAUDE.md §14/subscriptions.py), so
  the newer (correcting) row always wins as "current" once its
  `effective_from` is reached. Existing subscriptions are untouched by a new
  price — it applies only at each subscription's next renewal
  (`next_invoice_period()`), same as the S5 "no proration" rule above. Every
  post is also logged to `platform_config_log` (`entity_type='PRICE'`,
  `entity_key='<tier>/<billing_period>'`).
- **`GET /platform/config-log?entity_type=&entity_key=&limit=`** — newest
  first, `limit` capped at 500.
- **`GET /sa/registry`** adds `signup_source`, `subscription_status`,
  `billing_period`, `current_period_end`, `last_payment_status` (latest
  payment by `created_at`, or `null`) per tenant, via one query with
  `LEFT JOIN LATERAL` on `subscriptions` and `payments` — no N+1.
- **Frontend**: `frontend/src/app/[org]/settings/plans/page.tsx`, SA-only
  (`sa.nav_plans_pricing` in `SA_NAV`, `frontend/src/app/[org]/layout.tsx`).
  Non-SA sessions see the same inline not-authorised pattern as
  `[org]/permissions/page.tsx` (a plain restricted message, no redirect) —
  this is the project's existing convention for role-gated pages that don't
  redirect. The dashboard's old tier-config modal (state, mutation, and JSX)
  was removed; its button is now a link to this screen.

### Audit rule for SA decisions (target tenant vs. platform-level)

`shared.permissions.audit.audit_log()` writes to `audit_logs`, whose
`tenant_id` column is `NOT NULL` — but an SA actor has no `tenant_id` of its
own. Tenant attribution is resolved in this priority order: the actor's own
`tenant_id`, then `resource["tenant_id"]`, then `resource["target_tenant_id"]`.
`require_permission()` (`backend/shared/permissions/middleware.py`) stashes a
route's PATH `tenant_id` (e.g. `/{tenant_id}/plan`) into
`resource["target_tenant_id"]` automatically, so an SA decision on a specific
tenant is stored under THAT tenant. When none of the three resolve — a
platform-wide SA action such as `/platform/tier-config` with no path
tenant — the row is **not inserted** (there is no tenant to attach it to);
`audit_log()` logs a `logger.warning` instead, and `platform_config_log`
remains the durable record for those changes. A DB failure during the audit
write is caught and `logger.exception`'d, never raised — this must never
break the primary request.

### SA Tenant View (S8) — reusing the TA tabs in SA mode

`frontend/src/app/[org]/settings/tenants/[tenantId]/page.tsx` — SA-only (same
inline not-authorised pattern as `[org]/settings/plans/page.tsx`: a plain
restricted message, no redirect). Opened via an "Open" action on each row of
the SA registry table (`[org]/dashboard/page.tsx`). The header (name, slug,
status, signup_source) is read from the existing `GET /sa/registry` list —
no new backend field was added for it.

The five TA tenant-admin tab components (`[org]/settings/tenant-admin/
components/*.tsx`) are **reused, not copied**: `TabProps.tenantId` is now
optional. Absent (the TA's own page) → every tab calls `/api/v1/tenants/
me/...`. Present (this SA view, the real tenant UUID) → every tab calls the
matching `/api/v1/tenants/{tenantId}/...` by-tenant endpoint instead, and
SA-only controls appear. `ProfileTab` reads via `GET /{tenant_id}` (not a
separate `/{tenant_id}/profile` route — that endpoint doesn't exist, since
`GET /{tenant_id}` already returns every field the tab needs) but still
writes via `PATCH /{tenant_id}/profile`.

SA-only additions, each linking to the existing edit surface rather than
duplicating it:
- **Plan tab**: raise invoice (`POST /{tenant_id}/invoices`), mark paid
  (`POST .../payments/{id}/mark-paid` — the confirm step shows the amount and
  the invoice's `period_end`, which becomes the tenant's new contract end,
  using data already loaded by `GET /{tenant_id}/subscription`, before
  submitting), cancel (`POST .../payments/{id}/cancel`, note required).
  Billing error codes (`INVOICE_ALREADY_PENDING`, `NO_LIVE_SUBSCRIPTION`,
  `INVALID_PAYMENT_STATE`, `WRONG_PROVIDER`, `PRICE_NOT_AVAILABLE`,
  `PAYMENT_NOT_FOUND`) map to `sa_tenant.billing_error.<code>` i18n keys.
  **Since S9, this tab also has the tier-change + SKU-cap form** — see below.
- **Contacts tab**: full create/edit via `POST`/`PATCH /{tenant_id}/
  contacts(/{id})` (added in S8-1). No delete in SA mode — no by-tenant
  delete route exists.
- **Features tab**: read-only plan-granted matrix in both modes, plus
  **since S9** an SA-only "Feature overrides" editor — see below.

`DELETE /{tenant_id}` always returns `409 USE_DEACTIVATE` — tenants are never
hard-deleted (§1, §28). Its one caller, the onboarding wizard's rollback on a
failed signup, is gone: `POST /api/v1/tenants/` already creates the tenant
and its TA admin atomically in one DB transaction (`admin_name`/
`admin_email`/`admin_password`), so `frontend/src/app/onboard/page.tsx`'s
`launch()` sends those fields in its single step-1 call instead of a separate
`POST /{tenantId}/users` step — there is nothing left to roll back.

### S9 — contract vs. billing period, and the SA tenant page absorbs the dashboard's Admin tab

**Decision B — contract and billing period are independent.** The CONTRACT
(`tenants.contract_start`/`contract_end`) is the commercial agreement; the
SUBSCRIPTION's billing period (`subscriptions.billing_period`,
`current_period_start`/`end`) is the billing cycle. A 2-year contract can run
on monthly billing; they are unrelated except that the subscription's first
period starts on the contract start (or today, if no contract start is
given). `POST /api/v1/tenants/` (`TenantCreateRequest`) accepts optional
`contract_start`, `contract_end`, and `billing_period` (default `ANNUAL`);
`contract_end` defaults to the subscription's own computed period end when
only `contract_start` is sent. `start_subscription()`
(`shared/billing/subscriptions.py`) still only fills
`contract_start`/`contract_end` when both are NULL — an explicit contract in
the create call always wins outright. `PATCH /{tenant_id}/contract` remains
contract-only and never touches the subscription (regression-tested).
`mark_paid()`'s GREATEST rule — paying never moves `contract_end` backwards —
is unchanged and is not re-litigated by this decision. The onboarding wizard
(`frontend/src/app/onboard/page.tsx`) sends `contract_start`/`contract_end`/
`billing_period` in the same `POST /api/v1/tenants/` call — there is no
longer a separate `PATCH .../contract` step after create.

**The SA tenant page (`[org]/settings/tenants/[tenantId]/page.tsx`) is now
the single place every per-tenant SA action lives**, folded in from the old
dashboard "Tenant Admin" tab (which is now a picker only — see below). Nine
tabs: Profile, Plan, Contract, Status, Levels (a link to org-setup), Contact,
Features, Admin User, Activity. `Plan`, `Contract`, and `Features` are the
shared `tenant-admin/components/*.tsx` used by both the TA's own page and
this one (switched to SA-by-tenant endpoints via `tenantId`); `Status`,
`Admin User`, and `Activity` are SA-only components under this page's own
`components/` directory (no TA equivalent — these actions have no TA-facing
form). **Plan limits shown anywhere in this UI are always read live from
`GET /api/v1/tenants/platform/tier-config`** (`PlanTab`'s tier-change buttons,
the onboarding wizard's tier cards) — never a hardcoded or translated string;
`wizard.tier_desc.*` and `sa.plan_modal_caps` (the old hardcoded "STARTER: ...
GROWTH: ... ENTERPRISE: ..." caption) were deleted for this reason. The
Contract tab shows the billing period as a separate, clearly-labelled
read-only line (`tenant_admin.contract.billing_period_label`) next to the
contract dates, in both SA and TA mode — the two are never merged into one
field, per decision B above.

**Feature overrides became add-ons in S10** — see the dedicated S10 section
below. The raw `tenants.feature_flags` toggle UI this paragraph used to
describe (and its plan-change-wipes-it caveat) is gone; `PATCH
/{tenant_id}/feature-flags` now always 409s `USE_ADDONS`.

The dashboard's "Tenant Admin" tab (`saTab === "admin"`, `[org]/dashboard/
page.tsx`) is now a tenant picker only: selecting a tenant navigates straight
to `/settings/tenants/[tenantId]`. All of its old inline sub-tab JSX, state,
and handlers (`selectAdminTenant`, `doAdminSave`,
`handleAdminProfileSave`/`PlanSave`/`ContractSave`/`StatusAction`/
`FeatureFlagsSave`/`TaUserSave`/`ContactsSave`) were deleted — 933 lines.
Cross-links that used to jump straight into the old inline Contacts sub-tab
(a registry row's contact name, the personnel modal's "no contacts" CTA) now
navigate to the tenant's settings page instead.

**Bug found and fixed during this work**: `PATCH /{tenant_id}/feature-flags`
(`update_feature_flags` in `tenants.py`) had no `return` after a successful
change — it fell off the end of the function and returned `None`, which
FastAPI's `response_model` validation rejected with a 500 (surfaced to the
user as a raw Pydantic traceback). This had been broken since the route was
written; nothing exercised the "real change" branch until the new Feature
overrides UI did. Fixed with a regression test
(`tests/unit/test_feature_flags.py`).

### S10 — add-ons: per-tenant feature overrides survive a plan change

Migration 072 adds three tables. **`platform_addons`** is the platform-level
catalog (no `tenant_id`, no RLS) — one row per feature flag that is NOT
`true` in every package tier (`CORE_INVENTORY`, `LOT_TRACEABILITY`,
`TRANSFERS_PULL_PUSH` are excluded since every package already grants them).
**`addon_prices`** is append-only, same shape and rules as `package_prices`
(SA posts a new price; a correction reuses the same `effective_from`, newest
`created_at` wins). **`tenant_addons`** is tenant-scoped (RLS, no FORCE) —
one row per grant: `source` is `OVERRIDE` (free, `amount=0`, note required)
or `PURCHASED` (priced from the tenant's live subscription's
`billing_period`, snapshotting `price_id`/`amount` at grant time); `status`
is `ACTIVE`/`CANCELLED` — a grant is never deleted, only cancelled.

`get_tenant_entitlements()` (`shared/plans/catalog.py`) is what makes a
grant take effect: `feature_flags` = the tenant's package flags **OR**'d
with every currently-`ACTIVE`, in-window (`starts_on <= today`, `ends_on`
NULL or in the future) `tenant_addons` row — an add-on only ever adds a
flag, never removes one the package already grants. The result also carries
`addons: [codes]`. `apply_package_to_tenant()` (a plan change) still
replaces `tenants.feature_flags` wholesale but **never touches
`tenant_addons`**, so a granted add-on survives a plan change by
construction — this is the S10 fix for the S9 "overrides reset on plan
change" gap. Every feature-display and enforcement path (`check_plan`,
`GET /me/plan`, `GET /{tenant_id}/plan`) reads through this function.

`PATCH /{tenant_id}/feature-flags` (the raw per-tenant toggle route from S9)
is gone as a working endpoint — it always returns `409 {"code":"USE_ADDONS"}`
now. The route and its permission stay registered only so the CI drift check
still sees a `@require_permission`'d action for it.

**Endpoints** (`backend/shared/billing/addons.py` is the single writer of
`tenant_addons`): SA catalog — `GET`/`PATCH /platform/addons[/{code}]`,
`POST /platform/addons/{code}/prices` (`tenants.py`, grouped with the
package catalog routes, same reason/`platform_config_log` rules, entities
`ADDON`/`ADDON_PRICE`). Tenant grants (`billing.py`, same file as
subscriptions/payments) — `POST`/`GET /{tenant_id}/addons`,
`POST /{tenant_id}/addons/{id}/cancel` (SA, `billing:manage`/`billing:view`),
`GET /me/addons` (TA, `billing:view_own`). `grant_addon()` raises
`FEATURE_ALREADY_IN_PACKAGE` (422) if the tenant's package already grants
the flag, `ADDON_ALREADY_ACTIVE` (409) if one is already live, and for
`PURCHASED`, `NO_LIVE_SUBSCRIPTION` (409) / `ADDON_PRICE_NOT_AVAILABLE` (422)
if no current price exists for the subscription's billing period.

**Invoices**: `create_invoice()` adds one `ADDON` line item per `ACTIVE`
`PURCHASED` add-on (`amount > 0`), priced by the same is-renewal rule as the
`PACKAGE` line — the subscription's first invoice bills each add-on at its
own grant-time snapshot, a renewal re-prices it at the add-on's *current*
price for that billing period (falling back to the last known snapshot if
that add-on has no current price, so one add-on never blocks invoicing the
rest). `mark_paid()`'s price-adoption read is scoped to `item_type =
'PACKAGE'` explicitly, and separately adopts each `ADDON` line's price onto
its `tenant_addons` row. No proration, same as packages: an add-on added
mid-period is billed starting from the next invoice.

**Frontend**: the SA tenant page's Features tab replaces the old raw
override toggles with a full Add-ons section (grant free override / add
purchased add-on with a next-invoice price preview / cancel) and every
package feature now shows its source — Package / Add-on / Not included.
SA Plans & Pricing gained an Add-ons tab (catalog + pricing, mirrors the
Packages/Prices tabs). The TA's own Plan tab shows add-ons read-only plus
invoice line items; its Features tab shows the same source labels,
read-only (no management controls there).

### S12 — plan changes are SA-only; Help & Documents; draft public legal pages

**Plan changes are SA-only.** `PATCH /api/v1/tenants/me/profile` now rejects
a body containing any plan/billing field (`plan_tier`, `max_warehouses`,
`max_users`, `sku_cap`, `feature_flags`, `billing_period`) with `403
PLAN_CHANGE_SA_ONLY` — checked against the raw JSON body (`request.json()`),
since `TAProfileUpdateRequest` has no field for them and Pydantic would
otherwise just silently drop them rather than reject the request. Every
other field (`default_locale`) is unaffected. SA's `PATCH /{tenant_id}/plan`
and `/{tenant_id}/profile` are unchanged — they are the only way a tenant's
package changes. `GET /me/proration-preview` is removed (no UI ever called
it — `PlanTab.tsx`'s `TierChangeForm` only renders when an SA is viewing a
tenant by id; the TA's own Plan tab never had a tier-change control). The
SA-by-tenant `GET /{tenant_id}/proration-preview` is unaffected. The TA
Plan tab's old "Ready to Upgrade?" card (a button with no handler) and
`upgrade_hint` box are both replaced by one line of plain text,
`tenant_admin.plan.contact_sa_to_change` — no control that looks clickable.

**Help & Documents** (`frontend/src/app/[org]/help/`): a typed manifest
(`frontend/src/lib/help/manifest.ts`, `HELP_MANIFEST`) lists every document
— `id`, `titleKey`/`summaryKey`, `audience` (`SA`/`TA`/`MANAGER`/`STAFF`/
`ALL`), `file` (served from `frontend/public/help/`) or `link` (an external
path like `/terms`), and `status` (`published`/`coming_soon`).
`roleToAudience()` maps SA→SA, TA→TA, NM/RM/WM/LM→MANAGER, everything
else→STAFF; `isDocVisibleToRole()` additionally makes **SA see every
audience** — the one role-mapping exception. `/[org]/help` lists only the
docs visible to the viewer (coming-soon cards show a badge and are not
links); `/[org]/help/[docId]` fetches `file` from `/help/<file>` and renders
it with `DocumentRenderer` (`frontend/src/components/features/help/
DocumentRenderer.tsx`) — `react-markdown` + `remark-gfm`, **no `rehype-raw`**
so markdown-authored HTML never executes, Tailwind classes via the
`components` prop, a small GitHub-style slug function on headings (lowercase,
drop anything not `[a-z0-9 _-]`, turn each space into one hyphen — no
collapsing, matching the anchors already written into
`TA_ONBOARDING_GUIDE.md`) so `#anchor` links scroll, and images rendered as
`[alt text]` rather than an `<img>` request. **`frontend/public/` is served
with no login check** — never point a manifest `file` at anything
SA-internal; the SA Operations Manual entry has no `file` for exactly this
reason and will need an authenticated backend route once it's written.

`docs/TA_ONBOARDING_GUIDE.md` stays the single source of truth;
`scripts/sync_help_docs.sh` copies it to `frontend/public/help/
ta-onboarding-guide.md` and `scripts/check_help_docs.sh` (wired into
`frontend/package.json`'s `build` script, alongside `check_i18n.sh`) fails
CI if the two drift apart. Help nav entry (`nav.help`) added to both
`SA_NAV` and `TENANT_NAV` in `[org]/layout.tsx`.

**Public draft `/terms` and `/privacy`** (`frontend/src/app/(auth)/terms/`,
`.../privacy/`, both built on the shared `LegalDocPage` component): no
session required, same gradient/card shell as `/signup`, a language picker,
and a DRAFT banner (`legal.draft_banner`). Content is `frontend/public/
legal/{terms|privacy}-<version>.md` — **headings only, every section reads
"[To be supplied]"**; per this task's own instruction, no ToS/Privacy
clause text is invented anywhere in this codebase. `<version>` is read from
the public packages endpoint's existing `terms_version` field (no new
public endpoint). `/signup`'s terms checkbox and the `/login`/`/signup`
footers link to both.

**Terms acceptance is shown, read-only, to TA and SA**:
`GET /api/v1/tenants/me/terms-acceptance` (TA, `tenant:view` — the same
permission `GET /me/profile` uses, since this is tenant data, not billing)
and `GET /{tenant_id}/terms-acceptance` (SA, `tenant:manage` + the usual
inline SA-only check) both return `{accepted_version, accepted_at,
accepted_by_email, current_version}`, reading the newest row (there should
only ever be one) from `terms_acceptances` joined to `users` for the email.
`terms_acceptances` is written only by `public_signup.py` (§15 S4) — an
SA-created tenant (`POST /tenants/`) never gets a row, which these routes
report as all-null fields, not an error. The TA/SA-shared `ProfileTab.tsx`
(`tenant-admin/components/`) shows "Terms of Service version {v} accepted
on {date} by {email}" with a `(View)` link to `/terms`, or "No Terms of
Service acceptance on record" when there's no row; when
`accepted_version != current_version` an info-only note is added — no
blocking, no re-accept flow (future work).

**Known gaps (2026-10):** the real, lawyer-reviewed Terms of Service and
Privacy Policy text does not exist yet — both pages are an outline only; no
re-accept flow exists for when `TERMS_VERSION` changes (the TA/SA acceptance
line just notes it's outdated); the SA Operations Manual is SA-internal and
has no file yet, and when written must be served by an authenticated
backend route rather than a `frontend/public/` file; every Help document's
body is English-only (the chrome translates, `help.english_only_notice`
covers the body); and a downgrade followed by a re-upgrade within the same
annual period is charged again in full with no credit for the earlier
downgrade (§15 S11's existing "downgrade gives no credit" rule, now also
reachable only by SA since S12 — SA should avoid toggling a tenant's tier
back and forth within one billing period).

