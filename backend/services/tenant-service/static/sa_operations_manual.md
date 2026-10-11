# SMART Platform — SA Operations Manual

**Audience:** Super Admin (SA) only — this document is SA-internal.
**Status:** Draft. Not served by any frontend route yet — do not copy into
`frontend/public/` (no login check there) and do not add it to the Help
manifest (`frontend/src/lib/help/manifest.ts`). It must get an authenticated
backend route before it is exposed to anyone, per the known gap recorded in
`docs/claude/billing-and-tenants.md` §S12.

---

## 1. Role of the SA

The Super Admin is the platform operator, not a tenant user. There is exactly
one role scope above every tenant: SA has full, unrestricted access to every
tenant on the platform (the "SA Tenant View" — see §2 below). SA actions are
never subject to a tenant's own permission/approval rules.

SA-only UI pages use a consistent inline "not authorised" pattern for non-SA
sessions (a plain restricted message, no redirect) — this is the project's
existing convention for role-gated pages, not unique to any one screen.

Key SA-only screens:
- `[org]/dashboard` — tenant registry (`GET /api/v1/tenants/sa/registry`),
  now a tenant picker; selecting a row opens that tenant's settings page.
- `[org]/settings/tenants/[tenantId]` — the single place every per-tenant SA
  action lives. Nine tabs: Profile, Plan, Contract, Status, Levels (links to
  org-setup), Contact, Features, Admin User, Activity.
- `[org]/settings/plans` — package catalog, prices, add-ons (platform-wide,
  not scoped to one tenant).

## 2. SA Tenant View

