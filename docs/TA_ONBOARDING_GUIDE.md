# SMART Inventory — TA Onboarding Guide

**Version:** 1.6 | **Updated:** October 2026 | **Audience:** Tenant Administrators & Organisation Managers

**v1.6 changelog:** Step 1 (Organisation Levels) and the "Can I change org levels later?" FAQ
now reflect the ability to add a level below the bottom level, or remove it while empty,
after the initial save.

**Part 2 of 2 — Setting up your workspace.** New here? Read
[Getting Started](GETTING_STARTED.md) (Part 1) first — before you begin, getting your
account, verifying your email, login, system roles, setup order, and plan tiers all live
there.

> **Pre-Launch Reminder:** Replace all `[SCREENSHOT PLACEHOLDER]` notes with real screenshots before sharing with customers.

---

## How to Use This Guide

This guide covers two audiences:

| Audience | Sections |
|----------|----------|
| **All Users** (NM, RM, WM, LM, AU) | Steps 7–8, NM Quick Reference, Common Questions |
| **🔒 Tenant Administrator (TA) Only** | Steps 1–6, 9, User Management, Approval Rule Changes |

> **TA-only sections** are marked with 🔒 throughout this guide.

**Estimated setup time:** 45–90 minutes for initial configuration.

### How Roles Map to Your Organisation

When you create a **Position** (Step 3), you assign it one of SMART's predefined role
codes (see [Getting Started → System Roles](GETTING_STARTED.md#system-roles-summary) for
the full list):

- **L1 nodes** (top level, e.g. Main Factory) → assign **NM** positions
- **L2 nodes** (e.g. Regional Center) → assign **RM** positions
- **L3 nodes** (e.g. Sub Region) → assign **RM** positions
- **L4 nodes** (e.g. Warehouse Area, stock-holding) → assign **WM** positions
- **LM** positions can be created at **any node level** — the LM is then scoped to
  that exact node
- **Tenant-wide** (not tied to a node) → **AU** positions, and **LM** accounts
  created without a position

> **Note:** The TA role is your administrator account only — you do not create TA positions for regular staff. NM is the highest role your operational staff will use.

---

## Plan Tiers (Packages)

SMART workspaces are on one of three packages: **Starter**, **Growth**, or **Enterprise**.
You choose a package when you sign up, or your SMART administrator assigns one when they
onboard you. To **change** package later, contact your SMART administrator — you cannot
change it yourself from within the application.

Each package sets your limits and which features are included. Typical defaults:

| | Starter | Growth | Enterprise |
|---|---|---|---|
| Warehouses / org nodes | 3 | 10 | Unlimited |
| Staff accounts | 5 | 25 | Unlimited |
| Products (SKUs) | 500 | 1,500 | Unlimited |
| Core Inventory Management | ✓ | ✓ | ✓ |
| Pull & Push Transfers | ✓ | ✓ | ✓ |
| Lot & Batch Traceability | ✓ | ✓ | ✓ |
| Sister (Branch Exchange) Transfers | — | ✓ | ✓ |
| Logistics & Fleet Management | — | ✓ | ✓ |
| Audit Log Export | — | ✓ | ✓ |
| Custom Branding | — | ✓ | ✓ |
| AI Forecasting & Analytics | — | — | ✓ |
| API Access | — | — | ✓ |

> **The figures above are defaults and may be revised.** The sign-up page always shows the
> current package contents and prices, and **Settings → Tenant Admin → Plan** shows the
> exact limits and features that apply to *your* workspace. Packages are revised from time
> to time; a revision applies to new sign-ups and plan changes, and does not change an
> existing workspace's limits by itself.

**One warehouse and the TA account are free.** Your first top-level org node and your own TA
account do not count toward the warehouse and staff-account limits.

**Prices.** Every package has a monthly and an annual price. Prices are shown before VAT,
with **15% VAT** and the total shown separately. A price change applies to your
**next renewal**; it never changes an invoice you have already received.

**Changing package.** Package changes are made by your SMART administrator. The new limits
and features apply **immediately**, and the new price is charged from your **next invoice**.

- **Monthly billing:** nothing extra is charged for the rest of the current month.
- **Annual billing — upgrade:** the rest of the month you upgrade in is free. For the
  **whole months left** in your current year, you receive an invoice for the
  **difference** between the new and old annual prices, pro-rated by month, plus VAT.
  *Example:* Starter 1,000 → Growth 2,000 with 7 whole months left:
  (2,000 − 1,000) × 7 ÷ 12 = 583.33 + 87.50 VAT = **670.83 ETB**.
- **Downgrade:** the lower limits apply immediately. There is **no refund or credit** for the
  current period; the lower price applies from your next invoice.

This upgrade invoice is marked **Proration** in your invoice list. Paying it does not change
your contract or billing dates.

**Add-ons.** A feature that is not in your package (for example API Access) can be added
on its own by your SMART administrator. It works immediately and is billed with your package
from the next invoice. On **annual** billing you also receive a **Proration** invoice for the
whole months left in your current year at the add-on's annual price (pro-rated by month,
plus VAT); the rest of the current month is free. Cancelling an add-on stops it immediately,
with no refund.

