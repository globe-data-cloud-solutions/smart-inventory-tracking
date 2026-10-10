# SMART Inventory — Getting Started

**Part 1 of 2 — Before you sign up.** Part 2, [the TA Onboarding Guide](TA_ONBOARDING_GUIDE.md),
covers setting up your workspace once you're in.

**Version:** 1.0 | **Updated:** October 2026 | **Audience:** Anyone considering SMART Inventory

---

## Before You Begin

Have the following ready before you start:
- Your organisation chart (levels, names, locations)
- List of all staff with their roles and locations
- Transfer and approval policies (who approves what, at what quantities)
- Product list (names, SKUs, units of measure, categories)
- Organisation logo and banner image (optional, for branding)

You don't need all of this on day one — setup can proceed in stages — but having it
ready speeds up the ~45–90 minutes of initial configuration (see
[What happens after you submit](#what-happens-after-you-submit) below).

---

## Getting your account — two ways in

**Option A — Sign up yourself (self sign-up)**

1. Open the SMART Inventory sign-in page and click **Create an account**.
2. **Choose a package** — Starter, Growth or Enterprise — and a billing period
   (**Monthly** or **Annual**). Each card shows the limits, the included features and the
   price, with 15% VAT and the total shown separately.
3. **Enter your details** — company name, organisation type (Producer, Retailer or Hybrid),
   industry (optional), language, an optional custom web address for your workspace,
   and your own name, email and password (at least 8 characters).
4. **Accept the Terms of Service**, review the summary and submit.
5. You will see **"Sign in with {your email}"**. Go to the sign-in page and use the email
   and password you just chose.

**Option B — Onboarded by SMART**

Your SMART administrator creates the workspace and your TA account and sends you:
- **URL:** your SMART Inventory web address
- **TA Email:** the email address registered for you
- **Initial Password:** a temporary password — you will be asked to change it at first sign-in

---

## Verifying your email

After self sign-up, SMART sends a **verification link** to your email address. Open it within
**48 hours**. If the link has expired or you did not receive it, use **Resend link** on the
verification page or on the sign-in page.

> **Current version:** email verification is being rolled out. Until it is switched on,
> you can sign in before verifying — but verify anyway so your account is ready when it is enforced.

---

## Login

- Sign in with your email and password.
- After 5 failed attempts the account is locked for 15 minutes.

---

## System Roles (summary)

SMART uses a fixed set of roles, defined by the platform. You assign staff to these roles
when creating positions and user accounts (covered in Part 2).

| Role | Code | Scope |
|------|------|-------|
| Super Admin | SA | Platform-wide — not used within your organisation |
| Tenant Administrator | TA | Full tenant — this is you |
| National Manager | NM | Full tenant — senior operational role |
| Regional Manager | RM | Regional scope |
| Warehouse Manager | WM | Warehouse scope |
| Logistics Manager | LM | Node-scoped (or tenant-wide read-only) |
| Auditor | AU | Tenant-wide, read-only |

### Role Hierarchy

TA (highest tenant authority)

└── NM (National/Factory level)

└── RM (Regional level)

└── WM (Warehouse level)

LM (node-scoped when assigned a position; tenant-wide read-only otherwise)

AU (cross-cutting, read-only)

---

## Setup Order (overview)

Once you're in, setup follows this order — each step depends on the previous one. Part 2
covers each step in detail.

| Step | What |
|------|------|
| 1 | Organisation Levels |
| 2 | Organisation Tree |
| 3 | Positions |
| 4 | Personnel (Users) |
| 5 | Transfer Types |
| 6 | Approval Rules |
| 7 | Products & Categories |
| 8 | Opening Stock |
| 9 | Branding (optional) |

---

## Plan Tiers (summary)

SMART workspaces are on one of three packages: **Starter**, **Growth**, or **Enterprise**.
You choose a package when you sign up, or your SMART administrator assigns one when they
onboard you.

| | Starter | Growth | Enterprise |
|---|---|---|---|
| Warehouses / org nodes | 3 | 10 | Unlimited |
| Staff accounts | 5 | 25 | Unlimited |
| Products (SKUs) | 500 | 1,500 | Unlimited |
| Sister (Branch Exchange) Transfers | — | ✓ | ✓ |
| Logistics & Fleet Management | — | ✓ | ✓ |
| AI Forecasting & Analytics | — | — | ✓ |

> **The figures above are defaults and may be revised.** The sign-up page always shows the
> current package contents and prices. Part 2's [Plan Tiers (Packages)](TA_ONBOARDING_GUIDE.md#plan-tiers-packages)
> section covers pricing, proration and add-ons in full once you're in.

---

## Choices you make at sign-up

A few sign-up choices are worth knowing about before you commit:

- **Package.** Changes go through SMART — you cannot change your package yourself from
  within the application; contact your SMART administrator to upgrade or downgrade.
- **Billing period.** Switching between monthly and annual isn't available yet — contact
  SMART if you need to change it.
- **Organisation type** (Producer, Retailer or Hybrid). This sets your default approval
  thresholds. Only SMART can change it later.
- **Workspace web address** (the custom URL/slug you optionally choose). This is
  **permanent** — it cannot be changed after sign-up.
- **Default language.** Unlike the choices above, this one is *not* permanent — you (the
  TA) can change it later yourself, in **Settings → Tenant Admin → Profile**.

---

## What happens after you submit

- The person who signs up becomes the **Tenant Administrator (TA)** and the **account
  owner** of the workspace — the main contact for the subscription and invoices.
- You'll be asked to **verify your email** (see above) — do this even if the system lets
  you sign in before verifying.
- Your workspace is **usable immediately** — you do not have to wait for payment before
  starting setup.
- Initial configuration (organisation structure, staff, products, opening stock) takes
  about **45–90 minutes**. Part 2 walks through it step by step.

---

*Document Version: 1.0 | Last Updated: October 2026 | Maintained by: Development team*