Opening a tenant from the registry (`[org]/settings/tenants/[tenantId]`)
reuses the same five TA tenant-admin tab components the TA sees on their own
profile (`tenant-admin/components/*.tsx`) — `TabProps.tenantId` switches each
tab from calling `/api/v1/tenants/me/...` (TA's own page) to the by-tenant
`/api/v1/tenants/{tenantId}/...` endpoints (SA view), and reveals SA-only
controls on top (raise/mark-paid/cancel invoices on Plan, add-ons on
Features, full contact CRUD, Status/Admin User/Activity tabs that have no TA
equivalent). This is how SA gets full visibility and control over any
tenant's configuration without a separate codebase or duplicated screens.

## 3. Creating Tenants

Two paths exist; they produce the same tenant shape but are NOT the same
workflow:

### 3.1 SA onboarding — `POST /api/v1/tenants/`
UI: `frontend/src/app/onboard/page.tsx`. One call creates the tenant and its
TA admin user atomically in a single DB transaction (`admin_name`,
`admin_email`, `admin_password` fields on the create request) — there is no
separate "create tenant then create admin" step and nothing to roll back on
partial failure.

This call accepts and sets, in one request:
- `organisation_type` (Producer / Retailer / Hybrid)
- plan tier/package → applied via `apply_package_to_tenant()`, which sets
  `plan_tier`, `max_warehouses`, `max_users`, `sku_cap`, and replaces
  `feature_flags` with the package's full flag set
- `billing_period` (`MONTHLY`/`ANNUAL`, default `ANNUAL`)
- optional `contract_start` / `contract_end` — if given, these win outright;
  if only `contract_start` is given, `contract_end` defaults to the
  subscription's own computed period end. Contract dates and the billing
  period are independent of each other (a 2-year contract can run on
  monthly billing) — see §8.
- `account_owner` — the TA admin created in the same call becomes the
  account owner (`users.is_account_owner = true`).

There is a separate `POST /api/v1/tenants/{tenant_id}/wizard` endpoint, but
**no frontend screen calls it** (2026-10 status) — it only sets
`organisation_type`, `approval_thresholds`, and `default_locale`. Plan tier
and feature flags are set once, at tenant creation, via
`apply_package_to_tenant()` — never by the wizard.

`DELETE /{tenant_id}` always returns `409 USE_DEACTIVATE` — tenants are
never hard-deleted through the API (see §9).

### 3.2 Tenant self sign-up — `POST /api/v1/tenants/public/signup`
UI: `frontend/src/app/(auth)/signup/page.tsx`, a public, unauthenticated
three-step flow (package + billing period → company/admin details → summary).
The signer-upper becomes the TA and account owner. In one DB transaction:
tenant insert (`signup_source = 'SELF_SIGNUP'`) → `apply_package_to_tenant()`
→ TA user insert (`is_account_owner = true`) → primary contact insert →
`start_subscription(status="PENDING_PAYMENT")` → terms acceptance insert →
activity-log insert → verification token issued. The verification email is
sent only AFTER commit — an email send failure never rolls back the sign-up.

A `PENDING_PAYMENT` subscription is fully usable immediately — there is no
payment enforcement anywhere yet (see §7). Rate-limited 5 signups/hour per IP
(`signup` bucket).

### 3.3 What distinguishes the two paths
- `signup_source`: `SELF_SIGNUP` vs. unset/SA-created — visible on
  `GET /sa/registry`.
- Self sign-up always starts `PENDING_PAYMENT`; SA onboarding can set
  contract dates directly and is not required to start in any particular
  subscription status.
- Self sign-up writes a `terms_acceptances` row at signup time; an
  SA-created tenant does not — its account owner is prompted to accept at
  first login instead (see §10).

## 4. Plans & Pricing

The package catalog is the single source of plan defaults — nothing is
hardcoded elsewhere in backend or frontend. `backend/shared/plans/catalog.py`
is the only place that reads or writes it (`platform_tier_config` for
limits/flags, append-only `package_prices` for prices, append-only
`platform_config_log` for every SA edit to either).

### Editing the catalog — `[org]/settings/plans` (SA-only)
- **`PATCH /platform/tier-config`** — partial update per tier: only the
  fields present in the request body change (an omitted field is left
  untouched). Editable: `max_warehouses`, `max_users`, `display_name`,
  `sku_cap` (int ≥1, or null = unlimited), `is_public`, `sort_order`,
  `feature_flags` (full replace — every key must be a known flag code, an
  unknown key is rejected). At least one tier must remain `is_public=true`
  across the whole catalog, checked before any write. Every changed field is
  logged to `platform_config_log` under a `reason` (default: `"SA
  tier-config edit"` if not supplied).
  **Catalog edits apply to new tenant creation and future plan changes
  only — existing tenants' effective limits/flags are never retroactively
  changed.**
- **`GET /platform/packages/prices[?tier=]`** — current, scheduled
  (future `effective_from`), and full history, per tier + billing period.
- **`POST /platform/packages/{tier}/prices`** — posts a new, append-only
  price row. `reason` required. `effective_from` defaults to now and cannot
  be more than 5 minutes in the past. **To correct a wrong scheduled price**,
  post a new row with the SAME `effective_from` — the newer (by
  `created_at`) row wins as "current" once that `effective_from` is reached.
  A price change never affects an existing subscription until its next
  renewal.
- **`GET /platform/config-log?entity_type=&entity_key=&limit=`** — the
  audit trail for every catalog/price/add-on change, newest first.

### VAT
All prices are shown with **15% VAT** broken out separately from the
subtotal, everywhere a price appears (signup, invoices, proration previews).

### Add-ons (platform catalog)
`[org]/settings/plans` also has an Add-ons tab (catalog + pricing, same
append-only price-history pattern as packages). See §5 for how a grant is
applied to one tenant.

### Contact details: edit in SA settings → Contact; every change needs a reason and is logged

## 5. Plan Changes (SA-only)

**TA cannot change their own plan.** `PATCH /api/v1/tenants/me/profile`
rejects any plan/billing field (`plan_tier`, `max_warehouses`, `max_users`,
`sku_cap`, `feature_flags`, `billing_period`) with `403
PLAN_CHANGE_SA_ONLY`. The TA's own Plan tab shows only
"Contact SMART to change your plan" text — no button that looks clickable.
The TA can view their plan, subscription, invoices, and add-ons; only SA can
change them.

SA changes a tenant's plan via the tenant's own settings page
(`[org]/settings/tenants/[tenantId]` → Plan tab) or `PATCH
/{tenant_id}/plan`.

### Upgrades
Entitlements (caps, feature flags) change **immediately** —
`apply_package_to_tenant()` runs as part of the same call. The new price is
charged starting from the **next invoice**, never retroactively.

- **Monthly billing:** nothing extra charged for the rest of the current
  month.
- **Annual billing:** the rest of the month the change is made in is free. A
  second, automatic PENDING invoice (`invoice_kind='PRORATION'`) is raised in
  the same transaction, covering the **whole remaining billing months**
  (counted in +1-month steps from the subscription's `current_period_start`,
  not calendar days — so a day-29/30/31 start never drifts):
  `(new_annual_price − old_annual_price_snapshot) × remaining_months / 12`,
  VAT added on top. This shows as a **Proration** invoice in the tenant's
  invoice list.
- Blocked (`409 INVOICE_PENDING_SETTLE_FIRST`) with no write at all if a
  PENDING period invoice already exists for the subscription — a pending
  PRORATION invoice never blocks anything.
- Preview before committing: `GET /{tenant_id}/proration-preview?tier=`
  (SA) returns `{remaining_months, free_until, period_end, old_amount,
  new_amount, subtotal, vat, total, currency, will_invoice, blocked_code}`.

### Add-ons
A feature not in the tenant's package can be granted on its own:
- `OVERRIDE` — free, `amount=0`, a note is required.
- `PURCHASED` — priced from the tenant's live subscription's billing period,
  same proration formula as an upgrade
  (`addon_annual_price × remaining_months / 12` on annual billing, free for
  the rest of the current month; billed with the package from the next
  invoice on monthly billing).

An add-on **survives a plan change** — `apply_package_to_tenant()` replaces
`tenants.feature_flags` wholesale on a plan change but never touches
`tenant_addons`; effective flags are always the package's flags OR'd with
every currently-active add-on grant, so a grant is never silently lost when
the tier changes. A grant is never deleted, only cancelled (`status =
CANCELLED`); cancelling stops it immediately, no refund.

Endpoints: `POST`/`GET /{tenant_id}/addons`, `POST
/{tenant_id}/addons/{id}/cancel`.

## 6. Downgrades & Refunds

> Downgrades on a paid subscription are scheduled: the tenant keeps the
> current tier until renewal; the renewal invoice is billed at the lower
> tier; the switch happens when the SA records payment of that renewal
> invoice (early recording = early switch). Same rule for monthly and
> annual. Never-paid subscriptions downgrade immediately. The SA may apply a
> downgrade immediately on customer request (no refund, no credit). An
> upgrade while a downgrade is scheduled cancels it; the SA can also cancel
> it explicitly. No refunds and no account credit for downgrades; account
> credit is deferred until the accountant confirms Ethiopian VAT credit-note
> handling. Data above the new plan's caps is kept; only new creation is
> blocked. Avoid toggling a tenant's tier down and up within one billing
> period — the re-upgrade is charged in full.

Mechanics, for the SA operating the controls:
- `PATCH /{tenant_id}/plan` takes `effective: "RENEWAL" (default) |
  "IMMEDIATE"`. `RENEWAL` on a paid-at-least-once subscription's downgrade
  only schedules it (`subscriptions.scheduled_tier`/`scheduled_at`) —
  nothing else changes until the renewal invoice is paid.
- The switch itself happens inside `mark_paid()`: if the paid invoice's
  package line is priced at the `scheduled_tier`, the subscription's
  tier/price/period update and the schedule clears in the same write.
- `DELETE /{tenant_id}/plan/scheduled` cancels a pending schedule explicitly
  (404 `NO_SCHEDULED_CHANGE` if none exists). Any upgrade, or
  `effective=IMMEDIATE`, or re-setting the current tier, also clears a
  pending schedule as a side effect.
- `PATCH /{tenant_id}/profile`'s plan-tier path has no `effective` override
  — a paid downgrade through that route always schedules; use `PATCH
  /{tenant_id}/plan?effective=IMMEDIATE` to downgrade now instead.
- A never-paid subscription (still `PENDING_PAYMENT`) always downgrades
  immediately, regardless of `effective`.

## 7. Invoices & Payments

`[org]/settings/tenants/[tenantId]` → Plan tab (SA) / TA's own Plan tab
(read-only + "How to pay" for a pending invoice).

- **Recording a payment:** SA uses `POST .../payments/{id}/mark-paid` on the
  tenant's page. This is idempotent — marking an already-paid payment again
  returns `already_paid: true` and changes nothing else. It extends
  `tenants.contract_end` forward only (`GREATEST(old, new)` — never
  backwards), and sets `contract_start` only if it was still unset.
- **Cancelling a pending invoice:** `POST .../payments/{id}/cancel` — a note
  is required.
- **Pending renewal invoices:** a subscription has at most one PENDING
  `invoice_kind='PERIOD'` invoice at a time. A scheduled downgrade (§6) may
  leave a PENDING period invoice still priced at the OLD tier if it was
  raised before the downgrade was scheduled — that invoice is paid as a
  normal same-tier renewal and does **not** trigger the downgrade switch;
  the SA should re-raise or cancel it once the renewal at the new tier is
  actually due.
- **Payment provider:** no real payment gateway is connected yet. `MANUAL`
  (SA marks paid by hand — the only provider in real use today) and `STUB`
  (a fake gateway for testing the webhook path only) are the two providers
  implemented. A tenant is fully usable before any payment is made or
  recorded — **nothing is suspended or restricted for non-payment in this
  phase** (see §8).
- **Bank / payment instructions shown to the TA** ("How to pay" on a
  pending invoice): **TBD — Alex.** The current UI text is generic
  placeholder copy with no real bank details.

## 8. Contract Dates & Expiry

The contract (`tenants.contract_start`/`contract_end`) is the commercial
agreement; it is independent of the subscription's billing period (§3.1).
`PATCH /{tenant_id}/contract` only ever touches the contract, never the
subscription.

**SA is never restricted by any of this.** Contract stage and the
read-only gate below apply only to a tenant's own staff — an SA session is
always full access, regardless of any tenant's contract state.

### Contract stages

Four stages, derived automatically from `tenants.contract_end` (no stored
status column — always computed fresh):

| Stage | When | Access |
|---|---|---|
| **Active** | No contract date set, or more than 14 days left | Full access |
| **Expiring** | ≤14 days left | Full access; warning banners |
| **Grace** | ≤14 days past `contract_end` | Full access; banners |
| **Read-only** | More than 14 days past `contract_end` | View + export only; all changes blocked |

**Read-only is a real, automatic restriction** — not alerting only. Once a
tenant is in Read-only, every write request from that tenant's own staff is
rejected with `402 CONTRACT_EXPIRED_READ_ONLY`, except for the narrow set
still allowed: own password change, Terms acceptance, managing contacts,
sending a renewal request, staff password reset, and staff deactivation
(a leaver's access must still be revocable, and a locked-out staff member
must still be able to get back in, even while the tenant itself is
read-only).

**Renewal lifts read-only immediately.** Renewal means the SA records a
payment (`POST .../payments/{id}/mark-paid`, §7) or otherwise extends
`contract_end` (`PATCH /{tenant_id}/contract`) — either moves `contract_end`
forward, and the very next request re-derives the stage from the new date,
so there is no separate "restore access" step. **Suspension stays a
separate, manual SA decision** (§9) — read-only and Suspended are
independent states; renewing a read-only tenant does not touch a
suspension, and suspending a tenant is unrelated to its contract stage.

**Expiry alerts still only reach server logs** (CloudWatch, via the outbox
`ContractExpiryAlert` handler) — there is no email yet. Emailed expiry
reminders depend on `EMAIL_DELIVERY_MODE=ses` going live and that handler
being wired to notification-service (§11); do not tell a customer to
expect an email reminder until then.

### Renewals tab — `[org]/dashboard` → Renewals (SA-only, deep link `?tab=renewals`)

- **Stage counts** — Expiring / Grace / Read-only, tenant-wide.
- **Contracts list** — every non-deactivated tenant currently in one of
  those three stages, soonest-expiring first, with its current open
  renewal request (if any).
- **Open requests queue** — renewal requests a TA submitted from their own
  Plan tab (at any contract stage, including Read-only — it is one of the
  writes still allowed there). One open request per tenant at a time; a TA
  submitting a second request while one is already open is just shown the
  existing one, not a duplicate.
- **Mark handled / Cancel** — resolves a request (a short note is
  required either way). This does not itself change the contract or renew
  anything — the SA still records the actual payment/extension (§7) as a
  separate step; marking a request handled is bookkeeping for the queue,
  not a renewal action in itself.

## 9. Suspending / Deactivating a Tenant

Three states on `tenants.status`: `ACTIVE`, `SUSPENDED`, `DEACTIVATED` (plus
`is_active` mirroring non-ACTIVE as `false`). Transitions are SA-only
(`PATCH /{tenant_id}/suspend|deactivate|reactivate`, on the tenant's Status
tab):

- **Suspend** — temporary. Rejected with `422 ALREADY_SUSPENDED` /
  `TENANT_DEACTIVATED` if already in that state or already deactivated
  (reactivate first). All of that tenant's active login tokens are revoked
  immediately (`revoke_tenant_tokens()`) — every non-SA session for that
  tenant is logged out at once, not just blocked on next login.
- **Deactivate** — intended as a longer-term/soft-delete state; data is
  preserved, never dropped. Also revokes all tenant tokens immediately.
- **Reactivate** — restores `ACTIVE` from either `SUSPENDED` or
  `DEACTIVATED`. Rejected with `422 ALREADY_ACTIVE` if already active. Does
  not by itself re-issue tokens — users simply log in again normally.
- At the login layer (`POST /auth/token`), a `SUSPENDED` tenant returns
  `403 TENANT_SUSPENDED` only **after** the password is verified — this
  deliberately avoids confirming a tenant's existence/suspension to someone
  who doesn't already know a valid password.
- Every transition is written to `tenant_activity_log` (action
  `SUSPEND`/`DEACTIVATE`/`REACTIVATE`, old/new value) — a log write failure
  never rolls back the status change itself.

Tenants are **never hard-deleted** via the API (`DELETE /{tenant_id}` always
returns `409 USE_DEACTIVATE`). Local-dev-only hard purge exists via
`scripts/delete_tenant.py` (dry-run first, requires typed `YES` confirmation,
Alex's `pg_dump` taken beforehand) — see `CLAUDE.md` §8. **Never hard-delete
a tenant in staging or prod.**

## 10. Users & Security

- **Creating users:** done by the TA within their own tenant (Org Setup →
  Personnel), not by SA. SA does not create individual tenant users except
  the one TA admin created as part of SA onboarding (§3.1).
- **Password reset — two paths:**
  - Self-service: `POST /auth/forgot-password` (always 202, no account
    enumeration) → `POST /auth/reset-password` consumes a single-use,
    SHA-256-hashed, 60-minute-TTL token. On success: new password hash,
    `must_reset_password=false`, `email_verified_at` set if unset, and the
    failed-login lockout counter for that email is cleared. Issuing a new
    reset token invalidates the user's earlier unused ones. All of the
    user's existing login tokens are revoked on a successful reset
    (`revoke_user_tokens()`), so every open session is logged out.
  - TA-initiated: TA resets a user's password from the Personnel tab
    (temporary password, forced change at next login); this also clears
    that user's login-lockout counter immediately.
  - Other TA actions that also revoke a user's tokens
    (`personnel_v2.py`, `revoke_user_tokens()`): setting a new password for
    a user via Personnel → edit user (~line 815); deactivating a user
    (~line 601); and an SA force-removing a user's sole PRIMARY position,
    which deactivates the user as a side effect (~line 525).
- **Account lockout:** real and automatic, not merely a rate limit. After 5
  failed login attempts for one email, further attempts to that email are
  rejected with `429 TOO_MANY_ATTEMPTS` for 15 minutes from the **first**
  failed attempt in the window (the counter's TTL is set only on the first
  failure, so later failures extend the count, not the window). The lockout
  clears automatically after 15 minutes, or immediately on a successful
  password reset. No admin action is required to clear it, though a TA
  reset also clears it.
- **Login rate limiting (separate from account lockout):** `login` bucket,
  20 attempts / 15 minutes **per IP**, enforced at api-gateway on the
  email/password path only (never on the local-dev `dev_email` shortcut).
  This is independent of the per-email lockout above — both can trigger.
- **Terms re-acceptance:** when `TERMS_VERSION` changes, only the tenant's
  **account owner** (`users.is_account_owner`, not every TA/user) is forced
  to re-accept at next login, via a frontend-only gate — not an API-wide
  block. An SA-created tenant's owner (no `public_signup.py` row) is treated
  the same as a stale version and accepts at their first login too.

## 11. Email

- All system emails (verification, password reset) are **English only**.
- Sender address: `no-reply@<domain>` — **domain TBD — Alex** (must be an
  SES-verified domain before `EMAIL_DELIVERY_MODE=ses` can be used).
- `EMAIL_DELIVERY_MODE`: `log` (dev only — writes the link to the service
  log at WARNING instead of sending) vs. `ses` (required in stage/prod — the
  startup config guard refuses to start a stage/prod service with anything
  else). Default when unset: `log` only if `ENVIRONMENT=local`, else
  `disabled` (raises rather than silently failing to send).

## 12. Go-Live Checklist (SA)

- [ ] Remove the `#credentials` section from the public landing page
  (`frontend/src/app/page.tsx`) and remove `SA_USER.password` from
  `frontend/src/lib/demo-data.ts` (both still present).
- [ ] Reset the SA password used during development to a fresh, strong
  credential.
- [ ] Confirm branch protection / review requirements — **current reality
  (2026-08): neither repo has server-side branch protection** (private repos
  on a free GitHub plan); direct pushes to `main` are allowed in both. This
  item is **TBD — Alex** (decide whether to upgrade the GitHub plan before
  go-live, or accept the current no-protection state).
- [ ] Confirm `EMAIL_DELIVERY_MODE=ses` and a real `EMAIL_FROM` are set in
  stage/prod (the startup guard already refuses to start otherwise — this is
  a check, not a fix).
- [ ] Confirm real bank/payment instructions are supplied (§7) before
  relying on invoices for collection.
- [ ] Confirm the Terms of Service / Privacy Policy text is finalised —
  `/terms` and `/privacy` now serve Alex's draft v0.2 (`docs/legal/*.md`),
  still marked DRAFT with open COUNSEL NOTE items (data localisation,
  pricing/VAT, SLA, liability cap, arbitration, Amharic translation); it
  is not yet lawyer-reviewed or ready to be accepted as final.

## 13. Open Items / TBD List

- Bank/payment instructions shown on a pending invoice — **TBD — Alex**.
- Email sender domain for `EMAIL_FROM` — **TBD — Alex**.
- Whether to upgrade the GitHub plan for branch protection before go-live —
  **TBD — Alex**.
- Terms of Service / Privacy Policy — draft v0.2 text is live on `/terms`
  and `/privacy` (`docs/legal/*.md`), but still **TBD — Ethiopian counsel
  and GDC management** on the open COUNSEL NOTE items in those drafts
  (data localisation under the PDP Proclamation is flagged high-priority),
  before it can be published as final.
- Account credit / Ethiopian VAT credit-note handling for downgrades —
  **TBD — accountant**; no credit is given today regardless.
- Payment gateway (Chapa, Telebirr, or similar) integration — not started;
  `MANUAL` and `STUB` are the only providers implemented today.
- This document's own publishing route — **TBD** (needs an authenticated
  backend route; must not go through `frontend/public/` or the Help
  manifest).