> While an ordinary invoice is waiting for payment, package and add-on changes are paused
> until it is paid or cancelled, so that invoice is never issued at the wrong price.

> **Branch Exchange (Sister) transfers — Starter tier restriction:** Lateral transfers
> between warehouses at the same level are not available on the Starter tier. If staff
> attempt to create one they will receive a plan-limit error. If this feature is
> required, contact your SMART administrator about upgrading to Growth or Enterprise.

> **Hitting a limit during setup:** If you receive an error when trying to add a
> warehouse (Step 2), a staff account (Step 4) or a product (Step 7), you have likely
> reached your plan limit. Contact your SMART administrator to request a tier upgrade
> rather than assuming it is a bug.

---

## 🔒 Your Plan, Subscription & Invoices (TA Only)

*Settings → Tenant Admin*

The Tenant Admin page has five tabs:

| Tab | What you can do |
|-----|-----------------|
| **Profile** | View and update your organisation's details |
| **Plan** | See your package, limits, features, subscription and invoices |
| **Contract** | See your contract start and end dates (read-only) |
| **Contact** | Manage your organisation's contact people |
| **Features** | See which features your package includes |

### Subscription status

The **Plan** tab shows your subscription — package, billing period, current period and the
amount including VAT — with one of these statuses:

| Status | Meaning |
|--------|---------|
| **Pending payment** | Your workspace is fully active. Your first invoice has not been paid yet. |
| **Active** | Your current period is paid. |
| **Past due** | A renewal is overdue. Contact SMART to settle it. |
| **Cancelled** | The subscription has ended. |

> **Current version:** an unpaid invoice by itself does not restrict or suspend your
> workspace. What does restrict it is your **contract end date** passing without renewal
> — see [Contract dates](#contract-dates) and
> [What happens when our contract ends?](#common-questions) below.

### Invoices and how to pay

SMART issues your invoices; they appear in the **Invoices** list on the Plan tab with the
period, subtotal, VAT, total and status (Pending, Paid, Failed, Cancelled).

For a **Pending** invoice, click **How to pay** for the payment instructions.

`[PAYMENT INSTRUCTIONS PLACEHOLDER — bank name, account name and number, reference to quote, and where to send the receipt. To be supplied before go-live.]`

When SMART confirms your payment, the invoice shows **Paid**, your subscription becomes
**Active**, and your **contract end date moves forward** to the end of the paid period.

### Contract dates

Your contract runs from your sign-up (or onboarding) date for one billing period, and is
extended each time a payment is confirmed. The Contract tab is **read-only**; contract dates
are managed by SMART. Contact SMART to change them.

Your workspace moves through four stages as your contract end date approaches and passes:

| Stage | When | What you can do |
|-------|------|------------------|
| **Active** | More than 14 days before your contract end date | Everything, as normal |
| **Expiring** | 14 days or less before your contract end date | Everything, as normal — with a warning banner |
| **Grace** | Up to 14 days after your contract end date | Everything, as normal — with a banner |
| **Read-only** | More than 14 days after your contract end date | View and export only — see below |

**Read-only** blocks every new transaction, approval, edit or upload. You can still: log in,
view and export your data, change your own password, accept Terms updates, manage your
contacts, reset a staff member's password, and deactivate a staff account. Everything else
is blocked until SMART records your renewal — see
[How do I request renewal?](#common-questions) below. Your account being read-only is
separate from **suspension**, which only happens if SMART deliberately suspends your
workspace (see your SMART contact) — a lapsed contract alone does not suspend you.

---

## 🔒 Step 1 — Organisation Levels (TA Only)

*Org Setup → Organisation Levels tab*

Define how many levels your organisation has and what each level is called.

1. Go to Org Setup → click "Organisation Levels"
2. Enter the number of levels (typically 3–5)
3. Name each level in plain language
4. Mark the lowest level as **Stock Holding** — this is where physical stock is tracked
5. Save

**After saving**, you can still add a level below the current bottom level, or remove the
bottom level if it has no org nodes yet. Inserting or removing a level in the middle of the
stack is not self-service — contact SMART support for that.

Example 4-level structure:

| Level | Example Name | Notes |
|-------|-------------|-------|
| L1 | Main Factory | Top of hierarchy |
| L2 | Regional Center | Regional hubs |
| L3 | Sub Region | Optional intermediate level |
| L4 ★ | Warehouse Area | ★ Mark as Stock Holding |

`[SCREENSHOT: Organisation Levels tab showing 4 levels configured]`

---

## 🔒 Step 2 — Organisation Tree (TA Only)

*Org Setup → Organisation Tree tab*

Create the actual nodes (factories, offices, warehouses) using the levels from Step 1.

1. Click "+ Add Node" and start with your top-level node (e.g. "Factory A")
2. Select the level (L1) and enter the name
3. Add child nodes — select the parent first, then add child
4. Repeat until your full org chart is in the system

**Tips:**
- Not all branches need the same depth (mixed-depth structures are supported)
- Use consistent, official names — they appear in reports and audit logs
- You can add more nodes later as your organisation grows
- Node creation is subject to your plan tier's warehouse limit — if you receive an error when adding a node, contact your SMART administrator to request more capacity rather than assuming it is a bug (see [Plan Tiers](#plan-tiers))

`[SCREENSHOT: Organisation Tree showing two-factory structure]`

---

## 🔒 Step 3 — Positions (TA Only)

*Org Setup → Positions tab*

Positions link people to nodes and determine what they can do.

1. For each node, create at least one main position
2. Recommended: add an assistant position for coverage
3. Set the title (appears in approval notifications and audit logs)
4. Select the role level: **NM** (top), **RM** (mid), **WM** (warehouse)

**Examples:**

| Node | Main Position | Assistant |
|------|--------------|-----------|
| Factory A (L1) | "HQ Director (NM)" | "Deputy HQ (Asst NM)" |
| Region A (L2) | "Region A Manager (RM)" | "Region A Deputy (Asst RM)" |
| WHA1 (L4) | "WHA1 Warehouse Manager (WM)" | "WHA1 Warehouse Assistant (WM)" |

💡 **Tip:** Position titles appear throughout the system — use official, recognisable titles.

`[SCREENSHOT: Positions tab showing positions for Factory A and Warehouse nodes]`

---

## 🔒 Step 4 — Personnel (Adding Users) (TA Only)

*Org Setup → Personnel tab*

1. Click "+ Add Person" and enter name and email
2. Select their system role (NM / RM / WM / LM / AU)
3. Assign them to a position (links them to their org node)
4. Set an initial password (they'll be prompted to change on first login)
5. Repeat for all staff

**Email format suggestion:** `role_locationname@yourcompany.com`
- Example: `wm_warehouse1@company.com`
- Example: `rm_region_a@company.com`

👥 **Note:** A person can be assigned to multiple positions — their permissions are the combination of all assigned positions.

> **Staff account limit:** Adding accounts is subject to your plan tier's user limit. If you receive an error when adding a new person, you have reached your plan cap — contact your SMART administrator to request an upgrade rather than assuming it is a bug (see [Plan Tiers](#plan-tiers)).

`[SCREENSHOT: Personnel tab showing user list with positions assigned]`

---

## 🔒 Step 5 — Transfer Types (TA Only)

*Org Setup → Transfer Types tab*

Customise the display names for the three transfer types.

| System Code | Default Name | What It Means |
|------------|-------------|---------------|
| PULL | Request Stock | Warehouse requests from a higher level |
| PUSH | Send Stock | Higher level pushes stock down |
| SISTER | Branch Exchange | Lateral transfer between warehouses — **requires Growth tier or higher**; not available on Starter |

For each transfer type:
1. Enter your organisation's preferred display name
2. Add a description (optional)
3. Set which levels can initiate it
4. Toggle Active/Inactive

`[SCREENSHOT: Transfer Types tab with custom display names]`

---

## 🔒 Step 6 — Approval Rules (TA Only)

*Org Setup → Approval Rules tab*

### Transfer Approval Rules

For each transfer type, create rules specifying:
- **From Level → To Level** (which direction this rule covers)
- **Quantity range** (0 to unlimited, or a specific range)
- **Approval steps** (who approves, in what order, within how many hours)

> **Example:** Request Stock | Warehouse Area → Sub Region | Qty: 5,001+ units | Step 1: Sub Region Manager (24h) | Step 2: Regional Manager (48h)

`[SCREENSHOT: Transfer Rules showing multi-step rule configuration]`

### Adjustment Approval Rules

Define when stock adjustments need approval by quantity per role level.

### Self-Approval Limits

Set a blanket self-approval quantity per role — transfers below this limit are automatically approved:

| Role | Example Limit |
|------|--------------|
| Warehouse Manager (WM) | Up to 5,000 units — self-approved instantly |
| Regional Manager (RM) | Up to 20,000 units — self-approved instantly |
| Factory Manager (NM) | Unlimited — all transfers self-approved |

💡 **Tip:** After setting up rules, check the **Approval Policies** page for a plain-language summary.

---

## Step 7 — Products & Categories

*Products page — TA and NM can create products; all roles can view*

### 🔒 Creating Product Categories (TA Only)

1. Go to Products → Categories
2. Click "+ Add Category" and enter a name (e.g. "Raw Materials", "Finished Goods")
3. Create all categories before adding products

### Adding Products (TA and NM)

1. Go to Products → click "+ Add Product"
2. Enter the product name, SKU (or auto-generate), and select a category
3. Enter a **Type Code** — 2–10 alphanumeric characters (e.g. RAW, FIN, PKG)
4. Select Unit of Measure (KG, Piece, Box, Roll, etc.)
5. Upload a product image (optional, max 2MB, JPG/PNG/WebP)
6. Click Save

`[SCREENSHOT: Add Product panel with all fields filled]`

### 🔒 Controlled Products — Special Approval Rules (TA Only)

For high-value or sensitive items that always require approval regardless of quantity:

1. Create the product first, then open it for editing
2. Scroll to "Minimum Approval Level" section
3. Enable the override for relevant transfer types
4. Choose: **Always** require approval, OR **above a quantity threshold**
5. Select which position must approve
6. Save — a 🔒 icon will appear on the product

> **Important — Controlled products require two approver interactions per transfer:**
> When a warehouse manager creates a PULL for a controlled product, the transfer does
> NOT skip the normal review step. The full flow is:
> DRAFT → Pending Review → (reviewer advances) → Pending Approval → (override approver approves) → Approved
>
> This means the process takes longer than a standard transfer. Communicate this to your
> warehouse managers so they plan ahead — especially for time-sensitive stock movements.

---

## Step 8 — Opening Stock

*Inventory page → Receive Stock — NM and TA can enter opening stock*

Before going live, record existing stock at each warehouse.

1. Go to the Inventory page
2. Select the warehouse
3. Click "Receive Stock"
4. Select the product and enter the opening quantity
5. Add a note (e.g. "Opening balance — June 2026")
6. Submit — stock is added to the ledger immediately
7. Repeat for each product at each warehouse

**⚠️ Important:** Opening stock entries are permanent and cannot be deleted (the ledger is immutable for audit purposes). Use Adjustments with reason code `COUNT_CORRECTION` to fix errors.

`[SCREENSHOT: Receive Stock panel with product and quantity fields]`

---

## 🔒 Step 9 — Branding (Optional, TA Only)

*Org Setup → Branding tab*

| Item | Specs |
|------|-------|
| Organisation Logo | Max 1MB, JPG/PNG/WebP. Shows in navigation header. |
| Organisation Banner | Max 3MB, JPG/PNG/WebP. Shows on Dashboard. |

1. Go to Org Setup → Branding tab
2. Upload logo and banner
3. Save — appears immediately across the platform

`[SCREENSHOT: Branding tab with logo and banner upload]`

---

## Organisation Manager (NM) — Quick Reference

*This section is for Organisation Managers and operational staff.*

### Your Responsibilities
- Create and manage products
- Review and approve transfers
- Initiate Send Stock (PUSH) transfers
- Monitor stock levels
- View approval policies

### Approving Transfers

1. Go to Transfers page
2. Find transfers with status "Pending Review" or "Pending Approval"
3. Review details (product, quantity, source, destination)
4. Click **Review** then **Approve** — or **Reject** if not appropriate

### Issuing & Dispatching Stock

1. Find an Approved transfer in the Transfers page
2. Click **Issue** to confirm stock is ready to move
3. Click **Dispatch** to confirm it has left the source
4. The destination WM will then receive it

> **Acting on Behalf:** If you Issue/Dispatch a transfer where the source warehouse belongs to another facility, the system shows "Acting on behalf of: [Warehouse Name]" and records this in the audit log.

### Viewing Approval Policies

Go to **Approval Policies** in the navigation to see:
- Your self-approval limits per transaction type
- Which products have 🔒 special approval requirements
- Full policy matrix (TA/SA see all levels)

---

## Ongoing Administration

### 🔒 Adding a New User (TA Only)
1. Org Setup → Personnel → "+ Add Person"
2. Enter name, email, role, assign to position, set password
3. Share credentials securely

### 🔒 Deactivating a User (TA Only)
1. Personnel list → find user → toggle Active to off
2. Account is immediately locked

> **⚠️ Note:** If a deactivated user has pending approvals, contact your SMART administrator. Automatic re-routing is coming in a future update.

### 🔒 Reactivating a User (TA Only)
1. Personnel list → find the inactive user → toggle Active back on
2. Their previous primary position is automatically restored — no need to manually reassign them
3. If they held additional positions (acting or delegate assignments), only the primary position is restored automatically; reassign any acting or delegate positions manually if still needed

### 🔒 Adjusting Approval Rules (TA Only)
1. Org Setup → Approval Rules → find and edit the rule
2. Update quantities, steps, or approver positions
3. Save — changes take effect immediately

### Known Limitations — Current Version

- **Adjustment approval position enforcement:** Adjustment approval rules specify a
  preferred approver position, but the system does not technically block other users
  with approval permission from approving. Enforce adjustment approval as a process
  discipline among your management team.

- **Transfer notes length:** Transfer notes are limited to 2000 characters.

- **PUSH /review not applicable:** PUSH and Sister transfers do not have a review
  step. Only PULL transfers go through the PENDING_REVIEW → PENDING_APPROVAL flow.
  Do not instruct staff to use the review action on PUSH transfers.

- **Coming soon:** bulk CSV import (for products or opening stock), dispatch strategy
  configuration (FEFO/FIFO/LIFO), and stock-count submission are visible in the product
  but marked **Coming soon** — the screens are there, but there is no backend behind them
  yet. If a button in your workspace is greyed out, hover over it: it will tell you whether
  it is a Coming soon feature, a plan limit, or your workspace being read-only.

---

## Common Questions

**Q: How do I upgrade or change my package?**
Contact your SMART administrator — package changes are made by SMART, not from your own
Tenant Admin page. New limits and features apply as soon as the change is made. On annual
billing an upgrade also produces a pro-rated **Proration** invoice for the months left in your
year (see [Plan Tiers](#plan-tiers)); a downgrade has no refund.

**Q: What is a "Proration" invoice?**
A one-off invoice for an upgrade or add-on made part-way through an annual billing year. It
covers only the whole months left in that year; the month the change was made in is free.

**Q: I signed up but never received the verification email.**
Use **Resend link** on the sign-in page or the verification page. Links expire after 48 hours.
If it still does not arrive, check your spam folder or contact SMART support.

**Q: Who is the "account owner"?**
The person who signed the workspace up (or the first TA created by SMART). They are the
main contact for the subscription and invoices.

**Q: Can I change the org structure after adding users?**
Yes — you can add new nodes and positions. Existing users keep their assignments. To remove a node, reassign its users first.

**Q: Can I change org levels later?**
You can add a level below your current bottom level at any time, and remove the bottom
level as long as it has no org nodes yet — the Organisation Levels tab shows both options
once you've saved your initial levels. Inserting or removing a level in the middle of the
stack is not self-service; contact SMART support if you need that.

**Q: What if an approver is unavailable?**
As TA, you can approve on behalf of any position. Find the pending item in the
Transfers or Adjustments page and approve or reject it directly — the audit log
records that you acted on their behalf.

**Q: A transfer is stuck in Pending Approval and no one is actioning it — what do I do?**
This can happen when the assigned approver position becomes vacant (user deactivated
or reassigned) after the transfer was submitted. The system does not alert you
automatically yet — check Transfers filtered by "Pending Approval" regularly. As TA
you can approve or reject any transfer you did not create yourself. To resolve:
1. Go to Transfers → filter by status "Pending Approval"
2. Find the stuck transfer and open it
3. Approve or reject it directly (the audit log records TA action)
4. Before creating new transfers from that node, assign a user to the approver
   position so future transfers route correctly

To prevent this: before deactivating any user who holds an approver position,
assign a replacement to that position first. The system will then route new
transfers to the replacement automatically.

**Q: Can a user have more than one position?**
Yes. Their permissions are the union of all assigned positions — useful for managers covering multiple areas.

**Q: What does the 🔒 icon mean on a product?**
The product is Controlled — it has special approval rules that override normal transfer flow. Even small quantities require specific approval. See the Approval Policies page for details.

**Q: What is the difference between Adjustment and Receive Stock?**
- **Receive Stock** — stock arrives at a warehouse (from supplier or opening balance)
- **Adjustment** — corrects the stock count (damage, theft, count error)

**Q: Can I undo a completed transfer?**
No — the ledger is immutable for audit integrity. Create a reverse transfer or use an Adjustment with reason code `RETURN`.

**Q: What happens when our contract ends?**
Nothing happens immediately. You get a 14-day **Expiring** warning before the end date,
then a 14-day **Grace** period after it — full access both times, just with a banner. Only
after that, if it still has not been renewed, does your workspace go **Read-only**: you can
still log in, view and export everything, but no new transactions, approvals, edits or
uploads. See [Contract dates](#contract-dates) above for the full stage table.

**Q: How do I request renewal?**
From your Plan tab, at any time — including while your workspace is already Read-only
(this is one of the few actions still available then). SMART's team sees your request and
will follow up to arrange payment; once SMART records it, full access returns immediately.

**Q: Why is a button greyed out?**
Three possible reasons: your workspace is **Read-only** (contract lapsed — see above), you
have hit a **plan limit** (e.g. your SKU cap), or the feature is marked **Coming soon** (not
built yet — see [Known Limitations](#known-limitations-current-version)). Hover over the
button — it tells you which one applies.

**Q: Can I cancel a Branch Exchange after it has been approved?**
No — once a Branch Exchange reaches Approved status it cannot be cancelled. Both warehouse managers have confirmed and stock is committed to the transfer. If the transfer cannot physically proceed, complete the receipt at the destination and use a stock Adjustment (reason: RETURN or DAMAGE) to correct the balance. Contact your administrator for assistance.

**Q: I forgot my password — can I reset it myself?**
Yes. On the sign-in page, click **Forgot password?** and enter your email address.
If the address matches an account, you'll receive a reset link by email — the
link is valid for 60 minutes and can only be used once. Opening it lets you set
a new password. Once set, all of your other active sessions are signed out, and
any login lockout on your account is cleared immediately. If no email arrives,
ask your Tenant Administrator to reset it for you instead (see the next
question).

**Q: How do I reset a user's password?**
Go to Settings → Personnel. Click the user's row to open their detail panel. Click "Reset Password" and confirm. The user's password will be reset to a temporary credential you provide. They will be forced to change it on their next login. This also signs the user out of all their existing sessions. You can use this for forgotten passwords or to unlock a compromised account.

**Q: What happens if a user gets locked out?**
After 5 consecutive failed login attempts, the account is automatically locked for 15 minutes. The user will see a message on the login screen. They can wait 15 minutes and retry, or contact you (the Tenant Admin) to verify they are using the correct credentials. The lockout clears automatically — no admin action is required. If the user successfully resets their password, the lockout counter is also cleared immediately.

**Q: Do I need to create separate adjustment rules for each warehouse or region?**
Yes. Each adjustment rule applies to the specific node it is configured for. If your organization has multiple warehouses or regions, you must create a separate rule for each one. A rule set for WHA1 will not automatically apply to WHA2 or WHB1. Work through each node systematically to ensure full coverage. A future update will allow you to apply rules across all nodes at the same org level in one step.

**Q: What is the difference between a tenant-wide LM and a node-assigned LM?**
When creating a Logistics Manager, you have two options. A tenant-wide LM (created without a position assignment) has read visibility across the entire organization — useful for a head logistics coordinator overseeing all warehouses. A node-assigned LM is linked to a specific position at a node and sees that node and all nodes beneath it — useful for a logistics coordinator overseeing one warehouse and its satellite depots. Choose based on the staff member's actual operational scope.

---

**Q: What happens when I assign a second person to an approver position?**
The system allows multiple users to hold the same position simultaneously. However, when
a transfer or adjustment is routed to that position for approval, the system picks one
holder — typically the most recently assigned. This means adding a second person to an
approver position can cause approval tasks to route to the new holder instead of the
original. If approval routing seems to go to the wrong person, check how many active
users hold that position (Settings → Positions → view holders). Remove or adjust
assignments so only the intended approver holds it at any time, unless both are
genuinely co-approvers.

---

**Q: What happens if I deactivate a user who is an approver on pending transfers?**
When a user is deactivated, their position assignment is removed automatically. The
system does not alert you automatically yet — pending transfers routed to that user
still show that user as the approver, so you need to check Transfers filtered by
"Pending Approval" yourself. As TA you can approve or reject any transfer you did not
create yourself. Adjustments: ordinary adjustments can be approved by you as usual. An
adjustment where a product approval minimum applied is locked to the specific person it
was routed to; if that person is deactivated it cannot be approved by anyone — reject
it, and ask the creator to resubmit so it routes to an active approver. Reassigning the
position does not move an already-submitted adjustment. Before deactivating an
approver, assign another user to their position so routing continues uninterrupted.

---

**Q: Can adjustment approval rules specify who must approve?**
Adjustment approval rules define quantity thresholds and routing behaviour, but the
system does not enforce which specific named position must approve at the final step —
any user with adjustment approval permission can post a pending adjustment. If you need
strict control over who approves adjustments, communicate this as a process requirement
to your managers rather than relying on technical enforcement.

---

**Q: What can a Logistics Manager (LM) actually do in the system?**
LM is a logistics and dispatch-focused role — not an inventory operations role.
An LM can:
- View stock at their assigned node and all nodes beneath it
- View and list transfers
- Receive and dispatch shipments
- View adjustments and product information

An LM cannot:
- Create or submit transfers
- Create or submit adjustments
- Approve transfers or adjustments

If you need someone with broader operational access (approvals, creating transfers),
assign them a Warehouse Manager (WM) or Regional Manager (RM) role instead.
Note: if created without a node assignment (tenant-wide LM), the LM can view stock
across the entire organisation but still has the same action restrictions above.

---

**Q: Can all users initiate PUSH (Send Stock) transfers?**
No. PUSH transfers can only be initiated by users at Level 1 (Factory/Main) and
Level 2 (Regional) of your org hierarchy — typically NM and RM roles. This reflects
how stock flows in distribution: factories and regional hubs push stock downward to
warehouses, not the other way around.

Warehouse Managers (WM), Logistics Managers (LM), and satellite staff can only
initiate PULL (Request Stock) or Sister (lateral exchange) transfers. If a WM needs
stock sent to their warehouse, they should submit a PULL request — their NM or RM
will see and approve it.

---

**Q: I added a new satellite depot — do approval rules apply to it automatically?**
No. When you add a new node (warehouse or satellite), it has no transfer or adjustment
approval rules until you create them. Until rules are added, transfers from that node
will route through the system's default bands, which may not match your intended policy.
After creating any new node, go to Settings → Approval Rules and add the appropriate
transfer and adjustment rules for that node before staff begin using it.

---

**Q: A staff member was promoted or moved to a different role. What do I need to do?**
When reassigning a user to a new position:
1. Assign them PRIMARY at the new position (their scope updates immediately on next login)
2. Remove their old position assignment if they should no longer hold it
   — use force-remove (SA token required for sole PRIMARY removal)
3. If the old position had pending approvals routed to it, those are not escalated
   automatically — check Transfers/Adjustments filtered by "Pending Approval" yourself.
   Pending transfers you can approve or reject directly as TA. Pending adjustments can
   also be approved as usual, unless a product approval minimum locked the adjustment to
   that specific person — in that case it cannot be approved by anyone and must be
   rejected, with the creator resubmitting so it routes to an active approver. Assigning
   the replacement first avoids all of this for anything submitted afterward.

If the user moves to a higher level (e.g. WM → RM), their old WM scope is replaced
by the new RM scope on next login. If they move to a lower level (e.g. RM → WM), their
access narrows accordingly. Always verify by having the user log out and back in after
any position change.

---

## Setup Checklist

### 🔒 Tenant Administrator Checklist

**Account & Plan:**
- [ ] Email address verified (self sign-up)
- [ ] Settings → Tenant Admin → Plan reviewed — package, limits and features as expected
- [ ] Organisation profile and contact people completed (Profile and Contact tabs)
- [ ] First invoice reviewed and payment arranged (if issued)

**Organisation Structure:**
- [ ] Organisation levels defined
- [ ] Organisation tree complete — all nodes created
- [ ] Positions created for every node (main + assistant recommended)
- [ ] Transfer types named with custom display names
- [ ] Transfer approval rules configured for all active types
- [ ] Adjustment approval rules configured
- [ ] Self-approval limits set per role level

**People & Products:**
- [ ] All staff added and assigned to positions
- [ ] Initial passwords shared securely
- [ ] Product categories created
- [ ] All products added with type codes and units
- [ ] Controlled products configured with 🔒 approval rules
- [ ] Product images uploaded (optional)
- [ ] Opening stock entered at all warehouse nodes

**Verification:**
- [ ] Approval Policies page reviewed — rules display correctly
- [ ] Test transfer created and approved through full lifecycle
- [ ] At least one WM, RM, and NM user confirmed access
- [ ] Branding uploaded (optional)
- [ ] Audit Log checked — setup actions recorded

---

> **📋 Pre-Launch Reminder:** Before sharing with customers, replace all screenshot placeholders with real screenshots. Translate to Amharic or Oromifa if required for Ethiopian customers. Review all TA-only sections against the final permission matrix.

---

*Document Version: 1.6 | Last Updated: October 2026 | Maintained by: Development team*
*1.5 (2026-10-10) — added contract stages (Active/Expiring/Grace/Read-only), the
read-only access gate, how to request a renewal, and Coming soon status for bulk CSV
import, dispatch strategy and stock-count submission.*
*1.5 — split into two parts: Getting Started (before sign-up) is now its own document;
this guide is Part 2, covering workspace setup from Plan Tiers onward.*
*1.3 — pro-rated upgrades and add-ons on annual billing; package changes are made by SMART only.*
*1.2 — self sign-up, email verification, packages with prices and VAT, subscription and invoices, read-only contract.*
